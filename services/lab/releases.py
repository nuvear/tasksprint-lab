"""Release records and active-artifact resolution (Architecture A5, A11, A12).

Phase 02 implements the seed release and read paths only. Plans, approvals and
execution (deploy/rollback) are Phases 08-09; nothing here can change the
active artifact except the instructor seed.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from typing import Any

from .candidates import get_candidate, verify_integrity
from .clock import parse_iso, utc_now, utc_now_iso
from .store import LabError


def record_seed_release(conn: sqlite3.Connection, workspace_id: str, candidate: sqlite3.Row, request_id: str) -> dict[str, Any]:
    now = utc_now_iso()
    receipt = {"operation": "seed", "candidate_id": candidate["candidate_id"], "sha256": candidate["sha256"],
               "release_revision": 0, "request_id": request_id, "baseline": True}
    conn.execute(
        "INSERT INTO active_releases(workspace_id, active_candidate_id, active_sha256, previous_sha256, release_revision, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        (workspace_id, candidate["candidate_id"], candidate["sha256"], None, 0, now),
    )
    conn.execute(
        "INSERT INTO releases(release_id, workspace_id, release_revision, operation, active_sha256, previous_sha256, plan_id, action_id, receipt_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("rel_" + secrets.token_hex(12), workspace_id, 0, "seed", candidate["sha256"], None, None, None,
         json.dumps(receipt, sort_keys=True), now),
    )
    return receipt


def get_active(conn: sqlite3.Connection, workspace_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM active_releases WHERE workspace_id = ?", (workspace_id,)).fetchone()
    if row is None:
        raise LabError(409, "NO_ACTIVE_RELEASE", "workspace has no active application artifact")
    return row


def resolve_active_candidate(conn: sqlite3.Connection, workspace_id: str) -> tuple[sqlite3.Row, sqlite3.Row]:
    """Resolve the active artifact by content hash and verify stored bytes (fail closed)."""
    active = get_active(conn, workspace_id)
    cand = get_candidate(conn, workspace_id, active["active_candidate_id"])
    if cand is None or cand["sha256"] != active["active_sha256"] or not verify_integrity(cand):
        raise LabError(500, "ARTIFACT_INTEGRITY_ERROR", "active artifact does not match its recorded hash")
    return active, cand


def release_status(conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
    active, cand = resolve_active_candidate(conn, workspace_id)
    history = conn.execute(
        "SELECT release_id, release_revision, operation, active_sha256, previous_sha256, plan_id, action_id, created_at"
        " FROM releases WHERE workspace_id = ? ORDER BY release_revision DESC LIMIT 20",
        (workspace_id,),
    ).fetchall()
    return {
        "active": {
            "candidate_id": active["active_candidate_id"],
            "sha256": active["active_sha256"],
            "origin": cand["origin"],
            "label": cand["label"],
            "previous_sha256": active["previous_sha256"],
            "release_revision": active["release_revision"],
            "updated_at": active["updated_at"],
        },
        "history": [dict(r) for r in history],
    }


def active_drill(conn: sqlite3.Connection, workspace_id: str, sha256: str) -> sqlite3.Row | None:
    for row in conn.execute(
        "SELECT * FROM drills WHERE workspace_id = ? AND candidate_sha256 = ? AND enabled = 1", (workspace_id, sha256)
    ).fetchall():
        if parse_iso(row["expires_at"]) > utc_now():
            return row
    return None


def is_baseline(conn: sqlite3.Connection, workspace_id: str, sha256: str) -> bool:
    ws = conn.execute("SELECT baseline_sha256 FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
    return ws is not None and ws["baseline_sha256"] == sha256


def app_health(conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
    """Business health of the active version; distinct from /healthz liveness."""
    checks: list[dict[str, Any]] = []
    try:
        active, cand = resolve_active_candidate(conn, workspace_id)
    except LabError as err:
        return {"status": "unhealthy", "checks": [{"name": "active_artifact", "ok": False, "code": err.code}]}
    checks.append({"name": "active_artifact_integrity", "ok": True})
    drill = active_drill(conn, workspace_id, active["active_sha256"])
    checks.append({"name": "no_active_incident_drill", "ok": drill is None})
    baseline = is_baseline(conn, workspace_id, active["active_sha256"])
    return {
        "status": "healthy" if drill is None else "degraded",
        "active_candidate_id": active["active_candidate_id"],
        "active_sha256": active["active_sha256"],
        "release_revision": active["release_revision"],
        "features": {
            "add": "available",
            "list": "available",
            "complete": "FEATURE_UNAVAILABLE (starter baseline)" if baseline else "requires runner (Phase 03)",
        },
        "checks": checks,
    }
