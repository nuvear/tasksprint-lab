"""Server-issued run contexts with fixed budgets (A8 POST /v1/runs, A9; SEC-14 partial)."""
from __future__ import annotations

from datetime import timedelta

from services.lab import clock
from services.lab.config import RUN_MAX_ACTIONS
from tests.conftest import headers


def new_run(lab, role="coordinator", ws="demo-001", body=None, **fields):
    payload = {"conversation_id": "conv-1", **fields, **(body or {})}
    return lab.client.post("/v1/runs", json=payload, headers=headers(role, ws))


def test_run_identity_and_budgets_come_from_server(seeded):
    r = new_run(seeded)
    assert r.status_code == 201
    run = r.json()
    assert run["role"] == "coordinator" and run["workspace_id"] == "demo-001"
    assert run["session_namespace"] == "demo-001:coordinator:conv-1"
    assert run["max_actions"] == 8 and run["tree_max_actions"] == 24 and run["depth"] == 0


def test_client_cannot_choose_budget_role_or_run_id(seeded):
    for extra in ({"max_actions": 1000}, {"role": "instructor"}, {"run_id": "run_" + "0" * 32},
                  {"deadline_s": 99999}, {"workspace_id": "demo-002"}):
        assert new_run(seeded, body=extra).status_code == 422, extra


def test_budget_exhaustion_stops_the_run(seeded):
    run = new_run(seeded, role="application").json()["run_id"]
    for _ in range(RUN_MAX_ACTIONS):
        assert seeded.cmd("list", run=run).status_code == 200
    r = seeded.cmd("list", run=run)
    assert r.status_code == 429 and r.json()["error"]["code"] == "BUDGET_EXHAUSTED"


def test_run_is_bound_to_its_role_and_workspace(seeded):
    seeded.seed("demo-002")
    run = new_run(seeded, role="application").json()["run_id"]
    assert seeded.cmd("list", workspace="demo-002", run=run).json()["error"]["code"] == "RUN_NOT_BOUND"
    r = seeded.client.get("/v1/state", headers=headers("coordinator", run=run))
    assert r.json()["error"]["code"] == "RUN_NOT_BOUND"


def test_unknown_or_expired_runs_are_refused(seeded):
    assert seeded.cmd("list", run="run_" + "f" * 32).json()["error"]["code"] == "RUN_NOT_BOUND"
    run = new_run(seeded, role="application").json()["run_id"]
    clock.advance_for_tests(timedelta(seconds=91))
    assert seeded.cmd("list", run=run).json()["error"]["code"] == "RUN_EXPIRED"


def test_delegation_depth_is_limited(seeded):
    root = new_run(seeded).json()
    child = new_run(seeded, role="developer", parent_run_id=root["run_id"]).json()
    assert child["depth"] == 1 and child["root_run_id"] == root["run_id"]
    grandchild = new_run(seeded, role="qa", parent_run_id=child["run_id"]).json()
    assert grandchild["depth"] == 2
    r = new_run(seeded, role="operations", parent_run_id=grandchild["run_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "DELEGATION_DEPTH_EXCEEDED"


def test_human_only_roles_cannot_create_agent_runs(seeded):
    for role in ("human_approver", "instructor", "evaluator"):
        assert new_run(seeded, role=role).status_code == 403
