"""Release readiness and canonical release plans (Architecture A8, A10, A11; Phase 08).

* ``compute_readiness`` derives the release gates from recorded evidence only: the
  candidate's verified bytes, an immutable protected test report for the exact hash
  under the current suite, the agent-system manifest (Phase 10; until then always
  NOT_QUALIFIED), app health and the current release revision. No caller boolean is read.
* ``create_plan`` binds one immutable plan (``release_plans`` is append-only) to the
  operation, the fixed environment ``demo-production``, the target and current hashes,
  the expected release revision and the evidence IDs, and hashes those consequential
  fields (``plan_sha256``, canonical JSON, excluding the hash itself). Its state goes
  PLANNED -> AWAITING_APPROVAL in the same transaction. An identical live plan is
  returned instead of a second one (application-level deduplication, A10).
* A plan is not an approval and nothing here changes the active artifact. Approval is
  ``approvals.py`` (human-only); execution is ``executions.py`` (A11).
* Phase 09 (plan schema 1.1) allowed a deploy plan bound to ``agent_manifest_id: null`` while no
  manifest could exist. **Phase 10 (plan schema 1.2)** restores the requirement: a deploy plan is
  created only when every gate passes, including the qualified agent-system manifest
  (``agent_evaluations.manifest_gate``), and binds that manifest's id. Rollback plans bind
  ``null`` (an agent baseline is not required to return to the recorded healthy v0). Old 1.1
  plans bound to null stay reviewable and are still refused at A11 step 5.
* ``review_snapshot`` is the exact immutable preview a human reviews; ``snapshot_sha256``
  (canonical JSON) is what an approval is bound to, together with ``plan_sha256``.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from .audit import record_event
from .candidates import get_candidate, verify_integrity
from .clock import parse_iso, to_iso, utc_now
from .releases import active_drill, app_health, resolve_active_candidate
from .store import LabError, require_active_workspace
from .testing import SUITE_SHA256, SUITE_VERSION

PLAN_SCHEMA_VERSION = "1.2"  # 1.2 (Phase 10): deploy binds the qualified manifest id; rollback binds null
POLICY_VERSION = ("tasksprint-release-policy/3 (Phase 10: qualified agent-system manifest gate; human approval + "
                  "transactional execution, A11)")
SNAPSHOT_SCHEMA = "tasksprint-review-snapshot/1"
ENVIRONMENT = "demo-production"
PLAN_TTL = timedelta(minutes=15)
CANONICAL_FIELDS = ("schema_version", "plan_id", "workspace_id", "operation", "environment", "target_candidate_id",
                    "target_sha256", "current_sha256", "expected_release_revision", "app_test_run_id",
                    "agent_manifest_id", "baseline_evidence_id", "expires_at")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({k: plan[k] for k in CANONICAL_FIELDS}).encode("ascii")).hexdigest()


# ------------------------------------------------------------------ evidence lookups
def qualified_agent_manifest(conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any] | None:
    """The approved agent-system manifest that qualifies a deployment, or None (fail closed).

    Phase 10: the newest QUALIFIED independent evaluation report whose manifest still matches the
    live system (``agent_evaluations.manifest_gate``: lab side recomputed now, latest attestation of
    the Langflow/harness side, no later failing evaluation, verification age). Returns the gate
    record (with ``manifest_id``) only when its status is PASS.
    """
    from .agent_evaluations import manifest_gate
    gate = manifest_gate(conn, workspace_id)
    return {**gate, "manifest_id": gate["agent_manifest_id"]} if gate["status"] == "PASS" else None


def manifest_gate_detail(conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
    from .agent_evaluations import manifest_gate
    return manifest_gate(conn, workspace_id)


def passing_report(conn: sqlite3.Connection, workspace_id: str, candidate_id: str, sha256: str,
                   test_run_id: str | None = None) -> sqlite3.Row | None:
    """Newest (or the named) passing report for the exact hash under the current suite."""
    sql = ("SELECT * FROM test_runs WHERE workspace_id = ? AND candidate_id = ? AND candidate_sha256 = ?"
           " AND outcome = 'pass' AND suite_sha256 = ?")
    args: list[Any] = [workspace_id, candidate_id, sha256, SUITE_SHA256]
    if test_run_id is not None:
        sql += " AND test_run_id = ?"
        args.append(test_run_id)
    return conn.execute(sql + " ORDER BY created_at DESC, rowid DESC LIMIT 1", args).fetchone()


def _latest_tested_candidate(conn: sqlite3.Connection, workspace_id: str, active_sha: str) -> str | None:
    row = conn.execute(
        "SELECT candidate_id FROM test_runs WHERE workspace_id = ? AND outcome = 'pass' AND suite_sha256 = ?"
        " AND candidate_sha256 != ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (workspace_id, SUITE_SHA256, active_sha)).fetchone()
    return row["candidate_id"] if row else None


def baseline_candidate_id(conn: sqlite3.Connection, workspace_id: str, baseline_sha: str) -> str | None:
    """The candidate record of the recorded healthy baseline (candidates are unique per workspace and hash)."""
    row = conn.execute("SELECT candidate_id FROM candidates WHERE workspace_id = ? AND sha256 = ?",
                       (workspace_id, baseline_sha)).fetchone()
    return row["candidate_id"] if row else None


def baseline_release(conn: sqlite3.Connection, workspace_id: str, baseline_sha: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM releases WHERE workspace_id = ? AND active_sha256 = ? ORDER BY release_revision LIMIT 1",
        (workspace_id, baseline_sha)).fetchone()


# ------------------------------------------------------------------ readiness
def compute_readiness(conn: sqlite3.Connection, workspace_id: str, candidate_id: str | None) -> dict[str, Any]:
    ws = require_active_workspace(conn, workspace_id)
    active, _active_cand = resolve_active_candidate(conn, workspace_id)
    health = app_health(conn, workspace_id)
    selected_by = "requested"
    if candidate_id is None:
        candidate_id = _latest_tested_candidate(conn, workspace_id, active["active_sha256"])
        selected_by = "latest_passing_report"
    gates: list[dict[str, Any]] = []
    cand_view: dict[str, Any] | None = None
    if candidate_id is None:
        gates.append({"gate": "candidate", "status": "MISSING",
                      "reason": "no candidate other than the active artifact has a passing protected test report"})
    else:
        row = get_candidate(conn, workspace_id, candidate_id)
        if row is None:
            gates.append({"gate": "candidate", "status": "MISSING", "candidate_id": candidate_id,
                          "reason": "candidate does not exist in this workspace"})
        elif not verify_integrity(row):
            gates.append({"gate": "candidate", "status": "FAIL", "candidate_id": candidate_id,
                          "reason": "stored bytes do not match the recorded hash"})
        else:
            cand_view = {"candidate_id": row["candidate_id"], "sha256": row["sha256"], "origin": row["origin"],
                         "label": row["label"], "selected_by": selected_by}
            gates.append({"gate": "candidate", "status": "PASS", "candidate_id": row["candidate_id"],
                          "sha256": row["sha256"]})
            same = row["sha256"] == active["active_sha256"]
            gates.append({"gate": "differs_from_active", "status": "FAIL" if same else "PASS",
                          **({"reason": "candidate is already the active artifact"} if same else {})})
            rep = passing_report(conn, workspace_id, row["candidate_id"], row["sha256"])
            if rep is None:
                any_rep = conn.execute(
                    "SELECT test_run_id, outcome, suite_sha256 FROM test_runs WHERE workspace_id = ? AND"
                    " candidate_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (workspace_id, row["candidate_id"])).fetchone()
                reason = ("no protected test report for this exact hash" if any_rep is None else
                          f"latest report {any_rep['test_run_id']} is '{any_rep['outcome']}'" +
                          ("" if any_rep["suite_sha256"] == SUITE_SHA256 else " under a different suite version"))
                gates.append({"gate": "application_tests", "status": "FAIL" if any_rep else "MISSING",
                              "test_run_id": any_rep["test_run_id"] if any_rep else None, "reason": reason})
            else:
                gates.append({"gate": "application_tests", "status": "PASS", "test_run_id": rep["test_run_id"],
                              "candidate_sha256": rep["candidate_sha256"], "suite_sha256": rep["suite_sha256"],
                              "suite_version": SUITE_VERSION})
    manifest = qualified_agent_manifest(conn, workspace_id)
    if manifest:
        gates.append({"gate": "agent_system_manifest", "status": "PASS", "agent_manifest_id": manifest["manifest_id"],
                      **{k: manifest[k] for k in ("manifest_sha256", "report_id", "qualified_at", "last_verified_at")
                         if k in manifest}})
    else:
        detail = manifest_gate_detail(conn, workspace_id)
        status = detail["status"] if detail["status"] != "PASS" else "NOT_QUALIFIED"
        gates.append({"gate": "agent_system_manifest", "status": status,
                      "agent_manifest_id": detail.get("agent_manifest_id"),
                      "reason": detail.get("reason", "no qualified agent-system manifest"),
                      **({"changed": detail["changed"]} if detail.get("changed") else {})})
    drill = active_drill(conn, workspace_id, cand_view["sha256"]) if cand_view else None
    gates.append({"gate": "no_incident_on_target", "status": "FAIL" if drill else "PASS"})
    blocking = [g["gate"] for g in gates if g["status"] != "PASS"]
    baseline = baseline_release(conn, workspace_id, ws["baseline_sha256"])
    rollback_available = active["active_sha256"] != ws["baseline_sha256"] and baseline is not None
    baseline_cand = baseline_candidate_id(conn, workspace_id, ws["baseline_sha256"])
    return {
        "record_type": "release_readiness",
        "policy_version": POLICY_VERSION,
        "computed_at": to_iso(utc_now()),
        "workspace_id": workspace_id, "generation": ws["generation"], "environment": ws["environment"],
        "release": {"active_candidate_id": active["active_candidate_id"], "active_sha256": active["active_sha256"],
                    "release_revision": active["release_revision"], "previous_sha256": active["previous_sha256"],
                    "baseline_sha256": ws["baseline_sha256"], "baseline_candidate_id": baseline_cand,
                    "active_is_baseline": active["active_sha256"] == ws["baseline_sha256"]},
        "app_health": {"status": health["status"]},
        "candidate": cand_view,
        "gates": gates,
        "deploy": {"status": "READY" if not blocking else "BLOCKED", "blocking_gates": blocking},
        "rollback": {"available": rollback_available,
                     "target_sha256": ws["baseline_sha256"] if rollback_available else None,
                     # Phase 12: the candidate ID to pass to create_release_plan(action rollback), so one
                     # Operations request can plan the rollback without a hand-supplied ID.
                     "target_candidate_id": baseline_cand if rollback_available else None,
                     "baseline_evidence_id": baseline["release_id"] if (baseline and rollback_available) else None,
                     **({} if rollback_available else
                        {"reason": "the active artifact is the recorded healthy baseline; nothing to roll back"})},
        "note": "Readiness is computed from recorded evidence. It is not an approval and executes nothing.",
    }


# ------------------------------------------------------------------ plans
def _state(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM release_plan_states WHERE plan_id = ?", (plan_id,)).fetchone()


def effective_state(plan: dict[str, Any], state: str) -> str:
    if state in ("PLANNED", "AWAITING_APPROVAL", "APPROVED") and parse_iso(plan["expires_at"]) <= utc_now():
        return "EXPIRED"
    return state


def create_plan(conn: sqlite3.Connection, *, workspace_id: str, operation: str, candidate_id: str,
                app_test_run_id: str | None, request_id: str, actor_role: str, run_id: str | None) -> dict[str, Any]:
    ws = require_active_workspace(conn, workspace_id)
    if ws["stopped"]:
        raise LabError(409, "WORKSPACE_STOPPED", "the instructor has stopped this workspace; no plan was created")
    active, _ = resolve_active_candidate(conn, workspace_id)
    row = get_candidate(conn, workspace_id, candidate_id)
    if row is None:
        raise LabError(404, "CANDIDATE_NOT_FOUND", "candidate does not exist in this workspace")
    if not verify_integrity(row):
        raise LabError(500, "ARTIFACT_INTEGRITY_ERROR", "stored candidate does not match its hash")
    if row["sha256"] == active["active_sha256"]:
        raise LabError(409, "TARGET_ALREADY_ACTIVE", "the target is already the active artifact; nothing to plan",
                       {"audit": {"candidate_id": candidate_id}})
    test_ref = manifest_ref = baseline_ref = None
    if operation == "deploy":
        rep = passing_report(conn, workspace_id, candidate_id, row["sha256"], app_test_run_id)
        manifest = qualified_agent_manifest(conn, workspace_id)
        blocking = []
        if rep is None:
            blocking.append("application_tests")
        if manifest is None:
            blocking.append("agent_system_manifest")
        if active_drill(conn, workspace_id, row["sha256"]) is not None:
            blocking.append("no_incident_on_target")
        if blocking:
            raise LabError(409, "RELEASE_NOT_READY", "deployment prerequisites are not met; no plan was created",
                           {"blocking_gates": blocking,
                            "audit": {"candidate_id": candidate_id, "blocking_gates": blocking}})
        # Plan schema 1.2: a deploy plan always binds the qualified agent-system manifest.
        test_ref, manifest_ref = rep["test_run_id"], manifest["manifest_id"]
    else:
        if row["sha256"] != ws["baseline_sha256"]:
            raise LabError(409, "ROLLBACK_TARGET_NOT_BASELINE",
                           "rollback may only target the recorded healthy baseline in this lab",
                           {"audit": {"candidate_id": candidate_id}})
        if app_test_run_id is not None:
            raise LabError(422, "UNEXPECTED_FIELD", "app_test_run_id is only used for a deploy plan")
        base = baseline_release(conn, workspace_id, ws["baseline_sha256"])
        if base is None:
            raise LabError(409, "BASELINE_EVIDENCE_MISSING", "no recorded healthy baseline release")
        baseline_ref = base["release_id"]
    now = utc_now()
    existing = conn.execute(
        "SELECT p.plan_id, p.plan_json FROM release_plans p JOIN release_plan_states s ON s.plan_id = p.plan_id"
        " WHERE p.workspace_id = ? AND p.generation = ? AND p.operation = ? AND s.state = 'AWAITING_APPROVAL'"
        " ORDER BY p.created_at DESC", (workspace_id, ws["generation"], operation)).fetchall()
    for ex in existing:
        plan = json.loads(ex["plan_json"])
        if (plan["target_sha256"] == row["sha256"] and plan["current_sha256"] == active["active_sha256"]
                and plan["expected_release_revision"] == active["release_revision"]
                and plan["app_test_run_id"] == test_ref and plan["agent_manifest_id"] == manifest_ref
                and plan["baseline_evidence_id"] == baseline_ref and parse_iso(plan["expires_at"]) > now):
            record_event(conn, request_id=request_id, actor_role=actor_role, action="release_plan.create",
                         outcome="duplicate", workspace_id=workspace_id, run_id=run_id,
                         details={"plan_id": plan["plan_id"], "plan_sha256": plan["plan_sha256"],
                                  "operation": operation})
            return {**plan_view(conn, ex["plan_id"]), "created": False}
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION, "plan_id": "plan_" + secrets.token_hex(12),
        "workspace_id": workspace_id, "operation": operation, "environment": ENVIRONMENT,
        "target_candidate_id": row["candidate_id"], "target_sha256": row["sha256"],
        "current_sha256": active["active_sha256"], "expected_release_revision": active["release_revision"],
        "app_test_run_id": test_ref, "agent_manifest_id": manifest_ref, "baseline_evidence_id": baseline_ref,
        "expires_at": to_iso(now + PLAN_TTL),
    }
    plan["plan_sha256"] = plan_hash(plan)
    stamp = to_iso(now)
    conn.execute("INSERT INTO release_plans(plan_id, workspace_id, generation, operation, plan_json, plan_sha256,"
                 " created_at) VALUES (?,?,?,?,?,?,?)",
                 (plan["plan_id"], workspace_id, ws["generation"], operation, canonical_json(plan),
                  plan["plan_sha256"], stamp))
    conn.execute("INSERT INTO release_plan_states(plan_id, state, revision, updated_at) VALUES (?,?,1,?)",
                 (plan["plan_id"], "PLANNED", stamp))
    record_event(conn, request_id=request_id, actor_role=actor_role, action="release_plan.create", outcome="ok",
                 workspace_id=workspace_id, run_id=run_id,
                 details={"plan_id": plan["plan_id"], "plan_sha256": plan["plan_sha256"], "operation": operation,
                          "target_candidate_id": row["candidate_id"], "expected_release_revision":
                          active["release_revision"], "app_test_run_id": test_ref, "agent_manifest_id": manifest_ref,
                          "baseline_evidence_id": baseline_ref})
    conn.execute("UPDATE release_plan_states SET state = 'AWAITING_APPROVAL', revision = 2, updated_at = ?"
                 " WHERE plan_id = ? AND state = 'PLANNED' AND revision = 1", (stamp, plan["plan_id"]))
    record_event(conn, request_id=request_id, actor_role=actor_role, action="release_plan.state", outcome="ok",
                 workspace_id=workspace_id, run_id=run_id,
                 details={"plan_id": plan["plan_id"], "from": "PLANNED", "to": "AWAITING_APPROVAL"})
    return {**plan_view(conn, plan["plan_id"]), "created": True}


def _approval_row(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM approvals WHERE plan_id = ?", (plan_id,)).fetchone()


def approval_summary(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"approval_id": row["approval_id"], "decision": row["decision"], "status": row["status"],
            "plan_sha256": row["plan_sha256"], "snapshot_sha256": row["snapshot_sha256"],
            "approver": row["approver"], "display_name": row["display_name"], "created_at": row["created_at"],
            "expires_at": row["expires_at"], "consumed_at": row["consumed_at"],
            "hitl_request_id": row["hitl_request_id"]}


def review_snapshot(conn: sqlite3.Connection, plan: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The exact immutable human-review preview of a plan and its SHA-256 (canonical JSON).

    Built only from immutable records (the plan, the target candidate, the referenced test
    report, the recorded baseline), so the same plan always yields the same snapshot hash.
    """
    target = get_candidate(conn, plan["workspace_id"], plan["target_candidate_id"])
    current = conn.execute("SELECT candidate_id, origin, label FROM candidates WHERE workspace_id = ? AND sha256 = ?",
                           (plan["workspace_id"], plan["current_sha256"])).fetchone()
    report = (conn.execute("SELECT test_run_id, outcome, suite_sha256, candidate_sha256, runner_version, created_at"
                           " FROM test_runs WHERE test_run_id = ?", (plan["app_test_run_id"],)).fetchone()
              if plan["app_test_run_id"] else None)
    ws = conn.execute("SELECT baseline_sha256 FROM workspaces WHERE workspace_id = ?",
                      (plan["workspace_id"],)).fetchone()
    snapshot = {
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "plan_id": plan["plan_id"], "plan_sha256": plan["plan_sha256"],
        "operation": plan["operation"], "environment": plan["environment"], "workspace_id": plan["workspace_id"],
        "target": {"candidate_id": plan["target_candidate_id"], "sha256": plan["target_sha256"],
                   "origin": target["origin"] if target else None, "label": target["label"] if target else None,
                   "author_role": target["author_role"] if target else None},
        "current": {"sha256": plan["current_sha256"], "candidate_id": current["candidate_id"] if current else None,
                    "label": current["label"] if current else None},
        "expected_release_revision": plan["expected_release_revision"],
        "application_test_evidence": None if report is None else {
            "test_run_id": report["test_run_id"], "outcome": report["outcome"],
            "candidate_sha256": report["candidate_sha256"], "suite_sha256": report["suite_sha256"],
            "runner_version": report["runner_version"], "created_at": report["created_at"]},
        "agent_baseline_manifest": {
            "agent_manifest_id": plan["agent_manifest_id"],
            "status": "BOUND" if plan["agent_manifest_id"] else (
                "NOT_REQUIRED_FOR_ROLLBACK" if plan["operation"] == "rollback" else
                "NOT_QUALIFIED - plan schema 1.1 bound no manifest; execution is always refused "
                "(AGENT_MANIFEST_NOT_QUALIFIED)")},
        "rollback_target": {"sha256": ws["baseline_sha256"] if ws else None,
                            "baseline_evidence_id": plan["baseline_evidence_id"]},
        "plan_expires_at": plan["expires_at"],
        "consent_scope": ("A decision applies only to this plan_sha256 and this snapshot. An approval expires 15 "
                          "minutes after it is recorded (never later than the plan), can be used once, and does "
                          "not by itself release anything: execution re-verifies evidence, manifest, environment, "
                          "release revision and the stop flag."),
    }
    return snapshot, hashlib.sha256(canonical_json(snapshot).encode("ascii")).hexdigest()


def plan_view(conn: sqlite3.Connection, plan_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    sql = "SELECT * FROM release_plans WHERE plan_id = ?"
    args: list[Any] = [plan_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        args.append(workspace_id)
    row = conn.execute(sql, args).fetchone()
    if row is None:
        raise LabError(404, "PLAN_NOT_FOUND", "release plan does not exist in this workspace")
    plan = json.loads(row["plan_json"])
    if plan_hash(plan) != row["plan_sha256"] or plan.get("plan_sha256") != row["plan_sha256"]:
        raise LabError(500, "PLAN_INTEGRITY_ERROR", "stored plan does not match its hash")
    st = _state(conn, plan_id)
    snapshot, snapshot_sha = review_snapshot(conn, plan)
    approval = _approval_row(conn, plan_id)
    executed = conn.execute("SELECT release_id, action_id, release_revision, created_at FROM releases"
                            " WHERE plan_id = ? ORDER BY release_revision LIMIT 1", (plan_id,)).fetchone()
    ws = conn.execute("SELECT generation FROM workspaces WHERE workspace_id = ?", (plan["workspace_id"],)).fetchone()
    eff = effective_state(plan, st["state"])
    if approval is None:
        approval_text = "none recorded; a human must approve this exact plan_sha256 with the protected control"
    else:
        approval_text = f"{approval['decision']} recorded ({approval['approval_id']}, status {approval['status']})"
    return {
        "record_type": "release_plan",
        "plan": plan,
        "state": st["state"], "state_revision": st["revision"],
        "effective_state": eff,
        "generation": row["generation"],
        "current_generation": ws["generation"] if ws else None,
        "integrity": {"plan_sha256_verified": True},
        "preview": {
            "operation": plan["operation"], "environment": plan["environment"],
            "target": snapshot["target"],
            "current_sha256": plan["current_sha256"],
            "expected_release_revision": plan["expected_release_revision"],
            "application_test_evidence": None if snapshot["application_test_evidence"] is None else {
                k: snapshot["application_test_evidence"][k] for k in ("test_run_id", "outcome", "suite_sha256")},
            "agent_baseline_manifest": plan["agent_manifest_id"],
            "agent_baseline_manifest_status": snapshot["agent_baseline_manifest"]["status"],
            "rollback_target_sha256": snapshot["rollback_target"]["sha256"],
            "expires_at": plan["expires_at"],
            "approval": approval_text,
        },
        "review_snapshot": snapshot,
        "snapshot_sha256": snapshot_sha,
        "decision": approval_summary(approval),
        "execution": None if executed is None else dict(executed),
        "created_at": row["created_at"],
    }
