"""TaskSprint lab FastAPI application (Architecture A2, A4, A7, A8 — Phase 02-04 subset).

Run locally (one worker, as required by A5):
    TASKSPRINT_ENV_FILE=.local/lab.env uv run uvicorn --factory services.lab.main:create_app --workers 1

Only ``GET /healthz`` is public. Every other route passes the global
``authorize`` dependency: token -> identity, then the route's entry in
``auth.PERMISSIONS``; a route without an entry is denied (deny by default).
``/mcp`` is the MCP Streamable HTTP endpoint (``mcp.py``); it authenticates
every request itself with the same role tokens and the same permission table.
"""
from __future__ import annotations

import contextlib
import logging
import sqlite3
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Route

from . import SERVICE_VERSION, app_commands, audit, instructor, runs
from .auth import PUBLIC_ROUTES, Authenticator, Identity, allowed_roles
from .config import Settings, load_settings, valid_workspace_id
from .mcp import MCP_PATH, McpEndpoint
from .operations import Ctx, LabOps, RunCheckedStore
from .retrieval import KnowledgeBase
from .runner_client import RunnerClient, build_runner
from .schemas import (A2AExchangeCreate, AgentEvaluationCreate, AppCommand, ApprovalCreate, CandidateSubmit,
                      InstructorAction, InstructorKnowledgeSearch, KnowledgeSearch, MemorySave, ReadinessQuery,
                      ReleaseExecutionCreate, ReleasePlanCreate, RunCreate, StoryCreate, TestRunCreate,
                      TransitionRequest)
from .skills import SkillCatalog
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


# ------------------------------------------------------------------ application
def create_app(settings: Settings | None = None, runner: RunnerClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    runner = runner if runner is not None else build_runner(settings)
    store = Store(settings.db_path, settings.journal_mode)
    store.migrate()
    authenticator = Authenticator(settings.token_hashes)
    knowledge = KnowledgeBase(store, Path(settings.knowledge_dir))
    knowledge.ingest()
    skills = SkillCatalog(store, Path(settings.skills_dir))
    skills.load()
    ops = LabOps(settings, store, runner, knowledge, skills)
    mcp_endpoint = McpEndpoint(settings, ops, authenticator)

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
            ops.denial_event(_rid(request), identity, "authz.denied", ws if ws and valid_workspace_id(ws) else None,
                             None, err)
            raise err
        request.state.identity = identity
        return identity

    def ctx(request: Request) -> Ctx:
        """Trusted run context: workspace from header/run, never from body fields."""
        identity: Identity = request.state.identity
        ws_id = request.headers.get(WORKSPACE_HEADER, "")
        if not valid_workspace_id(ws_id):
            raise LabError(400, "WORKSPACE_REQUIRED", f"header {WORKSPACE_HEADER} with a valid workspace id is required")
        return ops.bind(identity, ws_id, request.headers.get(RUN_HEADER), _rid(request))

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp_endpoint.lifespan():
            yield

    # -------------------------------------------------------------- app + handlers
    app = FastAPI(title="TaskSprint lab", version=SERVICE_VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None, dependencies=[Depends(authorize)], lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.ops = ops
    app.state.mcp = mcp_endpoint
    app.state.runner_configured = runner is not None
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_body_bytes)
    # Not an APIRoute: the MCP endpoint authenticates each request itself (mcp.py).
    app.router.routes.append(Route(MCP_PATH, endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"]))

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
        return ops.write_op(c, "run.create", op)

    @app.get("/v1/state")
    def get_state(c: Ctx = Depends(ctx)) -> dict:
        return ops.get_state(c)

    @app.post("/v1/stories", status_code=201)
    def record_story(body: StoryCreate, c: Ctx = Depends(ctx)) -> dict:
        return ops.record_story(c, body)

    @app.post("/v1/state/transitions")
    def transition(body: TransitionRequest, c: Ctx = Depends(ctx)) -> dict:
        return ops.transition(c, body)

    @app.get("/v1/memory")
    def read_memory(c: Ctx = Depends(ctx)) -> dict:
        return ops.read_memory(c)

    @app.post("/v1/memory", status_code=201)
    def save_memory(body: MemorySave, c: Ctx = Depends(ctx)) -> dict:
        return ops.save_memory(c, body)

    @app.get("/v1/candidates/{candidate_id}")
    def read_candidate(candidate_id: str, c: Ctx = Depends(ctx)) -> dict:
        return ops.read_candidate(c, candidate_id)

    @app.post("/v1/candidates", status_code=201)
    def submit_candidate(body: CandidateSubmit, c: Ctx = Depends(ctx)) -> dict:
        return ops.submit_candidate(c, body)

    @app.get("/v1/releases")
    def get_releases(c: Ctx = Depends(ctx)) -> dict:
        return ops.release_status(c)

    @app.get("/v1/app-health")
    def get_app_health(c: Ctx = Depends(ctx)) -> dict:
        return ops.app_health(c)

    @app.get("/v1/events")
    def get_events(c: Ctx = Depends(ctx), limit: int = Query(20, ge=1, le=50)) -> dict:
        return ops.events(c, limit)

    @app.post("/v1/test-runs", status_code=201)
    def create_test_run(body: TestRunCreate, c: Ctx = Depends(ctx)) -> dict:
        return ops.create_test_run(c, body)

    @app.get("/v1/test-runs/{test_run_id}")
    def read_test_run(test_run_id: str, c: Ctx = Depends(ctx)) -> dict:
        return ops.read_test_run(c, test_run_id)

    @app.get("/v1/readiness")
    def get_readiness(c: Ctx = Depends(ctx), candidate_id: str | None = Query(None, max_length=29)) -> dict:
        q = ReadinessQuery(candidate_id=candidate_id)
        return ops.readiness(c, q.candidate_id)

    @app.post("/v1/release-plans", status_code=201)
    def create_release_plan(body: ReleasePlanCreate, c: Ctx = Depends(ctx)) -> dict:
        return ops.create_release_plan(c, body)

    @app.get("/v1/release-plans/{plan_id}")
    def read_release_plan(plan_id: str, c: Ctx = Depends(ctx)) -> dict:
        return ops.read_release_plan(c, plan_id)

    @app.post("/v1/approvals", status_code=201)
    def record_approval(body: ApprovalCreate, c: Ctx = Depends(ctx)) -> dict:
        return ops.record_approval(c, body)

    @app.post("/v1/release-executions", status_code=201)
    def execute_release(body: ReleaseExecutionCreate, c: Ctx = Depends(ctx)) -> Any:
        result = ops.execute_release(c, body)
        return JSONResponse(status_code=200, content=result) if result["replayed"] else result

    @app.post("/v1/agent-evaluations", status_code=201)
    def record_agent_evaluation(body: AgentEvaluationCreate, c: Ctx = Depends(ctx)) -> dict:
        return ops.record_agent_evaluation(c, body)

    @app.post("/v1/a2a-exchanges", status_code=201)
    def record_a2a_exchange(body: A2AExchangeCreate, c: Ctx = Depends(ctx)) -> dict:
        return ops.record_a2a_exchange(c, body)

    @app.get("/v1/a2a-exchanges/{exchange_id}")
    def read_a2a_exchange(exchange_id: str, c: Ctx = Depends(ctx)) -> dict:
        return ops.read_a2a_exchange(c, exchange_id)

    @app.post("/v1/knowledge/search")
    def knowledge_search(body: KnowledgeSearch, c: Ctx = Depends(ctx)) -> dict:
        return ops.knowledge_search(c, body)

    @app.post("/v1/instructor/knowledge/search")
    def instructor_knowledge_search(body: InstructorKnowledgeSearch, request: Request) -> dict:
        return ops.instructor_knowledge_search(request.state.identity, _rid(request), body)

    @app.get("/v1/skills")
    def list_skills(c: Ctx = Depends(ctx)) -> dict:
        return ops.list_skills(c)

    @app.get("/v1/skills/{name}/{version}")
    def load_skill(name: str, version: str, c: Ctx = Depends(ctx)) -> dict:
        return ops.load_skill(c, name, version)

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
            return ops.audited(c, "app.complete", lambda: app_commands.complete_task(
                RunCheckedStore(store, lambda conn: ops.recheck_run(conn, c)), runner, c.workspace_id, cmd.arg or "", record=record))

        def op(conn: sqlite3.Connection) -> dict:
            result = app_commands.execute(conn, c.workspace_id, cmd)
            if cmd.verb in ("add", "complete"):
                audit.record_event(conn, request_id=c.request_id, actor_role=c.identity.role, action=f"app.{cmd.verb}",
                                   outcome=result["code"], workspace_id=c.workspace_id, run_id=c.run_id,
                                   details={"task_id": (result["data"].get("task") or {}).get("id") or cmd.arg,
                                            "artifact_sha256": (result["data"].get("artifact") or {}).get("sha256")})
            return result
        return ops.write_op(c, f"app.{cmd.verb}", op)

    @app.post("/v1/instructor/actions")
    def instructor_action(body: InstructorAction, request: Request) -> dict:
        identity: Identity = request.state.identity
        c = Ctx(identity, body.workspace_id, None, _rid(request))
        unexpected = body.unexpected_fields()
        if unexpected:
            raise LabError(422, "UNEXPECTED_FIELD", f"{', '.join(unexpected)} not accepted with {body.action}")
        ws, rid = body.workspace_id, c.request_id
        handlers = {
            "seed": lambda conn: instructor.seed(conn, settings, ws, rid),
            "load_fixture": lambda conn: instructor.load_fixture(conn, settings, ws, body.fixture, rid),
            "confirm_scope": lambda conn: instructor.confirm_scope(conn, settings, ws, body.story_id,
                                                                   body.expected_revision, rid),
            "drill_enable": lambda conn: instructor.drill(conn, settings, ws, True, body.fault_type, body.candidate_id,
                                                          body.ttl_minutes, rid),
            "drill_disable": lambda conn: instructor.drill(conn, settings, ws, False, body.fault_type,
                                                           body.candidate_id, None, rid),
            "stop": lambda conn: instructor.stop(conn, settings, ws, True, body.reason, rid),
            "resume": lambda conn: instructor.stop(conn, settings, ws, False, None, rid),
            "reset_confirm": lambda conn: instructor.reset_confirm(conn, settings, ws, body.confirm, rid),
        }
        if body.action == "reset_preview":
            with store.read() as conn:
                return instructor.reset_preview(conn, settings, ws)
        return ops.write_op(c, f"instructor.{body.action}", handlers[body.action])

    return app
