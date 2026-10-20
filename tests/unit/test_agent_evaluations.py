"""Phase 10: independent agent-evaluation reports, the agent-system manifest and its deployment gate.

A5 agent_eval_reports, A8 POST /v1/agent-evaluations, A11 step 5, A12 evaluator separation.
Every report here is TEST-ONLY (built by ``tests.conftest.eval_report``); no agent runs in unit tests.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from services.lab import agent_evaluations, clock
from tests.conftest import TEST_SYSTEM, eval_report, headers, qualify

AGENT_ROLES = ("coordinator", "product_owner", "developer", "qa", "operations", "application")
READERS = ("evaluator", "operations", "human_approver", "instructor")


def post(lab, body, role="evaluator"):
    return lab.client.post("/v1/agent-evaluations", json=body, headers=headers(role))


def gate(lab, role="operations"):
    return lab.client.get("/v1/agent-system-manifests/qualified", headers=headers(role)).json()


def attest(lab, system, role="evaluator"):
    return lab.client.post("/v1/agent-system-manifests/attestations", json={"system": system}, headers=headers(role))


def readiness_gates(lab):
    body = lab.client.get("/v1/readiness", headers=headers("operations")).json()
    return body, {g["gate"]: g for g in body["gates"]}


@pytest.fixture
def tested(seeded):
    ref = seeded.load_fixture("reference_complete")
    assert seeded.run_tests(ref["candidate_id"]).json()["outcome"] == "pass"
    return seeded, ref


# ------------------------------------------------------------------ authority
def test_only_the_evaluator_writes_reports_and_attestations(seeded):
    for role in AGENT_ROLES + ("instructor", "human_approver"):
        assert post(seeded, eval_report(), role).status_code == 403, role
        assert attest(seeded, TEST_SYSTEM, role).status_code == 403, role
        assert seeded.client.get("/v1/evaluator/observations", params={"since": "2026-01-01T00:00:00Z"},
                                 headers=headers(role)).status_code == 403, role
    assert post(seeded, {**eval_report(), "qualified": True}).status_code == 422
    assert post(seeded, {**eval_report(), "verdict": "QUALIFIED"}).status_code == 422
    with seeded.store().read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_eval_reports").fetchone()[0] == 0


def test_report_and_gate_are_readable_by_operations_and_humans_not_agents(seeded):
    rec = qualify(seeded.client)
    for role in READERS:
        r = seeded.client.get(f"/v1/agent-evaluations/{rec['report_id']}", headers=headers(role))
        assert r.status_code == 200, role
        assert r.json()["report_sha256"] == rec["report_sha256"] and r.json()["integrity"]["report_sha256_verified"]
        assert gate(seeded, role)["status"] == "PASS"
    for role in ("coordinator", "product_owner", "developer", "qa", "application"):
        assert seeded.client.get(f"/v1/agent-evaluations/{rec['report_id']}", headers=headers(role)).status_code == 403
        assert seeded.client.get("/v1/agent-system-manifests/qualified", headers=headers(role)).status_code == 403


def test_no_mcp_tool_reaches_evaluation_routes():
    from services.lab.mcp import CATALOG
    routes = {t.route[1] for t in CATALOG if t.route}
    assert not {r for r in routes if "agent-evaluations" in r or "agent-system-manifests" in r or "evaluator" in r}


# ------------------------------------------------------------------ verdict computed by the server
def test_full_passing_run_qualifies_with_a_deterministic_manifest_id(seeded):
    rec = qualify(seeded.client)
    assert rec["manifest_id"] == "asm_" + rec["manifest_sha256"][:24]
    assert rec["lab_side_sha256"] == agent_evaluations.lab_side_sha256()
    assert rec["critical_failures"] == 0 and rec["failed_trials"] == 0
    assert all(s["denominator"] == 3 and s["passed"] == 3 for s in rec["case_summary"].values())
    again = qualify(seeded.client)
    assert again["manifest_id"] == rec["manifest_id"] and again["report_id"] != rec["report_id"]
    view = seeded.client.get(f"/v1/agent-evaluations/{rec['report_id']}", headers=headers("operations")).json()
    assert view["manifest"]["lab_side"]["lab_service_version"] == agent_evaluations.lab_side()["lab_service_version"]
    assert view["manifest"]["system"] == TEST_SYSTEM


@pytest.mark.parametrize("kwargs, reason", [
    ({"purpose": "partial"}, "purpose is 'partial'"),
    ({"repetitions": 2}, "repetitions 2 < 3"),
    ({"cases": ["AE-01", "AE-02"]}, "AE-03: 0 of 3 trials reported"),
    ({"fail": (("AE-05", 2),)}, "AE-05: 1 failed"),
])
def test_incomplete_or_failing_runs_do_not_qualify(seeded, kwargs, reason):
    r = post(seeded, eval_report(**kwargs))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["verdict"] == "NOT_QUALIFIED" and any(reason in x for x in body["verdict_reasons"]), body
    assert gate(seeded)["status"] == "NOT_QUALIFIED"


def test_failing_critical_check_counts_and_denominators_are_per_case(seeded):
    body = post(seeded, eval_report(fail=(("AE-04", 1), ("AE-04", 3)))).json()
    s = body["case_summary"]["AE-04"]
    assert (s["denominator"], s["passed"], s["failed"], s["critical_failures"]) == (3, 1, 2, 2)
    assert body["critical_failures"] == 2 and body["case_summary"]["AE-01"]["critical_failures"] == 0


def test_status_must_follow_from_checks_and_every_check_must_be_reported(seeded):
    b = eval_report()
    b["trials"][0]["checks"][0]["passed"] = False  # still says pass
    r = post(seeded, b)
    assert r.status_code == 422 and r.json()["error"]["code"] == "STATUS_MISMATCH"
    b = eval_report()
    b["trials"][0]["checks"][0]["passed"] = None
    b["trials"][0]["status"] = "fail"
    assert post(seeded, b).json()["verdict"] == "NOT_QUALIFIED"  # unevaluable = not passed
    b = eval_report()
    b["trials"][0]["checks"] = []
    assert post(seeded, b).json()["error"]["code"] == "CHECK_MISSING"
    b = eval_report()
    b["trials"][1] = {**b["trials"][1], "case_id": b["trials"][0]["case_id"],
                      "checks": b["trials"][0]["checks"]}
    assert post(seeded, b).json()["error"]["code"] == "DUPLICATE_TRIAL"


def test_evidence_ids_must_exist_in_this_workspace(seeded):
    b = eval_report(evidence={("AE-01", 1): ["evt_" + "0" * 24]})
    r = post(seeded, b)
    assert r.status_code == 422 and r.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"
    ev = seeded.client.get("/v1/events", params={"limit": 1}, headers=headers("evaluator")).json()["events"][0]
    assert post(seeded, eval_report(evidence={("AE-01", 1): [ev["event_id"]]})).status_code == 201


def test_run_ids_must_be_created_inside_the_trial_window(seeded):
    run = seeded.client.post("/v1/runs", json={"conversation_id": "old"}, headers=headers("coordinator")).json()
    clock.advance_for_tests(timedelta(minutes=5))
    b = eval_report()
    b["trials"][0]["run_ids"] = [run["run_id"]]
    r = post(seeded, b)
    assert r.status_code == 422 and r.json()["error"]["code"] == "RUN_OUTSIDE_TRIAL_WINDOW"


def test_server_slice_marks_protected_actions_inside_a_trial_window_critical(seeded):
    """The harness says every trial passed; the server sees an instructor action during the last trial."""
    r = seeded.client.post("/v1/instructor/actions", json={"action": "outage_enable", "workspace_id": "demo-001",
                                                           "tool": "get_app_health"}, headers=headers("instructor", None))
    assert r.status_code == 200
    body = post(seeded, eval_report(end_offset_s=0)).json()
    assert body["verdict"] == "NOT_QUALIFIED" and body["critical_failures"] >= 1
    rep = seeded.client.get(f"/v1/agent-evaluations/{body['report_id']}", headers=headers("evaluator")).json()
    hit = [t for t in rep["report"]["trials"] if t["server_slice"]]
    assert hit and hit[-1]["server_status"] == "fail" and hit[-1]["status"] == "pass"
    assert "PROTECTED_ACTION_IN_TRIAL" in {x["code"] for x in hit[-1]["server_slice"]}


def test_reports_are_immutable(seeded):
    rec = qualify(seeded.client)
    with seeded.store().write() as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE agent_eval_reports SET verdict = 'QUALIFIED' WHERE report_id = ?", (rec["report_id"],))
    with seeded.store().write() as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM agent_eval_reports")


def test_tampered_report_fails_the_gate(seeded):
    rec = qualify(seeded.client)
    with seeded.store().write() as conn:  # TEST-ONLY: bypass the append-only trigger to simulate tampering
        conn.execute("DROP TRIGGER agent_eval_reports_no_update")
        conn.execute("UPDATE agent_eval_reports SET report_json = replace(report_json, 'test-only', 'tampered')"
                     " WHERE report_id = ?", (rec["report_id"],))
    assert gate(seeded)["status"] == "FAIL"
    assert seeded.client.get(f"/v1/agent-evaluations/{rec['report_id']}",
                             headers=headers("operations")).status_code == 500


# ------------------------------------------------------------------ the deployment gate
def test_readiness_is_ready_only_with_a_qualified_matching_manifest_and_plans_bind_it(tested):
    lab, ref = tested
    body, g = readiness_gates(lab)
    assert g["agent_system_manifest"]["status"] == "NOT_QUALIFIED" and body["deploy"]["status"] == "BLOCKED"
    r = lab.client.post("/v1/release-plans", json={"action": "deploy", "candidate_id": ref["candidate_id"]},
                        headers=headers("operations"))
    assert r.status_code == 409 and r.json()["error"]["details"]["blocking_gates"] == ["agent_system_manifest"]
    rec = qualify(lab.client)
    body, g = readiness_gates(lab)
    assert body["deploy"] == {"status": "READY", "blocking_gates": []}
    assert g["agent_system_manifest"]["agent_manifest_id"] == rec["manifest_id"]
    p = lab.client.post("/v1/release-plans", json={"action": "deploy", "candidate_id": ref["candidate_id"]},
                        headers=headers("operations")).json()
    assert p["plan"]["schema_version"] == "1.2" and p["plan"]["agent_manifest_id"] == rec["manifest_id"]
    assert p["review_snapshot"]["agent_baseline_manifest"]["status"] == "BOUND"


def test_a_lab_side_change_makes_the_baseline_stale(tested, monkeypatch):
    lab, _ = tested
    qualify(lab.client)
    changed = {**agent_evaluations.lab_side(), "release_policy_version": "changed"}
    monkeypatch.setattr(agent_evaluations, "lab_side", lambda: changed)
    body, g = readiness_gates(lab)
    assert g["agent_system_manifest"]["status"] == "STALE" and body["deploy"]["status"] == "BLOCKED"
    assert "release_policy_version" in g["agent_system_manifest"]["changed"]


def test_attestation_mismatch_invalidates_and_a_matching_one_restores(tested):
    lab, _ = tested
    rec = qualify(lab.client)
    changed = {**TEST_SYSTEM, "models": {"agents": {"TS-10": {"model_name": "another-model"}}}}
    a = attest(lab, changed).json()
    assert a["matches_qualified"] is False and "models.agents.TS-10.model_name" in a["differences"]
    assert a["gate"]["status"] == "INVALIDATED"
    assert readiness_gates(lab)[0]["deploy"]["status"] == "BLOCKED"
    b = attest(lab, TEST_SYSTEM).json()
    assert b["matches_qualified"] is True and b["gate"]["status"] == "PASS"
    assert b["gate"]["agent_manifest_id"] == rec["manifest_id"] and b["gate"]["last_verified_by"] == b["attestation_id"]


def test_verification_expires_and_reattestation_renews(tested):
    lab, _ = tested
    qualify(lab.client)
    clock.advance_for_tests(timedelta(hours=25))
    assert gate(lab)["status"] == "ATTESTATION_EXPIRED"
    assert attest(lab, TEST_SYSTEM).json()["gate"]["status"] == "PASS"


def test_a_later_failing_evaluation_of_the_same_manifest_invalidates(tested):
    lab, _ = tested
    qualify(lab.client)
    bad = post(lab, eval_report(purpose="partial", cases=["AE-04"], repetitions=1, fail=(("AE-04", 1),))).json()
    g = gate(lab)
    assert g["status"] == "INVALIDATED" and g["invalidated_by"] == bad["report_id"]
    other = post(lab, eval_report(purpose="partial", cases=["AE-04"], repetitions=1,
                                  system={**TEST_SYSTEM, "langflow": {"version": "other"}},
                                  fail=(("AE-04", 1),))).json()
    assert other["manifest_id"] != bad["manifest_id"]


def test_execution_rechecks_the_gate_after_approval(tested):
    """A11 step 5: the manifest bound by the plan must still be the qualified, matching one at execution."""
    lab, ref = tested
    qualify(lab.client)
    p = lab.client.post("/v1/release-plans", json={"action": "deploy", "candidate_id": ref["candidate_id"]},
                        headers=headers("operations")).json()
    view = lab.client.get(f"/v1/release-plans/{p['plan']['plan_id']}", headers=headers("human_approver")).json()
    a = lab.client.post("/v1/approvals", json={"plan_id": p["plan"]["plan_id"], "plan_sha256": p["plan"]["plan_sha256"],
                                               "snapshot_sha256": view["snapshot_sha256"], "decision": "approve"},
                        headers=headers("human_approver"))
    assert a.status_code == 201
    attest(lab, {**TEST_SYSTEM, "flows": {"TS-10": {"flow_id": "x", "export_sha256": "f" * 64}}})
    r = lab.client.post("/v1/release-executions", json={"plan_id": p["plan"]["plan_id"]}, headers=headers("operations"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "AGENT_MANIFEST_NOT_QUALIFIED"
    assert lab.client.get("/v1/releases", headers=headers("operations")).json()["active"]["release_revision"] == 0
    attest(lab, TEST_SYSTEM)
    r = lab.client.post("/v1/release-executions", json={"plan_id": p["plan"]["plan_id"]}, headers=headers("operations"))
    assert r.status_code == 201, r.text


def test_incomplete_system_manifest_is_refused(seeded):
    for system in ({**TEST_SYSTEM, "flows": {}}, {k: v for k, v in TEST_SYSTEM.items() if k != "harness"},
                   {**TEST_SYSTEM, "harness": {**TEST_SYSTEM["harness"], "case_set_version": "other/9"}}):
        assert post(seeded, eval_report(system=system)).status_code == 422
        assert attest(seeded, system).status_code == 422


# ------------------------------------------------------------------ evaluator observations, outages, body limit
def test_observations_return_external_state_since_a_time(seeded):
    clock.advance_for_tests(timedelta(seconds=2))
    since = clock.utc_now_iso()
    seeded.client.post("/v1/memory", json={"key": "release_notes_style", "value": "concise"},
                       headers=headers("coordinator"))
    obs = seeded.client.get("/v1/evaluator/observations", params={"since": since}, headers=headers("evaluator")).json()
    assert [e["action"] for e in obs["events"]] == ["memory.save"]
    assert obs["memories"][0]["pref_value"] == "concise" and obs["counts"]["memories"] == 1
    bad = seeded.client.get("/v1/evaluator/observations", params={"since": "yesterday"}, headers=headers("evaluator"))
    assert bad.status_code == 422


def test_tool_outage_is_instructor_only_controlled_and_cleared_by_reset(seeded):
    ref = seeded.load_fixture("reference_complete")
    for role in AGENT_ROLES + ("evaluator", "human_approver"):
        r = seeded.client.post("/v1/instructor/actions", json={"action": "outage_enable", "workspace_id": "demo-001",
                                                               "tool": "run_candidate_tests"}, headers=headers(role, None))
        assert r.status_code == 403, role
    r = seeded.client.post("/v1/instructor/actions", json={"action": "outage_enable", "workspace_id": "demo-001",
                                                           "tool": "run_candidate_tests", "ttl_minutes": 3},
                           headers=headers("instructor", None))
    assert r.status_code == 200 and r.json()["created"] is True
    t = seeded.run_tests(ref["candidate_id"])
    assert t.status_code == 503 and t.json()["error"]["code"] == "TOOL_UNAVAILABLE"
    with seeded.store().read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM test_runs").fetchone()[0] == 0
    assert seeded.client.get("/v1/app-health", headers=headers("operations")).status_code == 200
    assert seeded.client.get("/healthz").status_code == 200
    seeded.client.post("/v1/instructor/actions", json={"action": "reset_confirm", "workspace_id": "demo-001",
                                                       "confirm": "demo-001"}, headers=headers("instructor", None))
    assert seeded.run_tests(ref["candidate_id"]).status_code == 201
    r = seeded.client.post("/v1/instructor/actions", json={"action": "outage_enable", "workspace_id": "demo-001",
                                                           "tool": "get_app_health", "fixture": "faulty_delete"},
                           headers=headers("instructor", None))
    assert r.status_code == 422


def test_outage_expires_by_itself(seeded):
    seeded.client.post("/v1/instructor/actions", json={"action": "outage_enable", "workspace_id": "demo-001",
                                                       "tool": "get_app_health", "ttl_minutes": 1},
                       headers=headers("instructor", None))
    assert seeded.client.get("/v1/app-health", headers=headers("operations")).status_code == 503
    clock.advance_for_tests(timedelta(minutes=1, seconds=1))
    assert seeded.client.get("/v1/app-health", headers=headers("operations")).status_code == 200


def test_only_the_evaluator_route_accepts_a_larger_body(seeded):
    big = {"title": "x", "narrative": "y" * 70_000, "criteria": ["z"]}
    assert seeded.client.post("/v1/stories", json=big, headers=headers("coordinator")).status_code == 413
    padded = {**eval_report(), "telemetry_notes": "n" * 70_000}
    assert post(seeded, padded).status_code == 422  # schema limit, not the 64 KiB transport limit
    assert post(seeded, {**eval_report(), "telemetry_notes": "n" * 300_000}).status_code == 413


# ------------------------------------------------------------------ expired-run sweep (cosmetic fix)
def test_runs_past_deadline_are_marked_expired_on_the_next_write_and_still_refused(seeded):
    old = seeded.client.post("/v1/runs", json={"conversation_id": "old"}, headers=headers("coordinator")).json()
    clock.advance_for_tests(timedelta(seconds=181))
    prev = seeded.client.post("/v1/instructor/actions", json={"action": "reset_preview", "workspace_id": "demo-001"},
                              headers=headers("instructor", None)).json()
    assert old["run_id"] in prev["pending"]["past_deadline_runs"] and old["run_id"] not in prev["pending"]["active_runs"]
    seeded.client.post("/v1/runs", json={"conversation_id": "new"}, headers=headers("coordinator"))
    with seeded.store().read() as conn:
        assert conn.execute("SELECT status FROM runs WHERE run_id = ?", (old["run_id"],)).fetchone()[0] == "expired"
    r = seeded.client.post("/v1/memory", json={"key": "release_notes_style", "value": "concise"},
                           headers=headers("coordinator", run=old["run_id"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_EXPIRED"
