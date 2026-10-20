"""Real MCP protocol tests: the official SDK client over Streamable HTTP against
spawned lab processes (and a separate runner process). Nothing is mocked.

Credentials are fresh, created by scripts/local_init.py in a temporary
directory; no value is printed. Two stacks are started per session:

* ``stack``: runner + lab, demo-001 seeded, faulty fixture loaded.
* ``slow_stack``: a lab whose runner URL points at a local TCP "black hole"
  (accepts, never answers) with a 1 s MCP tool deadline, for timeout tests.
"""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from services.lab.config import parse_env_file

REPO = Path(__file__).resolve().parents[2]
ROLE_VARS = {"coordinator": "TS_COORD_TOKEN", "product_owner": "TS_PO_TOKEN", "developer": "TS_DEV_TOKEN",
             "qa": "TS_QA_TOKEN", "operations": "TS_OPS_TOKEN", "application": "TS_APP_TOKEN",
             "human_approver": "TS_APPROVER_TOKEN", "instructor": "TS_INSTRUCTOR_TOKEN",
             "evaluator": "TS_EVALUATOR_TOKEN"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(proc: subprocess.Popen, url: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early with {proc.returncode}")
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("process did not become healthy")


def uvicorn(app: str, port: int) -> list[str]:
    return [sys.executable, "-m", "uvicorn", "--factory", app, "--host", "127.0.0.1", "--port", str(port),
            "--workers", "1", "--log-level", "warning"]


class Stack:
    def __init__(self, url: str, tokens: dict[str, str]):
        self.url = url
        self._tokens = tokens

    def token(self, role: str) -> str:
        return self._tokens[ROLE_VARS[role]]

    def rest(self, method: str, path: str, role: str, body: dict | None = None, workspace: str | None = "demo-001"):
        h = {"Authorization": f"Bearer {self.token(role)}"}
        if workspace:
            h["X-TaskSprint-Workspace"] = workspace
        return httpx.request(method, self.url + path, json=body, headers=h, timeout=15)

    def mcp_headers(self, role: str | None, workspace: str | None = "demo-001", run: str | None = None) -> dict:
        h: dict[str, str] = {}
        if role:
            h["Authorization"] = f"Bearer {self.token(role)}"
        if workspace:
            h["X-TaskSprint-Workspace"] = workspace
        if run:
            h["X-TaskSprint-Run"] = run
        return h

    @contextlib.asynccontextmanager
    async def session(self, role: str, *, workspace: str = "demo-001", run: str | None = None,
                      read_timeout: float | None = None) -> AsyncIterator[tuple[ClientSession, Any, Any]]:
        async with create_mcp_http_client(headers=self.mcp_headers(role, workspace, run)) as http:
            async with streamable_http_client(self.url + "/mcp", http_client=http) as (read, write, get_sid):
                rt = timedelta(seconds=read_timeout) if read_timeout else None
                async with ClientSession(read, write, read_timeout_seconds=rt) as s:
                    init = await s.initialize()
                    yield s, init, get_sid


def _start_lab(tmp: Path, extra_env: dict[str, str]) -> tuple[subprocess.Popen, Stack, Path]:
    target = tmp / ".local"
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "local_init.py"), "--dir", str(target)],
                          capture_output=True, timeout=30).returncode == 0
    tokens = parse_env_file(target / "role_tokens.env")
    port = free_port()
    env = {**os.environ, "TASKSPRINT_ENV_FILE": str(target / "lab.env"), **extra_env}
    lab = subprocess.Popen(uvicorn("services.lab.main:create_app", port), cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_healthy(lab, f"http://127.0.0.1:{port}/healthz")
    stack = Stack(f"http://127.0.0.1:{port}", tokens)
    assert stack.rest("POST", "/v1/instructor/actions", "instructor",
                      {"action": "seed", "workspace_id": "demo-001"}, None).status_code == 200
    return lab, stack, target


def _stop(*procs: subprocess.Popen) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.fixture(scope="session")
def stack(tmp_path_factory) -> Stack:
    tmp = tmp_path_factory.mktemp("mcpstack")
    target = tmp / ".local"
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "local_init.py"), "--dir", str(target)],
                          capture_output=True, timeout=30).returncode == 0
    runner_token = parse_env_file(target / "runner.env")["TS_RUNNER_TOKEN"]
    rport = free_port()
    runner = subprocess.Popen(uvicorn("services.runner.main:create_app", rport), cwd=REPO,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
                                   "TS_RUNNER_TOKEN": runner_token, "PYTHONDONTWRITEBYTECODE": "1"},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_healthy(runner, f"http://127.0.0.1:{rport}/healthz")
    tokens = parse_env_file(target / "role_tokens.env")
    lport = free_port()
    env = {**os.environ, "TASKSPRINT_ENV_FILE": str(target / "lab.env"),
           "TASKSPRINT_RUNNER_URL": f"http://127.0.0.1:{rport}"}
    lab = subprocess.Popen(uvicorn("services.lab.main:create_app", lport), cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_healthy(lab, f"http://127.0.0.1:{lport}/healthz")
    except RuntimeError:
        _stop(runner)
        raise
    s = Stack(f"http://127.0.0.1:{lport}", tokens)
    assert s.rest("POST", "/v1/instructor/actions", "instructor",
                  {"action": "seed", "workspace_id": "demo-001"}, None).status_code == 200
    r = s.rest("POST", "/v1/instructor/actions", "instructor",
               {"action": "load_fixture", "workspace_id": "demo-001", "fixture": "faulty_delete"}, None)
    assert r.status_code == 200
    s.faulty = r.json()["candidate"]  # type: ignore[attr-defined]
    s.lab_pid = lab.pid  # type: ignore[attr-defined]
    s.tokens_file = target / "role_tokens.env"  # type: ignore[attr-defined]
    yield s
    _stop(lab, runner)


class BlackHole:
    """Accepts TCP connections and never answers (a hung dependency)."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.conns: list[socket.socket] = []
        self._t = threading.Thread(target=self._accept, daemon=True)
        self._t.start()

    def _accept(self) -> None:
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.conns.append(c)

    def close(self) -> None:
        for c in self.conns:
            c.close()
        self.sock.close()


@pytest.fixture(scope="session")
def slow_stack(tmp_path_factory) -> Stack:
    hole = BlackHole()
    tmp = tmp_path_factory.mktemp("slowstack")
    lab, s, _ = _start_lab(tmp, {"TASKSPRINT_RUNNER_URL": f"http://127.0.0.1:{hole.port}",
                                 "TASKSPRINT_MCP_TOOL_TIMEOUT_S": "1"})
    r = s.rest("POST", "/v1/instructor/actions", "instructor",
               {"action": "load_fixture", "workspace_id": "demo-001", "fixture": "faulty_delete"}, None)
    assert r.status_code == 200
    s.faulty = r.json()["candidate"]  # type: ignore[attr-defined]
    yield s
    _stop(lab)
    hole.close()
