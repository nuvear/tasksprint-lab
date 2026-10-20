"""Audited A2A exchange records (A9, A10; Phase 08). The lab derives IDs and links evidence itself."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from services.lab import clock
from services.lab.a2a_exchanges import contract_problems
from tests.conftest import headers

FLOW = "0f6c2f8e-1d1b-4c9b-9a51-3a3cbb7f0a11"
CARD = f"https://langflow.example.test/api/v1/a2a/{FLOW}/.well-known/agent-card.json"


def coord_run(lab):
    return lab.client.post("/v1/runs", json={"conversation_id": "c"}, headers=headers("coordinator")).json()


def payload(ref, **over):
    body = {"schema_version": "1.1", "intent": "assess_release", "workspace_id": "demo-001",
            "candidate_id": ref["candidate_id"], "candidate_sha256": ref["sha256"],
            "app_test_run_id": "tr_" + "a" * 24, "agent_manifest_id": None,
            "deadline_utc": "2026-10-20T15:00:00Z", "allow_execute": False}
    body.update(over)
    return body


def task(text, state="TASK_STATE_COMPLETED"):
    return {"id": "8a1c6f3e-7b2d-4c10-9e55-5d1a2b3c4d5e", "contextId": "ctx-1",
            "status": {"state": state},
            "artifacts": [{"artifactId": "art-1", "name": "result", "parts": [{"text": text}]}],
            "history": [{"messageId": "msg-1", "role": "ROLE_USER", "parts": [{"data": {"x": 1}}]}]}


def exchange(lab, run_id, req, role="coordinator", **over):
    body = {"parent_run_id": run_id, "peer_flow_id": FLOW, "card_url": CARD, "protocol_version": "0.3.0",
            "transport": "JSONRPC", "adapter_version": "a2a_audit/1.0.0", "request": req, "outcome": "completed",
            "task": task("BLOCKED"), "task_get": task("BLOCKED"), "http": [{"method": "message/send", "status": 200}],
            "error": None, "started_at": "2026-10-20T14:00:00Z", "finished_at": "2026-10-20T14:00:20Z"}
    body.update(over)
    return lab.client.post("/v1/a2a-exchanges", json=body, headers=headers(role))


def test_contract_accepts_null_manifest_and_rejects_execution_or_extra_fields(seeded):
    ref = seeded.load_fixture("reference_complete")
    assert contract_problems(payload(ref)) == []
    assert contract_problems(payload(ref, agent_manifest_id="mf_1")) == []
    assert contract_problems(payload(ref, allow_execute=True))
    assert contract_problems(payload(ref, approved=True))
    assert contract_problems(payload(ref, schema_version="1.0"))
    assert contract_problems(payload(ref, deadline_utc="tomorrow"))


def test_exchange_records_protocol_ids_lineage_trace_and_verified_references(seeded):
    ref = seeded.load_fixture("reference_complete")
    parent = coord_run(seeded)["run_id"]
    ops_run = seeded.client.post("/v1/runs", json={"conversation_id": "a2a", "parent_run_id": parent},
                                 headers=headers("operations")).json()
    assert ops_run["depth"] == 1 and ops_run["root_run_id"] == parent
    ready = seeded.client.get("/v1/readiness", headers=headers("operations", run=ops_run["run_id"])).json()
    text = (f"BLOCKED. readiness {ready['readiness_event_id']}; candidate {ref['candidate_id']}; "
            f"invented plan_{'9' * 24}. Bearer abcdefghijklmnop")
    r = exchange(seeded, parent, payload(ref), task=task(text), task_get=task(text))
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["protocol"] == {"task_id": "8a1c6f3e-7b2d-4c10-9e55-5d1a2b3c4d5e", "context_id": "ctx-1",
                               "state": "TASK_STATE_COMPLETED", "artifact_ids": ["art-1"], "message_ids": ["msg-1"]}
    assert rec["tasks_get_consistent"] is True and rec["parent_run_status_at_record"] == "active"
    linked = {x["id"]: x for x in rec["linked_evidence"]}
    assert linked[ready["readiness_event_id"]]["exists"] and linked[ready["readiness_event_id"]]["action"] == \
        "release.readiness"
    assert linked[ref["candidate_id"]]["exists"] and linked["plan_" + "9" * 24]["exists"] is False
    (peer,) = rec["peer_runs"]
    assert peer["run_id"] == ops_run["run_id"] and [t["action"] for t in peer["tool_trace"]] == ["run.create", "release.readiness"]
    stored = seeded.client.get(f"/v1/a2a-exchanges/{rec['exchange_id']}", headers=headers("instructor"))
    assert stored.status_code == 200
    raw = stored.json()["raw"]
    assert "abcdefghijklmnop" not in str(raw) and "[REDACTED]" in raw["task"]["artifacts"][0]["parts"][0]["text"]
    ev = seeded.client.get("/v1/events", headers=headers("coordinator")).json()["events"][0]
    assert ev["action"] == "a2a.exchange" and ev["details"]["exchange_id"] == rec["exchange_id"]


def test_failed_peer_is_recorded_without_a_task(seeded):
    ref = seeded.load_fixture("reference_complete")
    parent = coord_run(seeded)["run_id"]
    r = exchange(seeded, parent, payload(ref), outcome="unreachable", task=None, task_get=None,
                 error={"code": "PEER_UNAVAILABLE", "message": "card 404"})
    assert r.status_code == 201
    assert r.json()["protocol"]["task_id"] is None and r.json()["linked_evidence"] == []


def test_completed_outcome_requires_a_completed_task(seeded):
    ref = seeded.load_fixture("reference_complete")
    parent = coord_run(seeded)["run_id"]
    assert exchange(seeded, parent, payload(ref), task=None).json()["error"]["code"] == "EXCHANGE_INCONSISTENT"
    r = exchange(seeded, parent, payload(ref), task=task("x", "TASK_STATE_FAILED"))
    assert r.json()["error"]["code"] == "EXCHANGE_INCONSISTENT"


def test_contract_violations_and_foreign_runs_are_rejected(seeded):
    ref = seeded.load_fixture("reference_complete")
    parent = coord_run(seeded)["run_id"]
    r = exchange(seeded, parent, payload(ref, allow_execute=True))
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONTRACT_VIOLATION"
    other = seeded.client.post("/v1/runs", json={"conversation_id": "q"}, headers=headers("qa")).json()["run_id"]
    assert exchange(seeded, other, payload(ref)).json()["error"]["code"] == "RUN_NOT_BOUND"
    bad_card = exchange(seeded, parent, payload(ref), card_url="https://evil.example/x")
    assert bad_card.status_code == 422


def test_only_the_coordinator_records_exchanges(seeded):
    ref = seeded.load_fixture("reference_complete")
    parent = coord_run(seeded)["run_id"]
    for role in ("operations", "developer", "qa", "instructor", "human_approver"):
        assert exchange(seeded, parent, payload(ref), role=role).status_code == 403, role


def test_late_record_is_accepted_but_marked(seeded):
    ref = seeded.load_fixture("reference_complete")
    parent = coord_run(seeded)["run_id"]
    clock.advance_for_tests(timedelta(seconds=400))
    r = exchange(seeded, parent, payload(ref))
    assert r.status_code == 201 and r.json()["parent_run_status_at_record"] == "expired"


def test_exchanges_are_append_only(seeded):
    ref = seeded.load_fixture("reference_complete")
    parent = coord_run(seeded)["run_id"]
    xid = exchange(seeded, parent, payload(ref)).json()["exchange_id"]
    with pytest.raises(sqlite3.DatabaseError):
        with seeded.store().write() as conn:
            conn.execute("DELETE FROM a2a_exchanges WHERE exchange_id = ?", (xid,))
