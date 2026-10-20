"""SEC-01 and deny-by-default authorization on every business route."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.routing import APIRoute

from services.lab.auth import PERMISSIONS, PUBLIC_ROUTES
from services.lab.config import ROLES
from tests.conftest import INVALID_TOKEN, Lab, headers

SAMPLE_BODIES = {
    "/v1/runs": {"conversation_id": "c1"},
    "/v1/stories": {"title": "t", "narrative": "n", "criteria": ["a"]},
    "/v1/state/transitions": {"story_id": "ST-001", "to_stage": "IN_DEVELOPMENT", "expected_revision": 1},
    "/v1/memory": {"key": "summary_length", "value": "short"},
    "/v1/candidates": {"source": "def complete(tasks, task_id):\n    return 1\n"},
    "/v1/app/commands": {"command": "add Sneaky task"},
    "/v1/instructor/actions": {"action": "seed", "workspace_id": "demo-002"},
}


def business_routes(app):
    out = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                out.append((m, r.path))
    return [x for x in out if x not in PUBLIC_ROUTES]


def concrete(path):
    return path.replace("{candidate_id}", "cand_" + "0" * 24)


def snapshot(db):
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'events'")]
    snap = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables}
    conn.close()
    return snap


def call(lab, method, path, hdrs):
    body = SAMPLE_BODIES.get(path)
    return lab.client.request(method, concrete(path), json=body if method == "POST" else None, headers=hdrs)


def test_every_route_has_an_explicit_policy(seeded):
    routes = business_routes(seeded.app)
    assert routes, "no business routes discovered"
    missing = [r for r in routes if r not in PERMISSIONS]
    assert missing == [], f"routes without a policy: {missing}"
    assert set(PUBLIC_ROUTES) == {("GET", "/healthz")}


def test_missing_and_invalid_tokens_are_denied_without_state_change(seeded):
    before = snapshot(seeded.db_path)
    for method, path in business_routes(seeded.app):
        for hdrs in ({"X-TaskSprint-Workspace": "demo-001"},
                     {**headers(None), "Authorization": f"Bearer {INVALID_TOKEN}"},
                     {**headers(None), "Authorization": "Basic YWRtaW46YWRtaW4="},
                     {**headers(None), "Authorization": "Bearer "},
                     {**headers(None), "Authorization": f"bearer {INVALID_TOKEN}"}):
            r = call(seeded, method, path, hdrs)
            assert r.status_code == 401, (method, path, hdrs.get("Authorization"), r.status_code)
            assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert snapshot(seeded.db_path) == before


@pytest.mark.parametrize("role", sorted(ROLES))
def test_wrong_roles_are_denied_on_every_route(seeded, role):
    before = snapshot(seeded.db_path)
    for method, path in business_routes(seeded.app):
        if role in PERMISSIONS[(method, path)]:
            continue
        r = call(seeded, method, path, headers(role))
        assert r.status_code == 403, (role, method, path, r.status_code)
    assert snapshot(seeded.db_path) == before


def test_route_without_policy_is_denied_even_when_authenticated(db_path):
    lab = Lab(db_path)
    lab.seed()

    @lab.app.get("/v1/unlisted")
    def unlisted():  # pragma: no cover - must never run
        raise AssertionError("handler reached without a policy")

    for role in sorted(ROLES):
        assert lab.client.get("/v1/unlisted", headers=headers(role)).status_code == 403


def test_healthz_is_public_and_minimal(seeded):
    r = seeded.client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok", "service": "tasksprint-lab"}


def test_disabled_role_cannot_authenticate(db_path):
    lab = Lab(db_path, token_hashes={})  # no configured hashes at all
    assert lab.client.get("/v1/state", headers=headers("coordinator")).status_code == 401


def test_docs_and_openapi_are_not_exposed(seeded):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert seeded.client.get(path).status_code == 404
