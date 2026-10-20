"""Approved release execution: the transactional algorithm of Architecture A11 (Phase 09).

``execute`` runs inside ONE ``Store.write()`` transaction (BEGIN IMMEDIATE, single writer)
and performs, in order:

1. workspace active, run live (the caller re-checks the run in the same transaction) and
   the instructor stop flag clear;
2. replay check by action ID: an identical request returns the ORIGINAL receipt; the same
   action ID with a changed payload (or another workspace) is ACTION_CONFLICT;
3. the immutable plan (hash re-verified), its workspace generation and its current,
   unexpired, unused human approval;
4. approval bound to this plan_sha256 and to the snapshot the backend computes now; the
   caller's optional plan_sha256; target bytes/hash; environment; release revision and
   current active hash (the release concurrency token);
5. deploy: the exact candidate's passing protected report (the plan's test run, the same
   hash, the current suite) AND the approved agent-system manifest bound in the plan
   (none qualifies before Phase 10, so every deploy stops here);
6. rollback: the recorded healthy baseline release named in the plan and a passing
   baseline smoke report for that hash under the current smoke suite;
7. atomic pointer update + release revision increment + approval consumed + plan state +
   receipt + event; task records are not touched;
then, AFTER commit, ``post_activation`` (step 8) runs separately and records its result. A
failed post-check is an incident event, not evidence that the transaction did not happen.

Action IDs are generated outside the model: the MCP tool sends only ``plan_id`` and the
server derives ``act_<sha256(workspace:plan)[:24]>``; a trusted REST caller may supply its own.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from . import approvals, baseline_smoke, release_plans
from .audit import record_event
from .candidates import get_candidate, verify_integrity
from .clock import to_iso, utc_now
from .release_plans import (ENVIRONMENT, POLICY_VERSION, _state, baseline_release, canonical_json, passing_report,
                            plan_view)
from .releases import active_drill, app_health, resolve_active_candidate
from .store import LabError, require_active_workspace


def derive_action_id(workspace_id: str, plan_id: str) -> str:
    return "act_" + hashlib.sha256(f"tasksprint-action/1:{workspace_id}:{plan_id}".encode()).hexdigest()[:24]


def request_digest(plan_id: str, plan_sha256: str | None) -> str:
    return hashlib.sha256(canonical_json({"plan_id": plan_id, "plan_sha256": plan_sha256}).encode()).hexdigest()


def tasks_fingerprint(conn: sqlite3.Connection, workspace_id: str) -> str:
    rows = [list(r) for r in conn.execute("SELECT task_id, title, completed, revision FROM tasks WHERE workspace_id = ?"
                                          " ORDER BY task_id", (workspace_id,))]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def _deny(step: int, status: int, code: str, message: str, plan_id: str, action_id: str, **extra: Any) -> LabError:
    return LabError(status, code, message, {"step": step, "action_id": action_id, **extra,
                                            "audit": {"plan_id": plan_id, "action_id": action_id, "step": step,
                                                      **extra}})


def rollback_smoke_needed(conn: sqlite3.Connection, workspace_id: str, plan_id: str, action_id: str) -> str | None:
    """Read-only pre-pass: the baseline hash to smoke-test first, or None.

    Only for an existing, not-yet-executed rollback plan whose approval is currently valid and
    whose baseline has no passing smoke report yet; everything is re-checked in ``execute``.
    """
    if conn.execute("SELECT 1 FROM releases WHERE action_id = ?", (action_id,)).fetchone():
        return None
    row = conn.execute("SELECT plan_json, generation FROM release_plans WHERE plan_id = ? AND workspace_id = ?",
                       (plan_id, workspace_id)).fetchone()
    ws = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
    if row is None or ws is None or ws["stopped"] or row["generation"] != ws["generation"]:
        return None
    plan = json.loads(row["plan_json"])
    if plan["operation"] != "rollback" or plan["target_sha256"] != ws["baseline_sha256"]:
        return None
    if approvals.approval_problem(approvals.current_approval(conn, plan_id), generation=ws["generation"]):
        return None
    if baseline_smoke.passing_smoke(conn, workspace_id, ws["baseline_sha256"]) is not None:
        return None
    return ws["baseline_sha256"]


def execute(conn: sqlite3.Connection, *, workspace_id: str, plan_id: str, plan_sha256: str | None, action_id: str,
            request_id: str, actor_role: str, run_id: str | None) -> dict[str, Any]:
    digest = request_digest(plan_id, plan_sha256)
    # 1. workspace, (run re-checked by the caller in this transaction), stop flag
    ws = require_active_workspace(conn, workspace_id)
    if ws["stopped"]:
        raise _deny(1, 409, "WORKSPACE_STOPPED", "the instructor stop flag is set; nothing was executed",
                    plan_id, action_id)
    # 2. replay check by action ID
    prior = conn.execute("SELECT * FROM releases WHERE action_id = ?", (action_id,)).fetchone()
    if prior is not None:
        receipt = json.loads(prior["receipt_json"])
        if prior["workspace_id"] != workspace_id or receipt.get("request_sha256") != digest:
            raise _deny(2, 409, "ACTION_CONFLICT", "this action ID was already used with a different payload; "
                        "nothing was executed", plan_id, action_id, receipt_id=prior["release_id"])
        record_event(conn, request_id=request_id, actor_role=actor_role, action="release.execute", outcome="replay",
                     workspace_id=workspace_id, run_id=run_id,
                     details={"action_id": action_id, "plan_id": plan_id, "receipt_id": prior["release_id"]})
        return {"record_type": "release_execution", "replayed": True, "receipt": receipt,
                "note": "Identical replay: the original receipt is returned; nothing was executed again."}
    # 3. immutable plan, generation, current unexpired unused approval
    view = plan_view(conn, plan_id, workspace_id)
    plan = view["plan"]
    if view["generation"] != ws["generation"]:
        raise _deny(3, 409, "PLAN_STALE_GENERATION", "the plan belongs to an earlier workspace generation",
                    plan_id, action_id)
    approval = approvals.current_approval(conn, plan_id)
    problem = approvals.approval_problem(approval, generation=ws["generation"])
    if problem is not None:
        raise _deny(3, 409, problem[0], problem[1] + "; nothing was executed", plan_id, action_id,
                    approval_id=approval["approval_id"] if approval else None)
    if view["effective_state"] == "EXPIRED":
        raise _deny(3, 409, "PLAN_EXPIRED", "the plan has expired; nothing was executed", plan_id, action_id)
    if view["state"] != "APPROVED":
        raise _deny(3, 409, "PLAN_NOT_APPROVED", f"plan state is {view['state']}; nothing was executed",
                    plan_id, action_id)
    # 4. exact binding: plan hash, snapshot hash, target hash, environment, release revision
    if approval["plan_sha256"] != plan["plan_sha256"]:
        raise _deny(4, 409, "APPROVAL_PLAN_MISMATCH", "the approval is bound to a different plan hash",
                    plan_id, action_id)
    if plan_sha256 is not None and plan_sha256 != plan["plan_sha256"]:
        raise _deny(4, 409, "PLAN_HASH_MISMATCH", "the requested plan_sha256 differs from the stored plan",
                    plan_id, action_id)
    if approval["snapshot_sha256"] != view["snapshot_sha256"]:
        raise _deny(4, 409, "APPROVAL_SNAPSHOT_MISMATCH", "the approved review snapshot differs from the plan's "
                    "current snapshot", plan_id, action_id)
    target = get_candidate(conn, workspace_id, plan["target_candidate_id"])
    if target is None or not verify_integrity(target) or target["sha256"] != plan["target_sha256"]:
        raise _deny(4, 409, "TARGET_HASH_MISMATCH", "the target artifact does not match the planned hash",
                    plan_id, action_id)
    if plan["environment"] != ENVIRONMENT or ws["environment"] != plan["environment"]:
        raise _deny(4, 409, "ENVIRONMENT_MISMATCH", "the plan's environment is not this workspace's environment",
                    plan_id, action_id)
    active, _cand = resolve_active_candidate(conn, workspace_id)
    if (active["release_revision"] != plan["expected_release_revision"]
            or active["active_sha256"] != plan["current_sha256"]):
        raise _deny(4, 409, "RELEASE_REVISION_STALE", "the active release changed since the plan was made; a new "
                    "plan and approval are required", plan_id, action_id,
                    current_release_revision=active["release_revision"])
    evidence: dict[str, Any] = {"app_test_run_id": None, "agent_manifest_id": None, "baseline_evidence_id": None,
                                "baseline_smoke_id": None}
    if plan["operation"] == "deploy":
        # 5. exact candidate tests + approved agent-system manifest; recomputed, never a client boolean
        rep = passing_report(conn, workspace_id, target["candidate_id"], target["sha256"], plan["app_test_run_id"])
        if plan["app_test_run_id"] is None or rep is None:
            raise _deny(5, 409, "TEST_EVIDENCE_MISSING", "no passing protected report for this exact candidate hash "
                        "under the current suite", plan_id, action_id)
        manifest = release_plans.qualified_agent_manifest(conn, workspace_id)  # Phase 10 fills this gate
        if manifest is None:
            raise _deny(5, 409, "AGENT_MANIFEST_NOT_QUALIFIED", "no approved agent-system manifest exists (agent "
                        "evaluations are Phase 10); deployment stays blocked even with a valid human approval. "
                        "Nothing was executed and the approval was not consumed.", plan_id, action_id)
        if manifest.get("manifest_id") != plan["agent_manifest_id"]:
            raise _deny(5, 409, "AGENT_MANIFEST_MISMATCH", "the plan is bound to a different agent-system manifest "
                        "than the one currently approved", plan_id, action_id)
        if active_drill(conn, workspace_id, target["sha256"]) is not None:
            raise _deny(5, 409, "INCIDENT_ON_TARGET", "an incident drill is active for the target", plan_id, action_id)
        evidence.update(app_test_run_id=rep["test_run_id"], agent_manifest_id=manifest["manifest_id"])
    else:
        # 6. recorded healthy baseline + its smoke suite (not the new feature's tests)
        base = baseline_release(conn, workspace_id, ws["baseline_sha256"])
        if target["sha256"] != ws["baseline_sha256"] or base is None:
            raise _deny(6, 409, "BASELINE_EVIDENCE_MISSING", "rollback targets only the recorded healthy baseline",
                        plan_id, action_id)
        if base["release_id"] != plan["baseline_evidence_id"]:
            raise _deny(6, 409, "BASELINE_EVIDENCE_MISMATCH", "the plan names different baseline evidence",
                        plan_id, action_id)
        smoke = baseline_smoke.passing_smoke(conn, workspace_id, ws["baseline_sha256"])
        if smoke is None:
            raise _deny(6, 409, "BASELINE_SMOKE_REQUIRED", "no passing baseline smoke report for the rollback target",
                        plan_id, action_id)
        evidence.update(baseline_evidence_id=base["release_id"], baseline_smoke_id=smoke["smoke_id"])
    # 7. atomic activation; tasks untouched
    tasks_before = tasks_fingerprint(conn, workspace_id)
    now = to_iso(utc_now())
    new_rev = active["release_revision"] + 1
    cur = conn.execute("UPDATE active_releases SET active_candidate_id = ?, active_sha256 = ?, previous_sha256 = ?,"
                       " release_revision = ?, updated_at = ? WHERE workspace_id = ? AND release_revision = ? AND"
                       " active_sha256 = ?", (target["candidate_id"], target["sha256"], active["active_sha256"],
                                              new_rev, now, workspace_id, active["release_revision"],
                                              active["active_sha256"]))
    if cur.rowcount != 1:
        raise _deny(7, 409, "RELEASE_REVISION_STALE", "the active release changed concurrently", plan_id, action_id)
    cur = conn.execute("UPDATE approvals SET status = 'consumed', consumed_at = ? WHERE approval_id = ? AND"
                       " status = 'active' AND consumed_at IS NULL", (now, approval["approval_id"]))
    if cur.rowcount != 1:
        raise _deny(7, 409, "APPROVAL_ALREADY_USED", "the approval was consumed concurrently", plan_id, action_id)
    conn.execute("UPDATE release_plan_states SET state = 'EXECUTED', revision = revision + 1, updated_at = ?"
                 " WHERE plan_id = ? AND state = 'APPROVED'", (now, plan_id))
    rolled_back_plan = None
    if plan["operation"] == "rollback":
        prev = conn.execute("SELECT plan_id FROM releases WHERE workspace_id = ? AND active_sha256 = ? AND"
                            " operation = 'deploy' ORDER BY release_revision DESC LIMIT 1",
                            (workspace_id, active["active_sha256"])).fetchone()
        if prev is not None and prev["plan_id"] and _state(conn, prev["plan_id"])["state"] == "EXECUTED":
            rolled_back_plan = prev["plan_id"]
            conn.execute("UPDATE release_plan_states SET state = 'ROLLED_BACK', revision = revision + 1,"
                         " updated_at = ? WHERE plan_id = ?", (now, rolled_back_plan))
    release_id = "rel_" + hashlib.sha256(f"{workspace_id}:{action_id}".encode()).hexdigest()[:24]
    receipt = {
        "receipt_id": release_id, "action_id": action_id, "request_sha256": digest, "request_id": request_id,
        "policy_version": POLICY_VERSION, "operation": plan["operation"], "environment": plan["environment"],
        "workspace_id": workspace_id, "generation": ws["generation"],
        "plan_id": plan_id, "plan_sha256": plan["plan_sha256"],
        "approval_id": approval["approval_id"], "snapshot_sha256": approval["snapshot_sha256"],
        "approver": approval["approver"],
        "previous_sha256": active["active_sha256"], "active_sha256": target["sha256"],
        "active_candidate_id": target["candidate_id"], "release_revision": new_rev,
        "evidence": evidence, "rolled_back_plan_id": rolled_back_plan,
        "tasks_fingerprint_sha256": tasks_before, "executed_at": now, "executed_by": actor_role, "run_id": run_id,
    }
    conn.execute("INSERT INTO releases(release_id, workspace_id, release_revision, operation, active_sha256,"
                 " previous_sha256, plan_id, action_id, receipt_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (release_id, workspace_id, new_rev, plan["operation"], target["sha256"], active["active_sha256"],
                  plan_id, action_id, json.dumps(receipt, sort_keys=True), now))
    if tasks_fingerprint(conn, workspace_id) != tasks_before:  # defensive: activation must never touch tasks
        raise _deny(7, 500, "TASKS_CHANGED", "task records changed inside the release transaction", plan_id, action_id)
    receipt_event = record_event(conn, request_id=request_id, actor_role=actor_role, action="release.execute",
                                 outcome="ok", workspace_id=workspace_id, run_id=run_id,
                                 details={"receipt_id": release_id, "action_id": action_id, "plan_id": plan_id,
                                          "approval_id": approval["approval_id"], "operation": plan["operation"],
                                          "release_revision": new_rev, "active_sha256": target["sha256"],
                                          "previous_sha256": active["active_sha256"]})
    return {"record_type": "release_execution", "replayed": False, "receipt": receipt,
            "receipt_event_id": receipt_event}


def post_activation(conn: sqlite3.Connection, *, workspace_id: str, receipt: dict[str, Any], request_id: str,
                    actor_role: str, run_id: str | None) -> dict[str, Any]:
    """Step 8: separate, recorded post-activation checks (after the activation committed)."""
    checks: list[dict[str, Any]] = []
    try:
        active, _ = resolve_active_candidate(conn, workspace_id)
        checks.append({"check": "active_hash_matches_receipt", "passed": active["active_sha256"] ==
                       receipt["active_sha256"] and active["release_revision"] == receipt["release_revision"]})
    except LabError as err:
        checks.append({"check": "active_hash_matches_receipt", "passed": False, "code": err.code})
    health = app_health(conn, workspace_id)
    checks.append({"check": "app_health_healthy", "passed": health["status"] == "healthy", "status": health["status"]})
    passed = all(c["passed"] for c in checks)
    checks.append({"check": "tasks_fingerprint_equals_receipt", "informational": True,
                   "passed": tasks_fingerprint(conn, workspace_id) == receipt["tasks_fingerprint_sha256"]})
    event_id = record_event(conn, request_id=request_id, actor_role=actor_role, action="release.post_check",
                            outcome="pass" if passed else "incident", workspace_id=workspace_id, run_id=run_id,
                            details={"receipt_id": receipt["receipt_id"], "checks": {c["check"]: c["passed"]
                                                                                     for c in checks}})
    return {"passed": passed, "checks": checks, "event_id": event_id,
            "note": "Recorded separately from the activation; a failed post-check is an incident, not a rollback."}
