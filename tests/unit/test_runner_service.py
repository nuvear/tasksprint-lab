"""Runner HTTP service: transport auth, request validation, limits and configuration (A2, A6)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.runner import RUNNER_VERSION
from services.runner import main as runner_main
from services.runner.main import RunnerConfigError, RunnerSettings, load_runner_settings, run_evaluation
from tests.conftest import FAKE_RUNNER_TOKEN, runner_app

REPO = Path(__file__).resolve().parents[2]
TASKS = [{"id": "T001", "title": "Draft workshop agenda", "completed": False}]
AUTH = {"Authorization": f"Bearer {FAKE_RUNNER_TOKEN}"}


def req(source: str, tasks=None, task_id="T001", digest=None):
    return {"source": source, "source_sha256": digest or hashlib.sha256(source.encode()).hexdigest(),
            "tasks": TASKS if tasks is None else tasks, "task_id": task_id}


@pytest.fixture
def client():
    return TestClient(runner_app())


def reference() -> str:
    return (REPO / "instructor" / "fixtures" / "reference_complete.py").read_text()


def test_healthz_is_minimal(client):
    assert client.get("/healthz").json() == {"status": "ok", "service": "tasksprint-runner"}
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_evaluate_returns_result_ops_version_and_echoes_hash(client):
    body = req(reference())
    r = client.post("/v1/evaluate", json=body, headers=AUTH)
    assert r.status_code == 200
    doc = r.json()
    assert doc["status"] == "ok" and doc["result"]["tasks"][0]["completed"] is True
    assert doc["runner_version"] == RUNNER_VERSION and doc["ops"] > 0
    assert doc["source_sha256"] == body["source_sha256"]
    assert doc["limits"]["max_ops"] == 5000 and doc["limits"]["max_seconds"] == 2.0


def test_rejected_source_is_a_200_with_status_rejected(client):
    doc = client.post("/v1/evaluate", json=req("def complete(tasks, task_id):\n    return len(tasks)\n"),
                      headers=AUTH).json()
    assert doc["status"] == "rejected" and doc["error"]["code"] == "FORBIDDEN_SYNTAX" and doc["result"] is None


@pytest.mark.parametrize("mutate,status,code", [
    (lambda b: b.update(source_sha256="0" * 64), 422, "SOURCE_HASH_MISMATCH"),
    (lambda b: b.update(extra=1), 422, "INVALID_REQUEST"),
    (lambda b: b.pop("task_id"), 422, "INVALID_REQUEST"),
    (lambda b: b.update(task_id="T001; drop"), 422, "INVALID_REQUEST"),
    (lambda b: b.update(tasks=[{"id": "T1", "title": "x", "completed": "yes"}]), 422, "INVALID_REQUEST"),
    (lambda b: b.update(tasks=[{"id": "T1", "title": "x" * 121, "completed": False}]), 422, "INVALID_REQUEST"),
    (lambda b: b.update(tasks=[{"id": "T1", "title": "x", "completed": False, "role": "admin"}]), 422, "INVALID_REQUEST"),
    (lambda b: b.update(tasks=[{"id": f"T{i}", "title": "x", "completed": False} for i in range(101)]), 413,
     "INPUT_TOO_LARGE"),
])
def test_request_validation(client, mutate, status, code):
    body = req(reference())
    mutate(body)
    r = client.post("/v1/evaluate", json=body, headers=AUTH)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_input_byte_limit_32_kib():
    tasks = [{"id": f"T{i:03d}", "title": "é" * 120, "completed": False} for i in range(100)]
    with pytest.raises(runner_main.BadRequest) as exc:
        run_evaluation(RunnerSettings(token=FAKE_RUNNER_TOKEN), req(reference(), tasks=tasks))
    assert exc.value.code == "INPUT_TOO_LARGE"


def test_body_limit_and_invalid_json(client):
    r = client.post("/v1/evaluate", content=b"{" + b" " * (49 * 1024) + b"}", headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 413
    r = client.post("/v1/evaluate", content=b"not json", headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_JSON"


def test_settings_hold_only_the_transport_token_and_limits():
    s = load_runner_settings({"TS_RUNNER_TOKEN": FAKE_RUNNER_TOKEN, "PATH": "/usr/bin"})
    assert s.describe()["fields"] == ["token", "limits", "allow_root"]
    assert FAKE_RUNNER_TOKEN not in repr(s)


@pytest.mark.parametrize("name", ["TASKSPRINT_DB_PATH", "TASKSPRINT_ENV_FILE", "TS_APP_TOKEN", "TS_QA_TOKEN_HASH",
                                  "TS_A2A_API_KEY", "LANGFLOW_SECRET_KEY", "OPENAI_API_KEY", "DATABASE_URL",
                                  "RAILWAY_TOKEN"])
def test_runner_refuses_to_start_with_lab_or_platform_secrets(name):
    with pytest.raises(RunnerConfigError) as exc:
        load_runner_settings({"TS_RUNNER_TOKEN": FAKE_RUNNER_TOKEN, name: "value-must-not-appear"})
    assert name in str(exc.value) and "value-must-not-appear" not in str(exc.value)
    assert FAKE_RUNNER_TOKEN not in str(exc.value)


def test_runner_requires_a_transport_token():
    with pytest.raises(RunnerConfigError):
        load_runner_settings({})
    with pytest.raises(RunnerConfigError):
        load_runner_settings({"TS_RUNNER_TOKEN": "short"})


def test_runner_refuses_to_run_as_root(monkeypatch):
    monkeypatch.setattr(runner_main.os, "geteuid", lambda: 0)
    with pytest.raises(RunnerConfigError):
        runner_main.create_app(RunnerSettings(token=FAKE_RUNNER_TOKEN))
