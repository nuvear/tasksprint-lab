"""Redacted events, request IDs, size limits, no echo of input, no code execution."""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from services.lab.audit import redact
from tests.conftest import FAKE_TOKENS, headers

REPO = Path(__file__).resolve().parents[2]


def test_redaction_of_keys_and_token_shaped_values():
    out = redact({"api_key": "x", "Authorization": "Bearer abc", "nested": {"password": "p"},
                  "note": f"leaked {FAKE_TOKENS['coordinator']} here", "msg": "Bearer sometoken123"})
    assert out["api_key"] == out["Authorization"] == out["nested"]["password"] == "[REDACTED]"
    assert FAKE_TOKENS["coordinator"] not in str(out) and "sometoken123" not in str(out)


def test_events_never_contain_tokens(seeded):
    seeded.cmd(f"add remember {FAKE_TOKENS['instructor'][:30]}")
    seeded.client.get("/v1/state", headers=headers("application"))  # denied -> event
    conn = seeded.store().connect()
    try:
        blob = " ".join(r[0] for r in conn.execute("SELECT details_json FROM events"))
    finally:
        conn.close()
    for token in FAKE_TOKENS.values():
        assert token not in blob


def test_request_ids_are_server_generated(seeded):
    r = seeded.client.get("/healthz", headers={"X-Request-ID": "client-chosen"})
    assert re.fullmatch(r"req_[0-9a-f]{24}", r.headers["x-request-id"])
    err = seeded.client.get("/v1/state").json()["error"]
    assert re.fullmatch(r"req_[0-9a-f]{24}", err["request_id"])


def test_oversized_body_is_rejected_before_handling(seeded):
    r = seeded.client.post("/v1/app/commands", content=b'{"command":"' + b"a" * 70_000 + b'"}',
                           headers={**headers("application"), "Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert len(seeded.cmd("list").json()["data"]["tasks"]) == 2


def test_validation_errors_do_not_echo_input(seeded):
    secretish = "ts_coordinator_" + "S" * 40
    r = seeded.client.post("/v1/app/commands", json={"command": "list", "token": secretish},
                           headers=headers("application"))
    assert r.status_code == 422 and secretish not in r.text


def test_service_code_contains_no_dynamic_execution():
    forbidden = re.compile(r"(?<![.\w])(exec|eval|compile|__import__)\s*\(|\bimportlib\b|\bpickle\b|\bsubprocess\b|os\.system|\bmarshal\b")
    hits = []
    for path in (REPO / "services").rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if forbidden.search(line) and not line.lstrip().startswith("#"):
                hits.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert hits == []


def run_init(target: Path):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "local_init.py"), "--dir", str(target)],
                          capture_output=True, text=True, timeout=30)


def test_local_init_writes_private_files_and_never_prints_values(tmp_path):
    target = tmp_path / ".local"
    first = run_init(target)
    assert first.returncode == 0, first.stderr
    tokens = (target / "role_tokens.env").read_text()
    lab_env = (target / "lab.env").read_text()
    values = [line.split("=", 1)[1] for line in (tokens + lab_env).splitlines() if "=" in line and not line.startswith("#")]
    secret_values = [v for v in values if len(v) >= 32]
    assert len(secret_values) >= 19  # 9 tokens + 9 hashes + runner token
    for v in secret_values:
        assert v not in first.stdout and v not in first.stderr
    for name in ("role_tokens.env", "lab.env"):
        assert stat.S_IMODE((target / name).stat().st_mode) == 0o600
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert "TS_A2A_API_KEY" not in tokens
    second = run_init(target)
    assert second.returncode == 3 and "REFUSED" in second.stderr
    assert (target / "role_tokens.env").read_text() == tokens  # unchanged


def test_local_init_tokens_authenticate_against_the_lab(tmp_path):
    from fastapi.testclient import TestClient

    from services.lab.config import load_settings, parse_env_file
    from services.lab.main import create_app
    target = tmp_path / ".local"
    assert run_init(target).returncode == 0
    settings = load_settings({"TASKSPRINT_ENV_FILE": str(target / "lab.env")})
    tokens = parse_env_file(target / "role_tokens.env")
    client = TestClient(create_app(settings))
    r = client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": "demo-001"},
                    headers={"Authorization": f"Bearer {tokens['TS_INSTRUCTOR_TOKEN']}"})
    assert r.status_code == 200
    r = client.post("/v1/app/commands", json={"command": "list"},
                    headers={"Authorization": f"Bearer {tokens['TS_APP_TOKEN']}", "X-TaskSprint-Workspace": "demo-001"})
    assert r.status_code == 200 and len(r.json()["data"]["tasks"]) == 2
    r = client.post("/v1/app/commands", json={"command": "list"},
                    headers={"Authorization": f"Bearer {tokens['TS_DEV_TOKEN']}", "X-TaskSprint-Workspace": "demo-001"})
    assert r.status_code == 403
    assert os.environ.get("TS_APP_TOKEN") is None
