"""Phase 05 rehearsal without Docker or Railway: the real container entrypoints as processes.

* runner: ``python -m services.runner.serve`` with only PORT, PATH, LANG and its token;
  binds dual-stack ``::`` and answers on 127.0.0.1 and ::1.
* lab: ``python -m services.lab.serve`` on $PORT, 0.0.0.0, Railway-like MCP host allowlist;
  migrations logged once; nothing seeded; logs carry no token values.
* scripts/seed_demo.py --lab-url and scripts/check_stack.py --target railway against it,
  including --snapshot save -> restart ("redeploy") -> --snapshot verify on the same DB.

Fresh credentials from scripts/local_init.py in a temporary directory; no value is printed.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from services.lab.config import parse_env_file
from services.runner.serve import ipv6_available

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration
PUBLIC_HOST = "tasksprint-lab-test.up.railway.app"
MCP_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
MCP_ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url: str, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"exited early with {proc.returncode}: {proc.stderr.read() if proc.stderr else ''}")
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("not healthy")


def stop(proc: subprocess.Popen) -> str:
    proc.terminate()
    try:
        _, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    return err or ""


@pytest.fixture()
def creds(tmp_path):
    target = tmp_path / "railway"
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "local_init.py"), "--dir", str(target),
                           "--db-path", str(tmp_path / "data" / "tasksprint.sqlite3")],
                          capture_output=True, timeout=30).returncode == 0
    return target


def start_runner(creds: Path, port: int) -> subprocess.Popen:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "PORT": str(port),
           "PYTHONDONTWRITEBYTECODE": "1", "TS_RUNNER_TOKEN": parse_env_file(creds / "runner.env")["TS_RUNNER_TOKEN"]}
    proc = subprocess.Popen([sys.executable, "-m", "services.runner.serve"], cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    wait(f"http://127.0.0.1:{port}/healthz", proc)
    return proc


def start_lab(creds: Path, port: int, runner_port: int) -> subprocess.Popen:
    # Railway-style: configuration arrives as process variables (here from the private file).
    env = {**os.environ, **parse_env_file(creds / "lab.env"), "PORT": str(port),
           "TASKSPRINT_RUNNER_URL": f"http://127.0.0.1:{runner_port}",
           "TASKSPRINT_MCP_ALLOWED_HOSTS": f"{PUBLIC_HOST},127.0.0.1:*"}
    env.pop("TASKSPRINT_ENV_FILE", None)
    proc = subprocess.Popen([sys.executable, "-m", "services.lab.serve"], cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    wait(f"http://127.0.0.1:{port}/healthz", proc)
    return proc


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True, timeout=120)


def test_runner_entrypoint_binds_dual_stack_port(creds):
    port = free_port()
    proc = start_runner(creds, port)
    try:
        assert httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2).json()["status"] == "ok"
        if ipv6_available():
            assert httpx.get(f"http://[::1]:{port}/healthz", timeout=2).status_code == 200
    finally:
        err = stop(proc)
    assert "runner start: bind=" in err and f"port={port}" in err


def test_lab_entrypoint_railway_mode_end_to_end(creds, tmp_path):
    tokens_file = creds / "role_tokens.env"
    tokens = parse_env_file(tokens_file)
    rport, lport = free_port(), free_port()
    runner = start_runner(creds, rport)
    logs: list[str] = []
    try:
        lab = start_lab(creds, lport, rport)
        base = f"http://127.0.0.1:{lport}"
        coord = {"Authorization": f"Bearer {tokens['TS_COORD_TOKEN']}", "X-TaskSprint-Workspace": "demo-001"}
        # Nothing seeded at start-up.
        assert httpx.get(base + "/v1/state", headers=coord, timeout=5).status_code == 404
        # MCP: the configured public host is accepted, others are not (DNS-rebinding guard).
        r = httpx.post(base + "/mcp", json=MCP_INIT, headers={**MCP_ACCEPT, **coord, "Host": PUBLIC_HOST}, timeout=10)
        assert r.status_code == 200 and r.headers.get("mcp-session-id")
        r = httpx.post(base + "/mcp", json=MCP_INIT, headers={**MCP_ACCEPT, **coord, "Host": "evil.example"}, timeout=10)
        assert r.status_code == 421
        # A token-shaped path must not reach the logs verbatim.
        assert httpx.get(base + "/" + tokens["TS_DEV_TOKEN"], timeout=5).status_code in (401, 404)

        seed = run_script("scripts/seed_demo.py", "--workspace", "demo-001", "--apply", "--lab-url", base,
                          "--tokens-file", str(tokens_file))
        assert seed.returncode == 0 and "HTTP 200" in seed.stdout, seed.stdout + seed.stderr

        check = ["scripts/check_stack.py", "--target", "railway", "--base-url", base, "--allow-http-loopback",
                 "--env-file", str(tokens_file)]
        saved = run_script(*check, "--snapshot", "save")
        assert saved.returncode == 0, saved.stdout + saved.stderr
        for line in ("PASS lab liveness without a token", "PASS business route without a token refused",
                     "PASS invalid token refused", "PASS /mcp without a token refused",
                     "PASS MCP initialize accepted for this host", "PASS authenticated state read",
                     "PASS application status", "PASS lab -> runner path", "PASS persistence snapshot saved"):
            assert line in saved.stdout, line
        snap = creds / "railway_snapshot.json"
        assert snap.is_file() and (snap.stat().st_mode & 0o077) == 0

        logs.append(stop(lab))  # "redeploy": same database file, new process
        lab = start_lab(creds, lport, rport)
        verified = run_script(*check, "--snapshot", "verify")
        assert verified.returncode == 0, verified.stdout + verified.stderr
        assert "PASS volume persistence after redeploy: saved newest event present" in verified.stdout
        logs.append(stop(lab))
        for out in (seed, saved, verified):
            for value in tokens.values():
                assert value not in out.stdout and value not in out.stderr
    finally:
        stop(runner)
    first, second = logs
    assert "lab start: bind=0.0.0.0:%d" % lport in first and "migrations_applied_now=[1, 2, 3, 4]" in first
    assert "migrations_applied_now=[]" in second and "schema_version=4" in second
    for value in tokens.values():
        assert value not in first and value not in second
    assert "[REDACTED]" in first


def test_check_stack_railway_requires_https(creds):
    out = run_script("scripts/check_stack.py", "--target", "railway", "--base-url", "http://lab.example.com",
                     "--env-file", str(creds / "role_tokens.env"))
    assert out.returncode == 2 and "https" in out.stderr
    out = run_script("scripts/seed_demo.py", "--workspace", "demo-001", "--apply", "--lab-url", "http://lab.example.com",
                     "--tokens-file", str(creds / "role_tokens.env"))
    assert out.returncode == 2
