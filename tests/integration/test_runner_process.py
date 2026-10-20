"""Runner as a SEPARATE local process next to the lab (Build Guide 03.4/03.5; Gate 03).

Docker is not installed on the owner VM, so Compose cannot run there. This test
proves the same separation with two real OS processes: the runner gets a
minimal environment (PATH, locale, its transport token) on its own port, with
no lab DB path, env file or role tokens; the lab reaches it over HTTP.
Credentials are fresh, created by scripts/local_init.py in a temporary
directory; no value is printed.
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


def wait_healthy(proc: subprocess.Popen, url: str) -> None:
    deadline = time.monotonic() + 20
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


def runner_cmd(port: int) -> list[str]:
    return [sys.executable, "-m", "uvicorn", "--factory", "services.runner.main:create_app", "--host", "127.0.0.1",
            "--port", str(port), "--workers", "1", "--log-level", "warning"]


def minimal_runner_env(token: str) -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TS_RUNNER_TOKEN": token,
            "PYTHONDONTWRITEBYTECODE": "1"}


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("stack")
    target = tmp / ".local"
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "local_init.py"), "--dir", str(target)],
                          capture_output=True, timeout=30).returncode == 0
    tokens = parse_env_file(target / "role_tokens.env")
    runner_token = parse_env_file(target / "runner.env")["TS_RUNNER_TOKEN"]
    rport, lport = free_port(), free_port()
    runner = subprocess.Popen(runner_cmd(rport), cwd=REPO, env=minimal_runner_env(runner_token),
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    wait_healthy(runner, f"http://127.0.0.1:{rport}/healthz")
    lab_env = {**os.environ, "TASKSPRINT_ENV_FILE": str(target / "lab.env"),
               "TASKSPRINT_RUNNER_URL": f"http://127.0.0.1:{rport}"}
    lab = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory", "services.lab.main:create_app",
                            "--host", "127.0.0.1", "--port", str(lport), "--workers", "1", "--log-level", "warning"],
                           cwd=REPO, env=lab_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        wait_healthy(lab, f"http://127.0.0.1:{lport}/healthz")
    except RuntimeError:
        runner.kill()
        raise
    info = {"tokens": tokens, "runner_token": runner_token, "runner": runner, "lab": lab,
            "runner_url": f"http://127.0.0.1:{rport}", "lab_url": f"http://127.0.0.1:{lport}",
            "db_path": parse_env_file(target / "lab.env")["TASKSPRINT_DB_PATH"], "target": target}
    yield info
    for proc in (lab, runner):
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)


def h(stack, var: str, workspace: str | None = "demo-001") -> dict[str, str]:
    out = {"Authorization": f"Bearer {stack['tokens'][var]}"}
    if workspace:
        out["X-TaskSprint-Workspace"] = workspace
    return out


def post(stack, path: str, var: str, body: dict, workspace: str | None = "demo-001") -> httpx.Response:
    return httpx.post(stack["lab_url"] + path, json=body, headers=h(stack, var, workspace), timeout=10)


def test_two_separate_processes_are_healthy(stack):
    assert stack["runner"].pid != stack["lab"].pid
    assert httpx.get(stack["runner_url"] + "/healthz").json() == {"status": "ok", "service": "tasksprint-runner"}
    assert httpx.get(stack["lab_url"] + "/healthz").json() == {"status": "ok", "service": "tasksprint-lab"}


def test_runner_rejects_requests_without_transport_token(stack):
    body = {"source": "x", "source_sha256": "0" * 64, "tasks": [], "task_id": "T001"}
    assert httpx.post(stack["runner_url"] + "/v1/evaluate", json=body).status_code == 401
    assert httpx.post(stack["runner_url"] + "/v1/evaluate", json=body,
                      headers={"Authorization": f"Bearer {stack['tokens']['TS_APP_TOKEN']}"}).status_code == 401


@pytest.mark.skipif(not Path("/proc/self/environ").exists(), reason="needs /proc (Linux)")
def test_runner_process_has_no_db_path_role_tokens_or_db_files(stack):
    pid = stack["runner"].pid
    raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    names = {item.split(b"=", 1)[0].decode() for item in raw if item}
    assert "TS_RUNNER_TOKEN" in names
    assert not {n for n in names if n.startswith("TASKSPRINT_")}, names
    assert not {n for n in names if n.startswith("TS_") and n != "TS_RUNNER_TOKEN"}, names
    values = b"\0".join(raw)
    for role_token in stack["tokens"].values():
        assert role_token.encode() not in values
    assert stack["db_path"].encode() not in values
    open_files = [os.readlink(f"/proc/{pid}/fd/{fd}") for fd in os.listdir(f"/proc/{pid}/fd")]
    assert not [f for f in open_files if "sqlite" in f or str(stack["target"]) in f], open_files


def test_runner_refuses_to_start_when_given_lab_secrets(stack):
    env = {**minimal_runner_env(stack["runner_token"]), "TASKSPRINT_DB_PATH": stack["db_path"]}
    proc = subprocess.run(runner_cmd(free_port()), cwd=REPO, env=env, capture_output=True, timeout=30)
    assert proc.returncode != 0 and b"TASKSPRINT_DB_PATH" in proc.stderr
    assert stack["db_path"].encode() not in proc.stderr and stack["runner_token"].encode() not in proc.stderr


def test_v0_complete_is_interpreted_by_the_separate_runner(stack):
    assert post(stack, "/v1/instructor/actions", "TS_INSTRUCTOR_TOKEN",
                {"action": "seed", "workspace_id": "demo-001"}, workspace=None).status_code == 200
    before = post(stack, "/v1/app/commands", "TS_APP_TOKEN", {"command": "list"}).json()["data"]["tasks"]
    body = post(stack, "/v1/app/commands", "TS_APP_TOKEN", {"command": "complete T001"}).json()
    assert body["code"] == "FEATURE_UNAVAILABLE"
    assert body["data"]["evaluation"]["evaluated_by"].startswith("tasksprint-runner/")
    assert body["data"]["evaluation"]["interpreted_sha256"] == body["data"]["artifact"]["sha256"]
    assert post(stack, "/v1/app/commands", "TS_APP_TOKEN", {"command": "list"}).json()["data"]["tasks"] == before


def test_qa_runs_write_reports_faulty_fails_reference_passes(stack):
    ids = {}
    for fixture in ("faulty_delete", "reference_complete"):
        r = post(stack, "/v1/instructor/actions", "TS_INSTRUCTOR_TOKEN",
                 {"action": "load_fixture", "workspace_id": "demo-001", "fixture": fixture}, workspace=None)
        assert r.status_code == 200
        ids[fixture] = r.json()["candidate"]["candidate_id"]
    bad = post(stack, "/v1/test-runs", "TS_QA_TOKEN", {"candidate_id": ids["faulty_delete"]})
    good = post(stack, "/v1/test-runs", "TS_QA_TOKEN", {"candidate_id": ids["reference_complete"]})
    assert bad.status_code == good.status_code == 201
    bad, good = bad.json(), good.json()
    assert bad["outcome"] == "fail" and good["outcome"] == "pass"
    tc02 = next(c for c in bad["cases"] if c["case_id"] == "TC-02")
    assert not tc02["passed"]
    assert good["runner_version"].startswith("tasksprint-runner/") and len(good["evidence"]["evidence_ids"]) >= 6
    read = httpx.get(f"{stack['lab_url']}/v1/test-runs/{good['test_run_id']}", headers=h(stack, "TS_OPS_TOKEN"))
    assert read.status_code == 200 and read.json()["report_sha256"] == good["report_sha256"]
    stack["ids"] = ids


def test_developer_cannot_read_reference_source_or_run_tests(stack):
    ref = stack["ids"]["reference_complete"]
    r = httpx.get(f"{stack['lab_url']}/v1/candidates/{ref}", headers=h(stack, "TS_DEV_TOKEN"))
    assert r.status_code == 403 and "def complete" not in r.text
    assert post(stack, "/v1/test-runs", "TS_DEV_TOKEN", {"candidate_id": ref}).status_code == 403


def test_no_candidate_overwrite(stack):
    src = "def complete(tasks, task_id):\n    return {'ok': False, 'code': 'NOT_YET', 'tasks': tasks}\n"
    first = post(stack, "/v1/candidates", "TS_DEV_TOKEN", {"source": src}).json()
    second = post(stack, "/v1/candidates", "TS_DEV_TOKEN", {"source": src}).json()
    assert first["created"] is True and second["created"] is False
    assert (first["candidate_id"], first["sha256"], first["created_at"]) == (second["candidate_id"], second["sha256"],
                                                                              second["created_at"])
    read = httpx.get(f"{stack['lab_url']}/v1/candidates/{first['candidate_id']}", headers=h(stack, "TS_QA_TOKEN")).json()
    assert read["source"] == src and read["provenance"]["sha256_verified"] is True


def test_runner_down_means_no_mutation_and_no_pass(stack):
    stack["runner"].terminate()
    stack["runner"].wait(timeout=10)
    before = post(stack, "/v1/app/commands", "TS_APP_TOKEN", {"command": "list"}).json()["data"]["tasks"]
    body = post(stack, "/v1/app/commands", "TS_APP_TOKEN", {"command": "complete T001"}).json()
    assert body["code"] == "RUNNER_UNAVAILABLE" and body["data"]["tasks_changed"] == 0
    assert post(stack, "/v1/app/commands", "TS_APP_TOKEN", {"command": "list"}).json()["data"]["tasks"] == before
    rep = post(stack, "/v1/test-runs", "TS_QA_TOKEN", {"candidate_id": stack["ids"]["reference_complete"]}).json()
    assert rep["outcome"] == "error" and rep["cases"] == []
