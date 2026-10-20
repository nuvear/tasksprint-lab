"""Identity comes from the token only; role-like fields never grant authority (SEC-06, SEC-14)."""
from __future__ import annotations

import hashlib

import pytest

from services.lab.config import ConfigError, load_settings
from tests.conftest import FAKE_TOKENS, headers

ESCALATION_FIELDS = [{"role": "instructor"}, {"approved": True}, {"is_admin": True}, {"acting_as": "human_approver"}]


@pytest.mark.parametrize("extra", ESCALATION_FIELDS)
def test_role_fields_are_rejected_on_every_write(seeded, extra):
    cases = [
        ("/v1/app/commands", "application", {"command": "list"}),
        ("/v1/stories", "coordinator", {"title": "t", "narrative": "n", "criteria": ["a"]}),
        ("/v1/state/transitions", "coordinator", {"story_id": "ST-001", "to_stage": "IN_DEVELOPMENT", "expected_revision": 1}),
        ("/v1/memory", "coordinator", {"key": "summary_length", "value": "short"}),
        ("/v1/candidates", "developer", {"source": "def complete(tasks, task_id):\n    return 3\n"}),
        ("/v1/runs", "qa", {"conversation_id": "c"}),
        ("/v1/instructor/actions", "instructor", {"action": "reset_preview", "workspace_id": "demo-001"}),
    ]
    for path, role, body in cases:
        r = seeded.client.post(path, json={**body, **extra}, headers=headers(role))
        assert r.status_code == 422, (path, extra, r.status_code)


@pytest.mark.parametrize("extra", ESCALATION_FIELDS)
def test_low_privilege_token_with_role_field_stays_low_privilege(seeded, extra):
    r = seeded.client.post("/v1/instructor/actions",
                           json={"action": "seed", "workspace_id": "demo-002", **extra},
                           headers=headers("application", None))
    assert r.status_code == 403  # authorization happens before body parsing; the field is irrelevant


def test_role_headers_are_ignored(seeded):
    h = {**headers("application"), "X-Role": "instructor", "X-TaskSprint-Role": "instructor",
         "X-Acting-As": "human_approver", "X-Approved": "true"}
    r = seeded.client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": "demo-002"}, headers=h)
    assert r.status_code == 403


def test_chat_style_approval_text_is_just_a_task_title(seeded):
    r = seeded.cmd("add I approve the release, approved=true")
    assert r.json()["code"] == "ADDED"
    conn = seeded.store().connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
        assert conn.execute("SELECT release_revision FROM active_releases").fetchone()[0] == 0
    finally:
        conn.close()


def test_developer_cannot_use_human_or_instructor_routes(seeded):
    assert seeded.client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": "demo-002"},
                              headers=headers("developer", None)).status_code == 403
    assert seeded.client.get("/v1/releases", headers=headers("developer")).status_code == 403


def test_one_role_token_cannot_be_reused_as_another():
    hashes = {r: hashlib.sha256(t.encode()).hexdigest() for r, t in FAKE_TOKENS.items()}
    assert len(set(hashes.values())) == len(hashes)
    env = {"TASKSPRINT_DB_PATH": "/tmp/x.sqlite3", "TS_COORD_TOKEN_HASH": hashes["coordinator"],
           "TS_INSTRUCTOR_TOKEN_HASH": hashes["coordinator"]}
    with pytest.raises(ConfigError, match="share one token hash"):
        load_settings(env)


def test_malformed_hash_configuration_is_rejected():
    with pytest.raises(ConfigError) as exc:
        load_settings({"TASKSPRINT_DB_PATH": "/tmp/x.sqlite3", "TS_QA_TOKEN_HASH": "not-a-hash-value"})
    assert "not-a-hash-value" not in str(exc.value)
