"""TaskSprint lab FastAPI application (Architecture A2, A4, A8 — Phase 02 subset).

Run locally (one worker, as required by A5):
    TASKSPRINT_ENV_FILE=.local/lab.env uv run uvicorn --factory services.lab.main:create_app --workers 1

Only ``GET /healthz`` is public. Every other route passes the global
``authorize`` dependency: token -> identity, then the route's entry in
``auth.PERMISSIONS``; a route without an entry is denied (deny by default).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import SERVICE_VERSION, app_commands, audit, candidates, instructor, memory, releases, runs, state, testing
from .auth import PUBLIC_ROUTES, Authenticator, Identity, allowed_roles
from .config import Settings, load_settings, valid_workspace_id
from .runner_client import RunnerClient, build_runner
from .schemas import (AppCommand, CandidateSubmit, InstructorAction, MemorySave, RunCreate, StoryCreate, TestRunCreate,
                      TransitionRequest)
from .store import LabError, Store, require_active_workspace

log = logging.getLogger("tasksprint.lab")
WORKSPACE_HEADER = "x-tasksprint-workspace"
RUN_HEADER = "x-tasksprint-run"


# ------------------------------------------------------------------ ASGI middleware
class RequestContextMiddleware:
    """Server-generated request IDs and a hard request-body size limit."""

    def __init__(self, app: Any, max_body_bytes: int):
        self.app = app
        self.max_body = max_body_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = audit.new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_body
            except ValueError:
                too_big = True
            if too_big:
                await _send_error(send_with_id, 413, "REQUEST_TOO_LARGE", "request body exceeds the size limit", request_id)
                return
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > self.max_body:
                await _send_error(send_with_id, 413, "REQUEST_TOO_LARGE", "request body exceeds the size limit", request_id)
                return
        replayed = False

        async def replay() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send_with_id)


async def _send_error(send: Callable, status: int, code: str, message: str, request_id: str) -> None:
    resp = JSONResponse(status_code=status, content=_error_body(code, message, request_id))
    await send({"type": "http.response.start", "status": status, "headers": resp.raw_headers})
    await send({"type": "http.response.body", "body": resp.body})


def _error_body(code: str, message: str, request_id: str, extra: dict | None = None) -> dict:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id}}
    public = {k: v for k, v in (extra or {}).items() if k != "audit"}
    if public:
        body["error"]["details"] = public
    return body


def _rid(request: Request) -> str:
    return request.scope.get("state", {}).get("request_id", "req_unknown")


# ------------------------------------------------------------------ context objects
@dataclass(frozen=True)
class Ctx:
    identity: Identity
    workspace_id: str
    run_id: str | None
    request_id: str


def create_app(settings: Settings | None = None, runner: RunnerClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    runner = runner if runner is not None else build_runner(settings)
    store = Store(settings.db_path, settings.journal_mode)
    store.migrate()
    authenticator = Authenticator(settings.token_hashes)

    def denial_event(request_id: str, identity: Identity, action: str, workspace_id: str | None,
                     run_id: str | None, err: LabError) -> None:
        details = {"code": err.code, **err.extra.get("audit", {})}
        try:
            with store.write() as conn:
                if workspace_id is not None and conn.execute(
                        "SELECT 1 FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone() is None:
                    workspace_id = None
                audit.record_event(conn, request_id=request_id, actor_role=identity.role, action=action,
                                   outcome="denied" if err.status in (401, 403) else "rejected",
                                   workspace_id=workspace_id, run_id=run_id, details=details)
        except sqlite3.Error:
            log.exception("could not record denial event request_id=%s", request_id)

    # -------------------------------------------------------------- dependencies
    def authorize(request: Request) -> Identity | None:
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        if (request.method, path) in PUBLIC_ROUTES:
            return None
        identity = authenticator.authenticate(request.headers.get("authorization"))
        if identity is None:
            # Unauthenticated denials are logged (redacted) but not written to the DB.
            log.info("auth denied request_id=%s path=%s", _rid(request), path)
            raise LabError(401, "UNAUTHENTICATED", "a valid TaskSprint role token is required")
        roles = allowed_roles(request.method, path or "")
        if roles is None or identity.role not in roles:
            ws = request.headers.get(WORKSPACE_HEADER)
            err = LabError(403, "FORBIDDEN", "this credential is not permitted to perform this operation",
                           {"audit": {"route": f"{request.method} {path}"}})
            denial_event(_rid(request), identity, "authz.denied", ws if ws and valid_workspace_id(ws) else None, None, err)
            raise err
        request.state.identity = identity
        return identity

    def ctx(request: Request) -> Ctx:
        """Trusted run context: workspace from header/run, never from body fields."""
        identity: Identity = request.state.identity
        ws_id = request.headers.get(WORKSPACE_HEADER, "")
        if not valid_workspace_id(ws_id):
            raise LabError(400, "WORKSPACE_REQUIRED", f"header {WORKSPACE_HEADER} with a valid workspace id is required")
        run_id = request.headers.get(RUN_HEADER)
        with store.write() if run_id else store.read() as conn:
            ws = require_active_workspace(conn, ws_id)
            if run_id:
                try:
                    runs.consume_action(conn, run_id=run_id, role=identity.role, workspace=ws)
                except LabError as err:
                    failed = err
                else:
                    failed = None
        if run_id and failed is not None:
            denial_event(_rid(request), identity, "run.action", ws_id, None, failed)
            raise failed
        return Ctx(identity, ws_id, run_id, _rid(request))

    def write_op(c: Ctx, action: str, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        return audited(c, action, lambda: _in_write(fn))

    def _in_write(fn: Callable[[sqlite3.Connection], Any]) -> Any:
        with store.write() as conn:
            return fn(conn)

    def audited(c: Ctx, action: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except LabError as err:
            if err.status in (403, 409, 422, 429):
                denial_event(c.request_id, c.identity, action, c.workspace_id, c.run_id, err)
            raise

    # -------------------------------------------------------------- app + handlers
    app = FastAPI(title="TaskSprint lab", version=SERVICE_VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None, dependencies=[Depends(authorize)])
    app.state.settings = settings
    app.state.store = store
    app.state.runner_configured = runner is not None
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_body_bytes)

    @app.exception_handler(LabError)
    async def _lab_error(request: Request, err: LabError) -> JSONResponse:
        return JSONResponse(status_code=err.status, content=_error_body(err.code, err.message, _rid(request), err.extra))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, err: RequestValidationError) -> JSONResponse:
        # Never echo submitted input back (it could contain a pasted secret).
        problems = [{"loc": [str(p) for p in e.get("loc", [])][-3:], "type": e.get("type")} for e in err.errors()][:10]
        return JSONResponse(status_code=422, content=_error_body("VALIDATION_ERROR", "request does not match the schema",
                                                                 _rid(request), {"problems": problems}))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, err: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(err.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=err.status_code, content=_error_body(code, code.lower().replace("_", " "), _rid(request)))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, err: Exception) -> JSONResponse:
        log.exception("unhandled error request_id=%s", _rid(request))
        return JSONResponse(status_code=500, content=_error_body("INTERNAL_ERROR", "internal error", _rid(request)))

    # -------------------------------------------------------------- routes
    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "service": "tasksprint-lab"}

    @app.post("/v1/runs", status_code=201)
    def create_run(body: RunCreate, request: Request) -> dict:
        identity: Identity = request.state.identity
        ws_id = request.headers.get(WORKSPACE_HEADER, "")
        if not valid_workspace_id(ws_id):
            raise LabError(400, "WORKSPACE_REQUIRED", f"header {WORKSPACE_HEADER} with a valid workspace id is required")
        c = Ctx(identity, ws_id, None, _rid(request))

        def op(conn: sqlite3.Connection) -> dict:
            ws = require_active_workspace(conn, ws_id)
            run = runs.create_run(conn, workspace=ws, role=identity.role, conversation_id=body.conversation_id,
                                  parent_run_id=body.parent_run_id)
            audit.record_event(conn, request_id=c.request_id, actor_role=identity.role, action="run.create", outcome="ok",
                               workspace_id=ws_id, run_id=run["run_id"],
                               details={"depth": run["depth"], "parent_run_id": run["parent_run_id"]})
            return run
        return write_op(c, "run.create", op)

    @app.get("/v1/state")
    def get_state(c: Ctx = Depends(ctx)) -> dict:
        with store.read() as conn:
            return state.read_state(conn, c.workspace_id)

    @app.post("/v1/stories", status_code=201)
    def record_story(body: StoryCreate, c: Ctx = Depends(ctx)) -> dict:
        return write_op(c, "story.create", lambda conn: state.StateWriter(conn, c.request_id, c.identity.role, c.run_id)
                        .create_story(c.workspace_id, title=body.title, narrative=body.narrative,
                                      criteria=list(body.criteria), evidence_refs=list(body.evidence_refs)))

    @app.post("/v1/state/transitions")
    def transition(body: TransitionRequest, c: Ctx = Depends(ctx)) -> dict:
        return write_op(c, "story.transition", lambda conn: state.StateWriter(conn, c.request_id, c.identity.role, c.run_id)
                        .transition(c.workspace_id, story_id=body.story_id, to_stage=body.to_stage,
                                    expected_revision=body.expected_revision, candidate_id=body.candidate_id,
                                    test_run_id=body.test_run_id))

    @app.get("/v1/memory")
    def read_memory(c: Ctx = Depends(ctx)) -> dict:
        with store.read() as conn:
            return memory.read_preferences(conn, workspace_id=c.workspace_id, owner=c.identity.principal)

    @app.post("/v1/memory", status_code=201)
    def save_memory(body: MemorySave, c: Ctx = Depends(ctx)) -> dict:
        def op(conn: sqlite3.Connection) -> dict:
            saved = memory.save_preference(conn, workspace_id=c.workspace_id, owner=c.identity.principal, key=body.key,
                                           value=body.value, ttl_days=body.ttl_days,
                                           source=f"save_preference:{c.identity.role}:{c.request_id}")
            audit.record_event(conn, request_id=c.request_id, actor_role=c.identity.role, action="memory.save",
                               outcome="ok", workspace_id=c.workspace_id, run_id=c.run_id,
                               details={"key": body.key, "value": body.value})
            return saved
        return write_op(c, "memory.save", op)

    @app.get("/v1/candidates/{candidate_id}")
    def read_candidate(candidate_id: str, c: Ctx = Depends(ctx)) -> dict:
        if not candidate_id.startswith("cand_") or len(candidate_id) != 29:
            raise LabError(404, "CANDIDATE_NOT_FOUND", "candidate does not exist in this workspace")
        with store.read() as conn:
            row = candidates.get_candidate(conn, c.workspace_id, candidate_id)
            if row is None:
                raise LabError(404, "CANDIDATE_NOT_FOUND", "candidate does not exist in this workspace")
            if not candidates.verify_integrity(row):
                raise LabError(500, "ARTIFACT_INTEGRITY_ERROR", "stored candidate does not match its hash")
            allowed = candidates.source_read_allowed(conn, c.workspace_id, c.identity.role, row)
            diff = candidates.diff_from_base(conn, c.workspace_id, c.identity.role, row) if allowed else None
        if not allowed:
            denial_event(c.request_id, c.identity, "candidate.read", c.workspace_id, c.run_id,
                         LabError(403, "SOURCE_NOT_PERMITTED", "", {"audit": {"candidate_id": candidate_id}}))
            raise LabError(403, "SOURCE_NOT_PERMITTED", "this candidate's source is not readable by this role")
        return {**candidates.candidate_view(row, include_source=True), "base_diff": diff}

    @app.post("/v1/candidates", status_code=201)
    def submit_candidate(body: CandidateSubmit, c: Ctx = Depends(ctx)) -> dict:
        def op(conn: sqlite3.Connection) -> dict:
            view, created = candidates.put_candidate(conn, workspace_id=c.workspace_id, source=body.source.encode("utf-8"),
                                                     origin="agent-generated", author_role=c.identity.role,
                                                     label="agent-submission", base_sha256=body.base_sha256)
            audit.record_event(conn, request_id=c.request_id, actor_role=c.identity.role, action="candidate.submit",
                               outcome="ok" if created else "duplicate", workspace_id=c.workspace_id, run_id=c.run_id,
                               details={"candidate_id": view["candidate_id"], "sha256": view["sha256"]})
            return {**view, "created": created}
        return write_op(c, "candidate.submit", op)

    @app.get("/v1/releases")
    def get_releases(c: Ctx = Depends(ctx)) -> dict:
        with store.read() as conn:
            return releases.release_status(conn, c.workspace_id)

    @app.get("/v1/app-health")
    def get_app_health(c: Ctx = Depends(ctx)) -> dict:
        with store.read() as conn:
            return releases.app_health(conn, c.workspace_id)

    @app.get("/v1/events")
    def get_events(c: Ctx = Depends(ctx), limit: int = Query(20, ge=1, le=50)) -> dict:
        with store.read() as conn:
            return {"events": audit.list_events(conn, c.workspace_id, limit)}

    @app.post("/v1/test-runs", status_code=201)
    def create_test_run(body: TestRunCreate, c: Ctx = Depends(ctx)) -> dict:
        return audited(c, "test_run.create", lambda: testing.run_protected_suite(
            store, runner, workspace_id=c.workspace_id, candidate_id=body.candidate_id, request_id=c.request_id,
            actor_role=c.identity.role, run_id=c.run_id))

    @app.get("/v1/test-runs/{test_run_id}")
    def read_test_run(test_run_id: str, c: Ctx = Depends(ctx)) -> dict:
        if not (test_run_id.startswith("tr_") and len(test_run_id) == 27):
            raise LabError(404, "TEST_RUN_NOT_FOUND", "test run does not exist in this workspace")
        with store.read() as conn:
            return testing.get_report(conn, c.workspace_id, test_run_id)

    @app.post("/v1/app/commands")
    def app_command(body: AppCommand, c: Ctx = Depends(ctx)) -> dict:
        cmd = app_commands.parse(body.command)

        def record(conn: sqlite3.Connection, result: dict) -> None:
            audit.record_event(conn, request_id=c.request_id, actor_role=c.identity.role, action="app.complete",
                               outcome=result["code"], workspace_id=c.workspace_id, run_id=c.run_id,
                               details={"task_id": cmd.arg,
                                        "artifact_sha256": (result["data"].get("artifact") or {}).get("sha256"),
                                        "tasks_changed": result["data"].get("tasks_changed"),
                                        "runner": (result["data"].get("evaluation") or {}).get("evaluated_by"),
                                        "ops": (result["data"].get("evaluation") or {}).get("ops")})

        if cmd.verb == "complete":
            return audited(c, "app.complete", lambda: app_commands.complete_task(
                store, runner, c.workspace_id, cmd.arg or "", record=record))

        def op(conn: sqlite3.Connection) -> dict:
            result = app_commands.execute(conn, c.workspace_id, cmd)
            if cmd.verb in ("add", "complete"):
                audit.record_event(conn, request_id=c.request_id, actor_role=c.identity.role, action=f"app.{cmd.verb}",
                                   outcome=result["code"], workspace_id=c.workspace_id, run_id=c.run_id,
                                   details={"task_id": (result["data"].get("task") or {}).get("id") or cmd.arg,
                                            "artifact_sha256": (result["data"].get("artifact") or {}).get("sha256")})
            return result
        return write_op(c, f"app.{cmd.verb}", op)

    @app.post("/v1/instructor/actions")
    def instructor_action(body: InstructorAction, request: Request) -> dict:
        identity: Identity = request.state.identity
        c = Ctx(identity, body.workspace_id, None, _rid(request))
        if body.action != "load_fixture" and body.fixture is not None:
            raise LabError(422, "UNEXPECTED_FIELD", "fixture is only accepted with load_fixture")
        if body.action == "seed":
            return write_op(c, "instructor.seed", lambda conn: instructor.seed(conn, settings, body.workspace_id, c.request_id))
        if body.action == "load_fixture":
            return write_op(c, "instructor.load_fixture", lambda conn: instructor.load_fixture(
                conn, settings, body.workspace_id, body.fixture, c.request_id))
        with store.read() as conn:
            return instructor.reset_preview(conn, settings, body.workspace_id)

    return app
