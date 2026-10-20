"""TaskSprint runner service (Architecture A2, A6).

    TS_RUNNER_TOKEN=... uvicorn --factory services.runner.main:create_app --port 8001 --workers 1

Routes:
    GET  /healthz       public liveness, no data
    POST /v1/evaluate   transport-token bearer; {source, source_sha256, tasks, task_id}

The runner is stateless: no database, no files, no role tokens, no model or
platform keys. ``TS_RUNNER_TOKEN`` only authorizes evaluation requests from the
lab. Configuration refuses to start if lab or platform secrets are present in
its environment, and refuses to run as root.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import GRAMMAR_VERSION, RUNNER_VERSION
from .interpreter import DEFAULT_LIMITS, CandidateError, Limits, evaluate
from .validator import MAX_AST_DEPTH, MAX_AST_NODES, MAX_SOURCE_BYTES, ValidationRejected, validate_source

log = logging.getLogger("tasksprint.runner")

MAX_BODY_BYTES = 48 * 1024
MAX_INPUT_BYTES = 32 * 1024
MAX_TASKS = 100
MAX_TITLE = 120
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
TOKEN_MIN_LEN = 32

# Variables that must never reach the runner (fail closed if present).
_FORBIDDEN_ENV = (
    re.compile(r"^TASKSPRINT_(DB_PATH|ENV_FILE|API_BASE)$"),
    re.compile(r"^TS_(?!RUNNER_TOKEN$)[A-Z0-9_]+$"),  # role tokens, their hashes, TS_A2A_API_KEY
    re.compile(r"^LANGFLOW_"),
    re.compile(r"^(RAILWAY_TOKEN|RAILWAY_API_TOKEN|DATABASE_URL|PGPASSWORD)$"),
    re.compile(r"_API_KEY$"),
)


class RunnerConfigError(ValueError):
    """Invalid runner configuration. Messages never contain values."""


@dataclass(frozen=True)
class RunnerSettings:
    token: str = field(repr=False)
    limits: Limits = DEFAULT_LIMITS
    allow_root: bool = False

    @property
    def token_digest(self) -> bytes:
        return hashlib.sha256(self.token.encode("utf-8")).digest()

    def describe(self) -> dict[str, Any]:
        """Non-secret configuration summary (used by tests to prove what the runner holds)."""
        return {"fields": ["token", "limits", "allow_root"], "token_configured": bool(self.token),
                "limits": self.limits.__dict__.copy()}


def forbidden_env_names(env: dict[str, str]) -> list[str]:
    return sorted(k for k in env if any(p.search(k) for p in _FORBIDDEN_ENV))


def load_runner_settings(env: dict[str, str] | None = None) -> RunnerSettings:
    source = dict(os.environ if env is None else env)
    bad = forbidden_env_names(source)
    if bad:
        raise RunnerConfigError("runner environment contains variables it must not hold: " + ", ".join(bad))
    token = source.get("TS_RUNNER_TOKEN", "").strip()
    if len(token) < TOKEN_MIN_LEN:
        raise RunnerConfigError(f"TS_RUNNER_TOKEN is required (at least {TOKEN_MIN_LEN} characters)")
    return RunnerSettings(token=token)


# ------------------------------------------------------------------ request validation
class BadRequest(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _validate_request(payload: Any) -> tuple[str, str, list[dict[str, Any]], str]:
    if type(payload) is not dict or set(payload) != {"source", "source_sha256", "tasks", "task_id"}:
        raise BadRequest(422, "INVALID_REQUEST", "body must be exactly {source, source_sha256, tasks, task_id}")
    source, digest, tasks, task_id = payload["source"], payload["source_sha256"], payload["tasks"], payload["task_id"]
    if type(source) is not str or not 1 <= len(source.encode("utf-8")) <= MAX_SOURCE_BYTES:
        raise BadRequest(413, "SOURCE_TOO_LARGE", f"source must be 1..{MAX_SOURCE_BYTES} bytes of text")
    if type(digest) is not str or not _HEX64.match(digest):
        raise BadRequest(422, "INVALID_REQUEST", "source_sha256 must be a SHA-256 hex digest")
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != digest:
        raise BadRequest(422, "SOURCE_HASH_MISMATCH", "source bytes do not match source_sha256")
    if type(task_id) is not str or not _TASK_ID.match(task_id):
        raise BadRequest(422, "INVALID_REQUEST", "task_id must be 1..32 characters [A-Za-z0-9_-]")
    if type(tasks) is not list:
        raise BadRequest(422, "INVALID_REQUEST", "tasks must be a list")
    if len(tasks) > MAX_TASKS:
        raise BadRequest(413, "INPUT_TOO_LARGE", f"at most {MAX_TASKS} tasks")
    for t in tasks:
        if type(t) is not dict or set(t) != {"id", "title", "completed"}:
            raise BadRequest(422, "INVALID_REQUEST", "each task must be exactly {id, title, completed}")
        if type(t["id"]) is not str or not _TASK_ID.match(t["id"]):
            raise BadRequest(422, "INVALID_REQUEST", "task id must be 1..32 characters [A-Za-z0-9_-]")
        if type(t["title"]) is not str or not 1 <= len(t["title"]) <= MAX_TITLE:
            raise BadRequest(422, "INVALID_REQUEST", f"task title must be 1..{MAX_TITLE} characters")
        if type(t["completed"]) is not bool:
            raise BadRequest(422, "INVALID_REQUEST", "task completed must be a boolean")
    if len(json.dumps(tasks, separators=(",", ":")).encode("utf-8")) > MAX_INPUT_BYTES:
        raise BadRequest(413, "INPUT_TOO_LARGE", f"task input exceeds {MAX_INPUT_BYTES} bytes")
    return source, digest, tasks, task_id


def run_evaluation(settings: RunnerSettings, payload: Any, clock: Callable[[], float] | None = None) -> dict[str, Any]:
    """Validate + interpret; returns the response document (never raises for candidate faults)."""
    source, digest, tasks, task_id = _validate_request(payload)
    base: dict[str, Any] = {"runner_version": RUNNER_VERSION, "grammar_version": GRAMMAR_VERSION,
                            "source_sha256": digest, "result": None, "error": None, "ops": 0, "elapsed_ms": 0,
                            "limits": {"max_ops": settings.limits.max_ops, "max_seconds": settings.limits.max_seconds,
                                       "max_source_bytes": MAX_SOURCE_BYTES, "max_ast_nodes": MAX_AST_NODES,
                                       "max_ast_depth": MAX_AST_DEPTH, "max_tasks": MAX_TASKS,
                                       "max_input_bytes": MAX_INPUT_BYTES}}
    try:
        program = validate_source(source)
    except ValidationRejected as rej:
        return {**base, "status": "rejected", "error": rej.as_dict()}
    try:
        kwargs = {"clock": clock} if clock is not None else {}
        outcome = evaluate(program, tasks, task_id, settings.limits, **kwargs)
    except CandidateError as err:
        return {**base, "status": "error", "error": err.as_dict(), "ast_nodes": program.node_count}
    return {**base, "status": "ok", "result": outcome.result, "ops": outcome.ops, "elapsed_ms": outcome.elapsed_ms,
            "ast_nodes": program.node_count}


# ------------------------------------------------------------------ ASGI app
class _BodyLimit:
    def __init__(self, app: Any, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers", [])).get(b"content-length")
        try:
            too_big = declared is not None and int(declared) > self.limit
        except ValueError:
            too_big = True
        body = b""
        more = not too_big
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > self.limit:
                too_big = True
                break
        if too_big:
            resp = JSONResponse(status_code=413, content={"error": {"code": "REQUEST_TOO_LARGE",
                                                                    "message": "request body exceeds the size limit"}})
            await resp(scope, receive, send)
            return
        sent = False

        async def replay() -> dict:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: RunnerSettings | None = None) -> FastAPI:
    settings = settings or load_runner_settings()
    if not settings.allow_root and hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RunnerConfigError("the runner must not run as root")
    expected = settings.token_digest
    app = FastAPI(title="TaskSprint runner", version=RUNNER_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(_BodyLimit, limit=MAX_BODY_BYTES)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, err: Exception) -> JSONResponse:
        log.exception("runner internal error")
        return _err(500, "RUNNER_INTERNAL_ERROR", "internal error")

    @app.exception_handler(404)
    async def _not_found(request: Request, err: Exception) -> JSONResponse:
        return _err(404, "NOT_FOUND", "not found")

    @app.exception_handler(405)
    async def _not_allowed(request: Request, err: Exception) -> JSONResponse:
        return _err(405, "METHOD_NOT_ALLOWED", "method not allowed")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "service": "tasksprint-runner"}

    # The body is decoded here (not by FastAPI models) so the runner controls JSON limits.
    async def evaluate_endpoint(request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        presented = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
        digest = hashlib.sha256(presented.encode("utf-8")).digest()
        if not presented or not hmac.compare_digest(digest, expected):
            return _err(401, "RUNNER_UNAUTHENTICATED", "a valid runner transport token is required")
        raw = await request.body()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return _err(422, "INVALID_JSON", "body must be a JSON object")
        try:
            doc = await _in_thread(run_evaluation, settings, payload)
        except BadRequest as bad:
            return _err(bad.status, bad.code, bad.message)
        return JSONResponse(status_code=200, content=doc)

    app.add_api_route("/v1/evaluate", evaluate_endpoint, methods=["POST"], include_in_schema=False)
    app.state.settings = settings
    return app


async def _in_thread(fn: Callable, *args: Any) -> Any:
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(fn, *args)
