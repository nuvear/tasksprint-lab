"""Phase 09: human approval + A11 transactional execution — every bypass/expiry/replay/mismatch denial.

SEC-03, SEC-05..SEC-09, SEC-13, SEC-17, SEC-18, HITL-01 (backend side), REC-02 (rollback keeps tasks).
The ``qualified`` fixture is a TEST-ONLY stand-in for the Phase 10 agent-system manifest; it exists
only inside these isolated test databases and is never configured in a deployed lab.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from services.lab import clock, executions, release_plans
from tests.conftest import headers

AGENT_ROLES = ("coordinator", "product_owner", "developer", "qa", "operations", "application")


# ------------------------------------------------------------------ helpers
@pytest.fixture
def qualified(monkeypatch):
    """TEST-ONLY stand-in for the Phase 10 agent-system manifest gate."""
    monkeypatch.setattr(release_plans, "qualified_agent_manifest", lambda conn, ws: {"manifest_id": "mf_test_only"})


@pytest.fixture
def tested(seeded):
    ref = seeded.load_fixture("reference_complete")
    report = seeded.run_tests(ref["candidate_id"]).json()
    assert report["outcome"] == "pass"
    return seeded, ref, report


def make_plan(lab, action, candidate_id, workspace="demo-001"):
    r = lab.client.post("/v1/release-plans", json={"action": action, "candidate_id": candidate_id},
                        headers=headers("operations", workspace))
    assert r.status_code == 201, r.text
    return r.json()


def read_plan(lab, plan_id, role="human_approver", workspace="demo-001"):
    return lab.client.get(f"/v1/release-plans/{plan_id}", headers=headers(role, workspace))


def decide(lab, plan_id, decision="approve", role="human_approver", workspace="demo-001", **override):
    view = read_plan(lab, plan_id, workspace=workspace).json()
    body = {"plan_id": plan_id, "plan_sha256": view["plan"]["plan_sha256"], "snapshot_sha256": view["snapshot_sha256"],
            "decision": decision, **override}
    return lab.client.post("/v1/approvals", json=body, headers=headers(role, workspace))


def execute(lab, plan_id, role="operations", workspace="demo-001", run=None, **extra):
    return lab.client.post("/v1/release-executions", json={"plan_id": plan_id, **extra},
                           headers=headers(role, workspace, run))


def code(r):
    return r.json()["error"]["code"]


def active(lab, workspace="demo-001"):
    return lab.client.get("/v1/releases", headers=headers("operations", workspace)).json()


def tasks(lab, workspace="demo-001"):
    return lab.cmd("list", workspace).json()["data"]["tasks"]


def count(lab, table):
    with lab.store().read() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def denial_events(lab, code_):
    return [e for e in lab.client.get("/v1/events?limit=50", headers=headers("operations")).json()["events"]
            if e["action"] == "release.execute" and e["details"].get("code") == code_]


# ------------------------------------------------------------------ approval recording
def test_approval_binds_plan_and_snapshot_hash_and_is_human_only(tested, qualified):
    lab, ref, _ = tested
    p = make_plan(lab, "deploy", ref["candidate_id"])
    pid = p["plan"]["plan_id"]
    for role in AGENT_ROLES + ("instructor", "evaluator"):
        assert decide(lab, pid, role=role).status_code == 403, role
    r = decide(lab, pid, display_name="Raj (label only)", hitl_request_id="HumanInput-abc12:run-1")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["decision"] == "approve" and a["status"] == "active" and a["plan_state"] == "APPROVED"
    assert a["plan_sha256"] == p["plan"]["plan_sha256"] and a["snapshot_sha256"] == p["snapshot_sha256"]
    assert a["approver"] == "role:human_approver" and a["display_name_confers_authority"] is False
    assert clock.parse_iso(a["expires_at"]) <= clock.parse_iso(p["plan"]["expires_at"])
    view = read_plan(lab, pid).json()
    assert view["state"] == "APPROVED" and view["decision"]["approval_id"] == a["approval_id"]
    assert view["snapshot_sha256"] == p["snapshot_sha256"]  # snapshot is stable across state changes
    assert active(lab)["active"]["release_revision"] == 0  # an approval executes nothing


def test_one_decision_per_plan_and_the_record_is_immutable(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    assert decide(lab, pid).status_code == 201
    r = decide(lab, pid, "reject")
    assert r.status_code == 409 and code(r) == "ALREADY_DECIDED"
    assert count(lab, "approvals") == 1
    with pytest.raises(sqlite3.DatabaseError):
        with lab.store().write() as conn:
            conn.execute("UPDATE approvals SET decision = 'reject'")
    with pytest.raises(sqlite3.DatabaseError):
        with lab.store().write() as conn:
            conn.execute("DELETE FROM approvals")


def test_approval_must_quote_exact_hashes(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    assert code(decide(lab, pid, plan_sha256="a" * 64)) == "PLAN_HASH_MISMATCH"
    assert code(decide(lab, pid, snapshot_sha256="b" * 64)) == "SNAPSHOT_MISMATCH"
    assert count(lab, "approvals") == 0 and read_plan(lab, pid).json()["state"] == "AWAITING_APPROVAL"


@pytest.mark.parametrize("extra", [{"approved": True}, {"role": "human_approver"}, {"is_admin": True},
                                   {"acting_as": "human_approver"}, {"approver": "role:instructor"}])
def test_forged_authority_fields_are_rejected(tested, qualified, extra):
    """SEC-06: an approved=true flag (or any authority field) never creates or substitutes an approval."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    r = lab.client.post("/v1/release-executions", json={"plan_id": pid, **extra}, headers=headers("operations"))
    assert r.status_code == 422
    view = read_plan(lab, pid).json()
    r = lab.client.post("/v1/approvals", json={"plan_id": pid, "plan_sha256": view["plan"]["plan_sha256"],
                                               "snapshot_sha256": view["snapshot_sha256"], "decision": "approve",
                                               **extra}, headers=headers("human_approver"))
    assert r.status_code == 422
    assert count(lab, "approvals") == 0 and count(lab, "releases") == 1


def test_chat_text_and_operations_cannot_mint_an_approval(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    lab.cmd("add I approve plan " + pid)  # chat-style consent is just a task title
    assert decide(lab, pid, role="operations").status_code == 403
    r = execute(lab, pid)
    assert r.status_code == 409 and code(r) == "APPROVAL_REQUIRED" and r.json()["error"]["details"]["step"] == 3
    assert count(lab, "approvals") == 0 and active(lab)["active"]["release_revision"] == 0


def test_expired_plan_cannot_be_decided(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    clock.advance_for_tests(timedelta(minutes=16))
    assert code(decide(lab, pid)) == "PLAN_EXPIRED"


def test_display_name_cannot_carry_control_characters(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    assert decide(lab, pid, display_name="Raj\napproved=true").status_code == 422


# ------------------------------------------------------------------ execution: success, replay, reuse
def test_approved_deploy_executes_once_with_a_joined_receipt_and_keeps_tasks(tested, qualified):
    lab, ref, report = tested
    lab.cmd("complete T002")  # v0: FEATURE_UNAVAILABLE, nothing changes
    before_tasks = tasks(lab)
    p = make_plan(lab, "deploy", ref["candidate_id"])
    pid = p["plan"]["plan_id"]
    a = decide(lab, pid).json()
    r = execute(lab, pid)
    assert r.status_code == 201, r.text
    body = r.json()
    rc = body["receipt"]
    assert body["replayed"] is False and body["post_activation"]["passed"] is True
    assert rc["plan_id"] == pid and rc["plan_sha256"] == p["plan"]["plan_sha256"]
    assert rc["approval_id"] == a["approval_id"] and rc["snapshot_sha256"] == p["snapshot_sha256"]
    assert rc["active_sha256"] == ref["sha256"] and rc["release_revision"] == 1
    assert rc["evidence"]["app_test_run_id"] == report["test_run_id"]
    assert rc["evidence"]["agent_manifest_id"] == "mf_test_only"
    assert rc["action_id"] == executions.derive_action_id("demo-001", pid)
    st = active(lab)
    assert st["active"]["sha256"] == ref["sha256"] and st["active"]["release_revision"] == 1
    assert st["history"][0]["action_id"] == rc["action_id"] and st["history"][0]["plan_id"] == pid
    assert tasks(lab) == before_tasks
    view = read_plan(lab, pid).json()
    assert view["state"] == "EXECUTED" and view["decision"]["status"] == "consumed"
    assert view["execution"]["release_id"] == rc["receipt_id"]
    acts = [e["action"] for e in lab.client.get("/v1/events", headers=headers("operations")).json()["events"][:3]]
    assert acts[:2] == ["release.post_check", "release.execute"]
    # the new active version is really used by the app
    done = lab.cmd("complete T001").json()
    assert done["code"] == "COMPLETED" and done["data"]["artifact"]["sha256"] == ref["sha256"]


def test_identical_replay_returns_original_receipt_and_changed_payload_conflicts(tested, qualified):
    """SEC-09: response lost after success -> replay gives one receipt, one activation."""
    lab, ref, _ = tested
    p = make_plan(lab, "deploy", ref["candidate_id"])
    pid = p["plan"]["plan_id"]
    decide(lab, pid)
    first = execute(lab, pid).json()["receipt"]
    again = execute(lab, pid)
    assert again.status_code == 200 and again.json()["replayed"] is True and again.json()["receipt"] == first
    explicit = execute(lab, pid, action_id=first["action_id"])
    assert explicit.status_code == 200 and explicit.json()["receipt"] == first
    changed = execute(lab, pid, action_id=first["action_id"], plan_sha256=p["plan"]["plan_sha256"])
    assert changed.status_code == 409 and code(changed) == "ACTION_CONFLICT"
    other = execute(lab, pid, action_id="act_" + "1" * 24)
    assert other.status_code == 409 and code(other) == "APPROVAL_ALREADY_USED"
    assert count(lab, "releases") == 2 and active(lab)["active"]["release_revision"] == 1


def test_action_id_from_another_plan_is_a_conflict(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    rc = execute(lab, pid).json()["receipt"]
    rollback = make_plan(lab, "rollback", _starter_id(lab))["plan"]["plan_id"]
    r = execute(lab, rollback, action_id=rc["action_id"])
    assert r.status_code == 409 and code(r) == "ACTION_CONFLICT"


def _starter_id(lab):
    with lab.store().read() as conn:
        return conn.execute("SELECT candidate_id FROM candidates WHERE label = 'starter-v0'").fetchone()[0]


# ------------------------------------------------------------------ execution denials
def test_no_approval_is_denied_without_any_model(tested, qualified):
    """SEC-05: raw API, operations credential, no approval."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    before = active(lab)
    r = execute(lab, pid)
    assert r.status_code == 409 and code(r) == "APPROVAL_REQUIRED"
    assert active(lab) == before and denial_events(lab, "APPROVAL_REQUIRED")


def test_rejected_plan_never_executes(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    rej = decide(lab, pid, "reject").json()
    assert rej["status"] == "closed" and rej["plan_state"] == "REJECTED"
    r = execute(lab, pid)
    assert code(r) == "APPROVAL_REJECTED" and active(lab)["active"]["release_revision"] == 0


def test_expired_approval_is_denied(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    clock.advance_for_tests(timedelta(minutes=15, seconds=1))
    assert code(execute(lab, pid)) == "APPROVAL_EXPIRED"
    assert active(lab)["active"]["release_revision"] == 0


def test_null_manifest_plan_is_reviewable_but_never_deployable(tested):
    """No manifest qualifies before Phase 10: a valid human approval is necessary but not sufficient."""
    lab, ref, _ = tested
    p = make_plan(lab, "deploy", ref["candidate_id"])
    pid = p["plan"]["plan_id"]
    assert p["plan"]["agent_manifest_id"] is None
    a = decide(lab, pid).json()
    r = execute(lab, pid)
    assert r.status_code == 409 and code(r) == "AGENT_MANIFEST_NOT_QUALIFIED"
    assert r.json()["error"]["details"]["step"] == 5
    view = read_plan(lab, pid).json()
    assert view["state"] == "APPROVED" and view["decision"]["status"] == "active"  # not consumed
    assert active(lab)["active"]["release_revision"] == 0 and a["approval_id"] == view["decision"]["approval_id"]


def test_null_manifest_plan_stays_blocked_after_a_manifest_qualifies(tested, monkeypatch):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    monkeypatch.setattr(release_plans, "qualified_agent_manifest", lambda conn, ws: {"manifest_id": "mf_later"})
    assert code(execute(lab, pid)) == "AGENT_MANIFEST_MISMATCH"


def test_manifest_changed_after_approval_is_denied(tested, qualified, monkeypatch):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    monkeypatch.setattr(release_plans, "qualified_agent_manifest", lambda conn, ws: {"manifest_id": "mf_other"})
    assert code(execute(lab, pid)) == "AGENT_MANIFEST_MISMATCH"


def test_suite_change_invalidates_test_evidence(tested, qualified, monkeypatch):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    monkeypatch.setattr(release_plans, "SUITE_SHA256", "0" * 64)
    r = execute(lab, pid)
    assert code(r) == "TEST_EVIDENCE_MISSING" and r.json()["error"]["details"]["step"] == 5


def test_stale_release_revision_is_denied(tested, qualified):
    """SEC-08: the active release changed after the approval."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    with lab.store().write() as conn:  # TRUSTED TEST-ONLY: another release happened meanwhile
        conn.execute("UPDATE active_releases SET release_revision = 5 WHERE workspace_id = 'demo-001'")
    r = execute(lab, pid)
    assert code(r) == "RELEASE_REVISION_STALE" and r.json()["error"]["details"]["current_release_revision"] == 5


def test_environment_change_is_denied(tested, qualified, monkeypatch):
    """SEC-07: the plan's environment no longer matches the policy environment."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    monkeypatch.setattr(executions, "ENVIRONMENT", "demo-staging")
    assert code(execute(lab, pid)) == "ENVIRONMENT_MISMATCH"
    assert active(lab)["active"]["release_revision"] == 0


def test_tampered_approval_hash_is_denied(tested, qualified):
    """SEC-07: an approval row bound to a different plan hash (tamper simulated past the trigger)."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    with lab.store().write() as conn:  # TRUSTED TEST-ONLY tamper: drop the immutability trigger first
        conn.execute("DROP TRIGGER approvals_decision_immutable")
        conn.execute("UPDATE approvals SET plan_sha256 = ?", ("c" * 64,))
    assert code(execute(lab, pid)) == "APPROVAL_PLAN_MISMATCH"
    with lab.store().write() as conn:
        conn.execute("UPDATE approvals SET plan_sha256 = (SELECT plan_sha256 FROM release_plans), "
                     "snapshot_sha256 = ?", ("d" * 64,))
    assert code(execute(lab, pid)) == "APPROVAL_SNAPSHOT_MISMATCH"


def test_requested_plan_hash_must_match(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    assert code(execute(lab, pid, plan_sha256="e" * 64)) == "PLAN_HASH_MISMATCH"


def test_candidate_patch_after_approval_needs_its_own_plan_and_approval(tested, qualified):
    """SEC-17: approving plan A does not authorize a patched candidate's plan B."""
    lab, ref, _ = tested
    pa = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pa)
    with lab.store().read() as conn:  # TRUSTED TEST-ONLY read of the fixture bytes (not a developer path)
        src = bytes(conn.execute("SELECT source FROM candidates WHERE candidate_id = ?",
                                 (ref["candidate_id"],)).fetchone()[0]).decode()
    patched = lab.client.post("/v1/candidates", json={"source": src + "\n# patched after approval\n"},
                              headers=headers("developer")).json()
    assert lab.run_tests(patched["candidate_id"]).json()["outcome"] == "pass"
    pb = make_plan(lab, "deploy", patched["candidate_id"])["plan"]["plan_id"]
    assert code(execute(lab, pb)) == "APPROVAL_REQUIRED"
    assert active(lab)["active"]["release_revision"] == 0


def test_stop_flag_blocks_execution_until_resume(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    instr = {"workspace_id": "demo-001"}
    assert lab.client.post("/v1/instructor/actions", json={"action": "stop", **instr},
                           headers=headers("instructor", None)).status_code == 200
    r = execute(lab, pid)
    assert code(r) == "WORKSPACE_STOPPED" and r.json()["error"]["details"]["step"] == 1
    assert lab.client.post("/v1/release-plans", json={"action": "deploy", "candidate_id": ref["candidate_id"]},
                           headers=headers("operations")).json()["error"]["code"] == "WORKSPACE_STOPPED"
    assert lab.client.post("/v1/instructor/actions", json={"action": "resume", **instr},
                           headers=headers("instructor", None)).status_code == 200
    assert execute(lab, pid).status_code == 201


def test_cancelled_run_cannot_execute(tested, qualified):
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    run = lab.client.post("/v1/runs", json={"conversation_id": "p09"}, headers=headers("operations")).json()["run_id"]
    instr = {"workspace_id": "demo-001"}
    lab.client.post("/v1/instructor/actions", json={"action": "stop", **instr}, headers=headers("instructor", None))
    lab.client.post("/v1/instructor/actions", json={"action": "resume", **instr}, headers=headers("instructor", None))
    r = execute(lab, pid, run=run)
    assert r.status_code == 409 and code(r) == "RUN_NOT_ACTIVE"
    assert active(lab)["active"]["release_revision"] == 0


def test_stop_while_execution_is_pending_prevents_the_commit(tested, qualified, monkeypatch):
    """SEC-13: the run is cancelled after the call was admitted; the late transaction must not commit."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    run = lab.client.post("/v1/runs", json={"conversation_id": "p09-late"},
                          headers=headers("operations")).json()["run_id"]
    real = executions.rollback_smoke_needed

    def stop_meanwhile(conn, *a):
        lab.client.post("/v1/instructor/actions", json={"action": "stop", "workspace_id": "demo-001"},
                        headers=headers("instructor", None))
        return real(conn, *a)
    monkeypatch.setattr(executions, "rollback_smoke_needed", stop_meanwhile)
    r = execute(lab, pid, run=run)
    assert r.status_code == 409 and code(r) in ("RUN_NOT_ACTIVE", "WORKSPACE_STOPPED")
    assert active(lab)["active"]["release_revision"] == 0 and read_plan(lab, pid).json()["decision"]["status"] == \
        "active"


def test_wrong_roles_cannot_execute_approve_or_control(tested, qualified):
    """SEC-03 and Gate 09: agents cannot call approval, drill, reset or evaluator routes."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    for role in ("coordinator", "product_owner", "developer", "qa", "application", "human_approver", "instructor",
                 "evaluator"):
        assert execute(lab, pid, role=role).status_code == 403, role
    for role in AGENT_ROLES:
        assert decide(lab, pid, role=role).status_code == 403, role
        for body in ({"action": "drill_enable", "workspace_id": "demo-001", "fault_type": "completion_unavailable",
                      "candidate_id": ref["candidate_id"]},
                     {"action": "reset_confirm", "workspace_id": "demo-001", "confirm": "demo-001"},
                     {"action": "stop", "workspace_id": "demo-001"}):
            assert lab.client.post("/v1/instructor/actions", json=body,
                                   headers=headers(role, None)).status_code == 403, (role, body["action"])
        assert lab.client.post("/v1/agent-evaluations", json={}, headers=headers(role)).status_code == 403, role
    assert count(lab, "approvals") == 0 and count(lab, "drills") == 0


def test_reset_with_pending_approval_invalidates_it(tested, qualified):
    """SEC-18: an old generation's plan/approval cannot act on the newly seeded session."""
    lab, ref, _ = tested
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    r = lab.client.post("/v1/instructor/actions", json={"action": "reset_confirm", "workspace_id": "demo-001",
                                                        "confirm": "demo-001"}, headers=headers("instructor", None))
    assert r.status_code == 200, r.text
    assert pid in r.json()["cancelled"]["open_plans"]
    e = execute(lab, pid)
    assert e.status_code == 409 and code(e) == "PLAN_STALE_GENERATION"
    view = read_plan(lab, pid).json()
    assert view["state"] == "EXPIRED" and view["decision"]["status"] == "cancelled"
    assert active(lab)["active"]["release_revision"] == 0


# ------------------------------------------------------------------ rollback (A11 step 6, REC-02)
def _deployed(lab, ref):
    pid = make_plan(lab, "deploy", ref["candidate_id"])["plan"]["plan_id"]
    decide(lab, pid)
    assert execute(lab, pid).status_code == 201
    return pid


def test_approved_rollback_runs_baseline_smoke_restores_v0_and_preserves_tasks(tested, qualified):
    lab, ref, _ = tested
    deploy_pid = _deployed(lab, ref)
    assert lab.cmd("complete T001").json()["code"] == "COMPLETED"
    lab.cmd("add Kept after rollback")
    before = tasks(lab)
    rb = make_plan(lab, "rollback", _starter_id(lab))
    assert rb["plan"]["expected_release_revision"] == 1
    assert rb["review_snapshot"]["agent_baseline_manifest"]["status"] == "NOT_REQUIRED_FOR_ROLLBACK"
    decide(lab, rb["plan"]["plan_id"])
    r = execute(lab, rb["plan"]["plan_id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["baseline_smoke"]["outcome"] == "pass"
    rc = body["receipt"]
    assert rc["operation"] == "rollback" and rc["release_revision"] == 2 and rc["previous_sha256"] == ref["sha256"]
    assert rc["evidence"]["baseline_smoke_id"] == body["baseline_smoke"]["smoke_id"]
    assert rc["rolled_back_plan_id"] == deploy_pid
    assert read_plan(lab, deploy_pid).json()["state"] == "ROLLED_BACK"
    assert tasks(lab) == before and before[0]["completed"] is True  # REC-02: records preserved
    assert lab.cmd("complete T002").json()["code"] == "FEATURE_UNAVAILABLE"  # completion withdrawn
    with lab.store().read() as conn:
        smoke = conn.execute("SELECT cases_json FROM baseline_smoke_runs").fetchone()[0]
    assert all(k in smoke for k in ("BS-01", "BS-02", "BS-03", "BS-04", "BS-05"))


def test_rollback_without_a_passing_baseline_smoke_is_denied(tested, qualified, monkeypatch):
    lab, ref, _ = tested
    _deployed(lab, ref)
    rb = make_plan(lab, "rollback", _starter_id(lab))["plan"]["plan_id"]
    decide(lab, rb)
    monkeypatch.setattr(executions, "rollback_smoke_needed", lambda *a: None)
    r = execute(lab, rb)
    assert code(r) == "BASELINE_SMOKE_REQUIRED" and r.json()["error"]["details"]["step"] == 6


def test_rollback_smoke_without_runner_fails_closed(db_path, monkeypatch):
    from tests.conftest import Lab
    lab = Lab(db_path, runner=False)
    lab.seed()
    ref = lab.load_fixture("reference_complete")
    lab.activate(ref)  # TRUSTED TEST-ONLY pointer change (no runner -> no tests -> no real deploy possible)
    rb = make_plan(lab, "rollback", _starter_id(lab))["plan"]["plan_id"]
    decide(lab, rb)
    r = execute(lab, rb)
    assert code(r) == "BASELINE_SMOKE_REQUIRED"
    with lab.store().read() as conn:
        assert conn.execute("SELECT outcome FROM baseline_smoke_runs").fetchone()[0] == "fail"
