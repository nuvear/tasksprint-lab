"""Server-issued run contexts and fixed budgets (Architecture A8 POST /v1/runs, A9).

Run IDs are generated here; the role comes from the token, the workspace from
the trusted header, budgets from server constants. A caller cannot select
authority or budgets, and a new root run does not inherit a parent's spent budget
unless it is created as that parent's child. Full harness enforcement (tool-level
counting inside Langflow, no-progress detection) is Phase 07; the instructor stop flag
(Phase 09) refuses new runs and every run-bound action/commit while it is set.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from .clock import parse_iso, to_iso, utc_now
from .config import (RUN_DEADLINE_PARENT_S, RUN_DEADLINE_SPECIALIST_S, RUN_MAX_DEPTH, RUN_TREE_MAX_ACTIONS,
                     run_max_actions)
from .store import LabError


def run_view(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in ("run_id", "workspace_id", "generation", "role", "session_namespace", "parent_run_id",
                                "root_run_id", "depth", "max_actions", "actions_used", "tree_max_actions",
                                "deadline_at", "status", "created_at")}


def create_run(conn: sqlite3.Connection, *, workspace: sqlite3.Row, role: str, conversation_id: str,
               parent_run_id: str | None) -> dict[str, Any]:
    if workspace["stopped"]:
        raise LabError(409, "WORKSPACE_STOPPED", "the instructor stop flag is set; no new run can start")
    sweep_expired(conn, workspace["workspace_id"])
    now = utc_now()
    run_id = "run_" + secrets.token_hex(16)
    if parent_run_id is None:
        depth, root, tree_max = 0, run_id, RUN_TREE_MAX_ACTIONS
        deadline = now + timedelta(seconds=RUN_DEADLINE_PARENT_S if role == "coordinator" else RUN_DEADLINE_SPECIALIST_S)
    else:
        parent = conn.execute("SELECT * FROM runs WHERE run_id = ?", (parent_run_id,)).fetchone()
        if parent is None or parent["workspace_id"] != workspace["workspace_id"]:
            raise LabError(404, "PARENT_RUN_NOT_FOUND", "parent run does not exist in this workspace")
        _require_live(conn, parent, workspace)
        if parent["depth"] + 1 > RUN_MAX_DEPTH:
            raise LabError(409, "DELEGATION_DEPTH_EXCEEDED", f"delegation depth is limited to {RUN_MAX_DEPTH}")
        depth, root, tree_max = parent["depth"] + 1, parent["root_run_id"], parent["tree_max_actions"]
        deadline = min(now + timedelta(seconds=RUN_DEADLINE_SPECIALIST_S), parse_iso(parent["deadline_at"]))
    conn.execute(
        "INSERT INTO runs(run_id, workspace_id, generation, role, session_namespace, parent_run_id, root_run_id, depth,"
        " max_actions, actions_used, tree_max_actions, tree_actions_used, deadline_at, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,0,?,0,?,'active',?,?)",
        (run_id, workspace["workspace_id"], workspace["generation"], role,
         f"{workspace['workspace_id']}:{role}:{conversation_id}", parent_run_id, root, depth, run_max_actions(role),
         tree_max, to_iso(deadline), to_iso(now), to_iso(now)),
    )
    return run_view(conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())


def sweep_expired(conn: sqlite3.Connection, workspace_id: str) -> int:
    """Mark this workspace's active runs whose deadline has passed as ``expired`` (Phase 10, cosmetic).

    Expiry was always enforced at use (``_require_live``); this only makes stored status truthful.
    Called inside write transactions (new run, reset, stop). Returns the number of runs marked.
    """
    now = utc_now()
    stale = [r["run_id"] for r in conn.execute("SELECT run_id, deadline_at FROM runs WHERE workspace_id = ? AND"
                                               " status = 'active'", (workspace_id,)) if parse_iso(r["deadline_at"]) <= now]
    for run_id in stale:
        conn.execute("UPDATE runs SET status = 'expired', updated_at = ? WHERE run_id = ? AND status = 'active'",
                     (to_iso(now), run_id))
    return len(stale)


def _require_live(conn: sqlite3.Connection, run: sqlite3.Row, workspace: sqlite3.Row) -> None:
    if workspace["stopped"]:
        raise LabError(409, "WORKSPACE_STOPPED", "the instructor stop flag is set for this workspace")
    if run["generation"] != workspace["generation"]:
        raise LabError(409, "RUN_STALE_GENERATION", "run belongs to an earlier workspace generation")
    if run["status"] == "expired":
        raise LabError(409, "RUN_EXPIRED", "run deadline has passed")
    if run["status"] != "active":
        raise LabError(409, "RUN_NOT_ACTIVE", f"run is {run['status']}")
    if parse_iso(run["deadline_at"]) <= utc_now():
        raise LabError(409, "RUN_EXPIRED", "run deadline has passed")


def require_live_at_commit(conn: sqlite3.Connection, *, run_id: str, role: str, workspace_id: str) -> None:
    """Re-check the run inside the write transaction, immediately before a mutation commits (A9).

    ``consume_action`` admits an action when it starts; a long operation (a protected test run,
    a slow model turn) can outlive the run's deadline, or the run can be stopped/cancelled or the
    workspace reset meanwhile. Calling this inside the same ``BEGIN IMMEDIATE`` transaction as
    the write makes such a late result fail instead of committing. Spends no budget.
    """
    ws = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
    if ws is None or not ws["active"]:
        raise LabError(404, "WORKSPACE_NOT_FOUND", "workspace does not exist or is inactive")
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None or run["workspace_id"] != workspace_id or run["role"] != role:
        raise LabError(403, "RUN_NOT_BOUND", "run is not bound to this credential and workspace")
    try:
        _require_live(conn, run, ws)
    except LabError as err:
        raise LabError(err.status, err.code, err.message + " (re-checked at commit; nothing was written)",
                       {"audit": {"checked": "at_commit"}}) from None


def consume_action(conn: sqlite3.Connection, *, run_id: str, role: str, workspace: sqlite3.Row) -> sqlite3.Row:
    """Validate a run for this caller and count one tool action against its budgets."""
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None or run["workspace_id"] != workspace["workspace_id"] or run["role"] != role:
        raise LabError(403, "RUN_NOT_BOUND", "run is not bound to this credential and workspace")
    _require_live(conn, run, workspace)
    root = conn.execute("SELECT tree_actions_used FROM runs WHERE run_id = ?", (run["root_run_id"],)).fetchone()
    if run["actions_used"] >= run["max_actions"] or root["tree_actions_used"] >= run["tree_max_actions"]:
        raise LabError(429, "BUDGET_EXHAUSTED", "run action budget is exhausted; stop and escalate")
    now = to_iso(utc_now())
    conn.execute("UPDATE runs SET actions_used = actions_used + 1, updated_at = ? WHERE run_id = ?", (now, run_id))
    conn.execute("UPDATE runs SET tree_actions_used = tree_actions_used + 1, updated_at = ? WHERE run_id = ?",
                 (now, run["root_run_id"]))
    return conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
