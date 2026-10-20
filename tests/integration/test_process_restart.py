"""APP-08 (restart part): stop and start a real uvicorn process on the same DB file.

Distinct from the close/reopen unit test. Uses fresh credentials from
scripts/local_init.py in a temporary directory; prints no values.
Run: uv run pytest -q -m integration tests/integration
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

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(env_file: Path, port: int) -> subprocess.Popen:
    env = {**os.environ, "TASKSPRINT_ENV_FILE": str(env_file)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory", "services.lab.main:create_app",
                             "--host", "127.0.0.1", "--port", str(port), "--workers", "1", "--log-level", "warning"],
                            cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("lab did not become healthy")


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    proc.wait(timeout=10)


def test_tasks_survive_a_real_process_restart(tmp_path):
    target = tmp_path / ".local"
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "local_init.py"), "--dir", str(target)],
                          capture_output=True, timeout=30).returncode == 0
    tokens = parse_env_file(target / "role_tokens.env")
    app_h = {"Authorization": f"Bearer {tokens['TS_APP_TOKEN']}", "X-TaskSprint-Workspace": "demo-001"}
    port = free_port()
    base = f"http://127.0.0.1:{port}"

    proc = start(target / "lab.env", port)
    pid1 = proc.pid
    try:
        r = httpx.post(f"{base}/v1/instructor/actions", json={"action": "seed", "workspace_id": "demo-001"},
                       headers={"Authorization": f"Bearer {tokens['TS_INSTRUCTOR_TOKEN']}"}, timeout=5)
        assert r.status_code == 200
        r = httpx.post(f"{base}/v1/app/commands", json={"command": "add Survive restart"}, headers=app_h, timeout=5)
        assert r.json()["data"]["task"]["id"] == "T003"
        before = httpx.post(f"{base}/v1/app/commands", json={"command": "list"}, headers=app_h, timeout=5).json()
    finally:
        stop(proc)

    proc = start(target / "lab.env", port)
    try:
        assert proc.pid != pid1
        after = httpx.post(f"{base}/v1/app/commands", json={"command": "list"}, headers=app_h, timeout=5).json()
        assert after["data"]["tasks"] == before["data"]["tasks"]
        status = httpx.post(f"{base}/v1/app/commands", json={"command": "status"}, headers=app_h, timeout=5).json()
        assert status["data"]["release_revision"] == 0 and status["data"]["status"] == "healthy"
    finally:
        stop(proc)
