"""Human approval decisions (Architecture A5 approvals, A8 POST /v1/approvals, A11; Phase 09).

Only the ``human_approver`` credential reaches this writer (``auth.PERMISSIONS``); no MCP
tool exists for it and the agent-runtime roles are refused. The trusted TS-90 adapter calls
it after a native Human Input pause, but the backend does not trust the adapter either:

* the decision must quote the exact ``plan_sha256`` AND the ``snapshot_sha256`` of the
  canonical review snapshot (``release_plans.review_snapshot``) that was shown to the human;
* the plan must be AWAITING_APPROVAL, unexpired and of the workspace's current generation;
* one decision per plan (unique index): a second Approve/Reject is ALREADY_DECIDED, so a
  replayed click or a resumed checkpoint cannot create a second record;
* identity is the token's role (``role:human_approver``). ``display_name`` is a label that
  is stored and shown but confers no authority;
* an approval expires 15 minutes after it is recorded and never later than the plan, is
  ``active`` until execution consumes it, and is cancelled by a workspace reset. A rejection
  is ``closed`` at once and can never be executed.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from .audit import record_event
from .clock import parse_iso, to_iso, utc_now
from .release_plans import approval_summary, plan_view
from .store import LabError, require_active_workspace

APPROVAL_TTL = timedelta(minutes=15)
DISPLAY_NAME_NOTE = "display_name is a label only; authority comes from the human_approver credential"


def record_decision(conn: sqlite3.Connection, *, workspace_id: str, plan_id: str, plan_sha256: str,
                    snapshot_sha256: str, decision: str, display_name: str | None, hitl_request_id: str | None,
                    request_id: str, approver: str, actor_role: str) -> dict[str, Any]:
    ws = require_active_workspace(conn, workspace_id)
    view = plan_view(conn, plan_id, workspace_id)
    plan = view["plan"]
    audit = {"plan_id": plan_id, "decision": decision}
    if view["generation"] != ws["generation"]:
        raise LabError(409, "PLAN_STALE_GENERATION", "the plan belongs to an earlier workspace generation",
                       {"audit": audit})
    if plan_sha256 != plan["plan_sha256"]:
        raise LabError(409, "PLAN_HASH_MISMATCH", "the decision does not quote this plan's exact plan_sha256",
                       {"audit": audit})
    if snapshot_sha256 != view["snapshot_sha256"]:
        raise LabError(409, "SNAPSHOT_MISMATCH", "the decision does not quote the snapshot the backend computes for "
                       "this plan; reload the review", {"audit": audit})
    if view["decision"] is not None:
        d = view["decision"]
        raise LabError(409, "ALREADY_DECIDED", "a human decision is already recorded for this plan",
                       {"approval_id": d["approval_id"], "decision": d["decision"], "status": d["status"],
                        "audit": {**audit, "approval_id": d["approval_id"]}})
    if view["effective_state"] == "EXPIRED":
        raise LabError(409, "PLAN_EXPIRED", "the plan expired before a decision was recorded; ask Operations for a "
                       "new plan", {"audit": audit})
    if view["state"] != "AWAITING_APPROVAL":
        raise LabError(409, "PLAN_NOT_AWAITING_APPROVAL", f"plan state is {view['state']}", {"audit": audit})
    now = utc_now()
    expires = min(now + APPROVAL_TTL, parse_iso(plan["expires_at"]))
    approval_id = "apr_" + secrets.token_hex(12)
    status = "active" if decision == "approve" else "closed"
    conn.execute(
        "INSERT INTO approvals(approval_id, plan_id, plan_sha256, approver, decision, created_at, expires_at,"
        " consumed_at, workspace_id, generation, snapshot_sha256, display_name, hitl_request_id, request_id, status)"
        " VALUES (?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?)",
        (approval_id, plan_id, plan["plan_sha256"], approver, decision, to_iso(now), to_iso(expires), workspace_id,
         ws["generation"], view["snapshot_sha256"], display_name, hitl_request_id, request_id, status))
    new_state = "APPROVED" if decision == "approve" else "REJECTED"
    cur = conn.execute("UPDATE release_plan_states SET state = ?, revision = revision + 1, updated_at = ?"
                       " WHERE plan_id = ? AND state = 'AWAITING_APPROVAL'", (new_state, to_iso(now), plan_id))
    if cur.rowcount != 1:
        raise LabError(409, "PLAN_NOT_AWAITING_APPROVAL", "plan state changed concurrently", {"audit": audit})
    event_id = record_event(conn, request_id=request_id, actor_role=actor_role, action="approval.record",
                            outcome=decision, workspace_id=workspace_id, run_id=None,
                            details={"approval_id": approval_id, "plan_id": plan_id, "plan_sha256": plan["plan_sha256"],
                                     "snapshot_sha256": view["snapshot_sha256"], "decision": decision,
                                     "expires_at": to_iso(expires), "display_name": display_name,
                                     "hitl_request_id": hitl_request_id})
    record_event(conn, request_id=request_id, actor_role=actor_role, action="release_plan.state", outcome="ok",
                 workspace_id=workspace_id, run_id=None,
                 details={"plan_id": plan_id, "from": "AWAITING_APPROVAL", "to": new_state, "approval_id": approval_id})
    row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
    return {"record_type": "approval_decision", **approval_summary(row), "plan_state": new_state,
            "approver_identity": approver, "display_name_confers_authority": False, "event_id": event_id,
            "note": ("Recorded against the exact plan and snapshot hash. Nothing was executed. "
                     + ("Operations may now request execution; the backend re-verifies everything."
                        if decision == "approve" else "A rejected plan can never be executed.")
                     + " " + DISPLAY_NAME_NOTE)}


def current_approval(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM approvals WHERE plan_id = ?", (plan_id,)).fetchone()


def approval_problem(row: sqlite3.Row | None, *, generation: int) -> tuple[str, str] | None:
    """Why an approval cannot authorize execution, or None when it is current, unexpired and unused."""
    if row is None:
        return "APPROVAL_REQUIRED", "no human approval is recorded for this plan"
    if row["decision"] != "approve":
        return "APPROVAL_REJECTED", "the human rejected this plan; it can never be executed"
    if row["status"] == "consumed" or row["consumed_at"] is not None:
        return "APPROVAL_ALREADY_USED", "this approval was already consumed by an execution"
    if row["status"] == "cancelled":
        return "APPROVAL_CANCELLED", "this approval was cancelled (workspace reset)"
    if row["status"] != "active":
        return "APPROVAL_NOT_ACTIVE", f"approval status is {row['status']}"
    if row["generation"] != generation:
        return "APPROVAL_STALE_GENERATION", "this approval belongs to an earlier workspace generation"
    if parse_iso(row["expires_at"]) <= utc_now():
        return "APPROVAL_EXPIRED", "the human approval has expired; a new review is required"
    return None

