"""Release readiness and canonical plans (A8, A10, A11; Phase 08). Nothing here executes a release."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import pytest
from jsonschema import Draft202012Validator

from services.lab import clock, release_plans
from services.lab.config import REPO_ROOT
from tests.conftest import headers, qualify

PLAN_SCHEMA = json.loads((REPO_ROOT / "contracts" / "release-plan.schema.json").read_text())


def readiness(lab, candidate_id=None, role="operations"):
    params = {"candidate_id": candidate_id} if candidate_id else None
    return lab.client.get("/v1/readiness", params=params, headers=headers(role))


def plan(lab, action, candidate_id, role="operations", **extra):
    return lab.client.post("/v1/release-plans", json={"action": action, "candidate_id": candidate_id, **extra},
                           headers=headers(role))


def gates(body):
    return {g["gate"]: g["status"] for g in body["gates"]}


@pytest.fixture
def tested(seeded):
    ref = seeded.load_fixture("reference_complete")
    report = seeded.run_tests(ref["candidate_id"]).json()
    assert report["outcome"] == "pass"
    return seeded, ref, report


@pytest.fixture
def qualified(monkeypatch):
    """TEST-ONLY stand-in for the Phase 10 agent-system manifest gate."""
    monkeypatch.setattr(release_plans, "qualified_agent_manifest", lambda conn, ws: {"manifest_id": "mf_test_only"})


def active(lab):
    return lab.client.get("/v1/releases", headers=headers("operations")).json()["active"]


def test_readiness_is_computed_from_evidence_and_blocks_without_agent_manifest(tested):
    lab, ref, report = tested
    body = readiness(lab).json()
    g = gates(body)
    assert body["candidate"]["candidate_id"] == ref["candidate_id"] and body["candidate"]["selected_by"] == \
        "latest_passing_report"
    assert g["application_tests"] == "PASS" and g["candidate"] == "PASS" and g["differs_from_active"] == "PASS"
    assert g["agent_system_manifest"] == "NOT_QUALIFIED"
    assert body["deploy"] == {"status": "BLOCKED", "blocking_gates": ["agent_system_manifest"]}
    assert body["release"]["release_revision"] == 0 and body["release"]["active_is_baseline"] is True
    assert body["rollback"]["available"] is False
    ev = lab.client.get("/v1/events", headers=headers("operations")).json()["events"][0]
    assert ev["event_id"] == body["readiness_event_id"] and ev["action"] == "release.readiness"
    assert ev["outcome"] == "blocked"


def test_readiness_without_passing_report_and_for_faulty_candidate(seeded):
    assert gates(readiness(seeded).json())["candidate"] == "MISSING"
    faulty = seeded.load_fixture("faulty_delete")
    assert seeded.run_tests(faulty["candidate_id"]).json()["outcome"] == "fail"
    body = readiness(seeded, faulty["candidate_id"]).json()
    assert gates(body)["application_tests"] == "FAIL" and body["candidate"]["selected_by"] == "requested"
    assert "application_tests" in body["deploy"]["blocking_gates"]


def test_deploy_plan_refused_while_not_ready_and_nothing_changes(tested):
    lab, _ref, _ = tested
    before = active(lab)
    faulty = lab.load_fixture("faulty_delete")
    assert lab.run_tests(faulty["candidate_id"]).json()["outcome"] == "fail"
    r = plan(lab, "deploy", faulty["candidate_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "RELEASE_NOT_READY"
    assert r.json()["error"]["details"]["blocking_gates"] == ["application_tests", "agent_system_manifest"]
    assert active(lab) == before
    with lab.store().read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM release_plans").fetchone()[0] == 0


def test_manifest_only_gap_refuses_the_deploy_plan_under_schema_1_2(tested):
    """Phase 10 (plan schema 1.2): no deploy plan without a qualified manifest; with one, the plan binds it."""
    lab, ref, report = tested
    before = active(lab)
    r = plan(lab, "deploy", ref["candidate_id"])
    assert r.status_code == 409 and r.json()["error"]["details"]["blocking_gates"] == ["agent_system_manifest"]
    rec = qualify(lab.client)
    r = plan(lab, "deploy", ref["candidate_id"])
    assert r.status_code == 201, r.text
    body = r.json()
    Draft202012Validator(PLAN_SCHEMA).validate(body["plan"])
    assert body["plan"]["agent_manifest_id"] == rec["manifest_id"] and body["plan"]["schema_version"] == "1.2"
    assert body["plan"]["app_test_run_id"] == report["test_run_id"]
    assert body["review_snapshot"]["agent_baseline_manifest"]["status"] == "BOUND"
    assert body["state"] == "AWAITING_APPROVAL" and body["decision"] is None and body["execution"] is None
    assert active(lab) == before
    bad = dict(body["plan"], agent_manifest_id=None)
    assert list(Draft202012Validator(PLAN_SCHEMA).iter_errors(bad))  # 1.2 deploy requires a manifest id


def test_deploy_plan_binds_evidence_hash_and_awaits_approval(tested, qualified):
    lab, ref, report = tested
    before = active(lab)
    r = plan(lab, "deploy", ref["candidate_id"])
    assert r.status_code == 201, r.text
    body = r.json()
    p = body["plan"]
    Draft202012Validator(PLAN_SCHEMA).validate(p)
    assert body["created"] is True and body["state"] == "AWAITING_APPROVAL" and body["state_revision"] == 2
    assert p["environment"] == "demo-production" and p["operation"] == "deploy"
    assert p["target_sha256"] == ref["sha256"] and p["current_sha256"] == before["sha256"]
    assert p["expected_release_revision"] == 0 and p["app_test_run_id"] == report["test_run_id"]
    assert p["agent_manifest_id"] == "mf_test_only" and p["plan_sha256"] == release_plans.plan_hash(p)
    assert active(lab) == before  # a plan is not a release
    ev = [e["action"] for e in lab.client.get("/v1/events", headers=headers("operations")).json()["events"][:2]]
    assert ev == ["release_plan.state", "release_plan.create"]


def test_identical_live_plan_is_deduplicated_and_expiry_is_computed(tested, qualified):
    lab, ref, _ = tested
    first = plan(lab, "deploy", ref["candidate_id"]).json()
    again = plan(lab, "deploy", ref["candidate_id"]).json()
    assert again["created"] is False and again["plan"]["plan_id"] == first["plan"]["plan_id"]
    clock.advance_for_tests(timedelta(minutes=16))
    read = lab.client.get(f"/v1/release-plans/{first['plan']['plan_id']}", headers=headers("operations")).json()
    assert read["state"] == "AWAITING_APPROVAL" and read["effective_state"] == "EXPIRED"
    third = plan(lab, "deploy", ref["candidate_id"]).json()
    assert third["created"] is True and third["plan"]["plan_id"] != first["plan"]["plan_id"]


def test_named_test_report_must_be_a_pass_for_the_exact_hash(tested, qualified):
    lab, ref, _ = tested
    faulty = lab.load_fixture("faulty_delete")
    bad = lab.run_tests(faulty["candidate_id"]).json()
    r = plan(lab, "deploy", ref["candidate_id"], app_test_run_id=bad["test_run_id"])
    assert r.status_code == 409 and r.json()["error"]["details"]["blocking_gates"] == ["application_tests"]


def test_plan_preview_is_readable_by_operations_and_human_approver_only(tested, qualified):
    lab, ref, report = tested
    pid = plan(lab, "deploy", ref["candidate_id"]).json()["plan"]["plan_id"]
    for role in ("operations", "human_approver"):
        r = lab.client.get(f"/v1/release-plans/{pid}", headers=headers(role))
        assert r.status_code == 200, role
        prev = r.json()["preview"]
        assert prev["application_test_evidence"]["test_run_id"] == report["test_run_id"]
        assert prev["agent_baseline_manifest"] == "mf_test_only" and "approval" in prev
    for role in ("developer", "qa", "coordinator", "application"):
        assert lab.client.get(f"/v1/release-plans/{pid}", headers=headers(role)).status_code == 403, role
    assert lab.client.get("/v1/release-plans/plan_" + "0" * 24, headers=headers("operations")).status_code == 404


def test_only_operations_may_compute_readiness_or_create_plans(tested):
    lab, ref, _ = tested
    for role in ("developer", "qa", "coordinator", "application", "human_approver", "instructor"):
        assert readiness(lab, role=role).status_code == 403, role
        assert plan(lab, "deploy", ref["candidate_id"], role=role).status_code == 403, role


def test_plan_requests_cannot_carry_authority_or_targets(tested):
    lab, ref, _ = tested
    for extra in ({"approved": True}, {"environment": "production"}, {"target_sha256": "a" * 64},
                  {"expected_release_revision": 7}, {"plan_id": "plan_" + "1" * 24}):
        assert plan(lab, "deploy", ref["candidate_id"], **extra).status_code == 422, extra


def test_rollback_plan_targets_the_recorded_baseline(tested):
    lab, ref, _ = tested
    starter = active(lab)
    r = plan(lab, "rollback", starter["candidate_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "TARGET_ALREADY_ACTIVE"
    body = readiness(lab).json()
    assert body["release"]["baseline_candidate_id"] == starter["candidate_id"]
    assert body["rollback"]["target_candidate_id"] is None  # nothing to roll back while v0 is active
    lab.activate(ref)  # TRUSTED TEST-ONLY pointer change
    body = readiness(lab).json()
    assert body["rollback"]["available"] is True
    # Phase 12: readiness names the recorded healthy baseline's candidate ID, so one Operations request can plan
    assert body["rollback"]["target_candidate_id"] == starter["candidate_id"] == body["release"]["baseline_candidate_id"]
    assert body["rollback"]["target_sha256"] == starter["sha256"]
    r = plan(lab, "rollback", ref["candidate_id"])
    assert r.json()["error"]["code"] == "TARGET_ALREADY_ACTIVE"
    faulty = lab.load_fixture("faulty_delete")
    assert plan(lab, "rollback", faulty["candidate_id"]).json()["error"]["code"] == "ROLLBACK_TARGET_NOT_BASELINE"
    r = plan(lab, "rollback", starter["candidate_id"])
    assert r.status_code == 201, r.text
    p = r.json()["plan"]
    Draft202012Validator(PLAN_SCHEMA).validate(p)
    seed_release = lab.client.get("/v1/releases", headers=headers("operations")).json()["history"][-1]
    assert p["baseline_evidence_id"] == seed_release["release_id"] and p["app_test_run_id"] is None


def test_plans_are_append_only(tested, qualified):
    lab, ref, _ = tested
    pid = plan(lab, "deploy", ref["candidate_id"]).json()["plan"]["plan_id"]
    with pytest.raises(sqlite3.DatabaseError):
        with lab.store().write() as conn:
            conn.execute("UPDATE release_plans SET plan_json = '{}' WHERE plan_id = ?", (pid,))
