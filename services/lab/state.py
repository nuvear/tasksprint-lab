"""Canonical sprint/story state and the single controlled writer (A5).

The stage machine is enforced here, not in prompts. Each story row carries a
revision; writes must quote the revision they read (optimistic concurrency).
Evidence preconditions are checked against trusted records (test_runs written
by trusted testing code in Phase 03), never against a caller's boolean.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .audit import record_event
from .candidates import get_candidate, verify_integrity
from .clock import utc_now_iso
from .store import LabError

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "PLANNED": frozenset({"IN_DEVELOPMENT"}),
    "IN_DEVELOPMENT": frozenset({"IN_QA"}),
    "IN_QA": frozenset({"CHANGES_REQUESTED", "APP_VERIFIED"}),
    "CHANGES_REQUESTED": frozenset({"IN_DEVELOPMENT"}),
    "APP_VERIFIED": frozenset({"READY_FOR_REVIEW"}),
    "READY_FOR_REVIEW": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
}
MAX_REPAIRS = 1  # one automatic repair for the demonstration story, then escalate
MAX_STORIES_PER_WORKSPACE = 10


def story_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "story_id": row["story_id"],
        "sprint_id": row["sprint_id"],
        "title": row["title"],
        "narrative": row["narrative"],
        "criteria": json.loads(row["criteria_json"]),
        "criteria_version": row["criteria_version"],
        "scope_confirmed": bool(row["scope_confirmed"]),
        "stage": row["stage"],
        "candidate_id": row["candidate_id"],
        "repair_count": row["repair_count"],
        "evidence_refs": json.loads(row["evidence_json"]),
        "revision": row["revision"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_story(conn: sqlite3.Connection, workspace_id: str, story_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM stories WHERE workspace_id = ? AND story_id = ?", (workspace_id, story_id)).fetchone()
    if row is None:
        raise LabError(404, "STORY_NOT_FOUND", "story does not exist in this workspace")
    return row


def read_state(conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
    ws = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
    sprint = conn.execute(
        "SELECT * FROM sprints WHERE workspace_id = ? ORDER BY created_at, sprint_id LIMIT 1", (workspace_id,)
    ).fetchone()
    stories = conn.execute("SELECT * FROM stories WHERE workspace_id = ? ORDER BY story_id", (workspace_id,)).fetchall()
    active = conn.execute("SELECT * FROM active_releases WHERE workspace_id = ?", (workspace_id,)).fetchone()
    return {
        "record_type": "canonical_sprint_state",
        "workspace": {"workspace_id": ws["workspace_id"], "generation": ws["generation"],
                      "environment": ws["environment"], "revision": ws["revision"]},
        "sprint": None if sprint is None else {"sprint_id": sprint["sprint_id"], "goal": sprint["goal"],
                                               "revision": sprint["revision"]},
        "stories": [story_view(s) for s in stories],
        "release": None if active is None else {"active_candidate_id": active["active_candidate_id"],
                                                "active_sha256": active["active_sha256"],
                                                "release_revision": active["release_revision"]},
    }


class StateWriter:
    """The one controlled writer for stories. Call inside ``Store.write()``."""

    def __init__(self, conn: sqlite3.Connection, request_id: str, actor_role: str, run_id: str | None = None):
        self.conn = conn
        self.request_id = request_id
        self.actor_role = actor_role
        self.run_id = run_id

    def _event(self, workspace_id: str, action: str, outcome: str, details: dict[str, Any]) -> None:
        record_event(self.conn, request_id=self.request_id, actor_role=self.actor_role, action=action,
                     outcome=outcome, workspace_id=workspace_id, run_id=self.run_id, details=details)

    def create_story(self, workspace_id: str, *, title: str, narrative: str, criteria: list[str],
                     evidence_refs: list[str]) -> dict[str, Any]:
        count = self.conn.execute("SELECT COUNT(*) AS n FROM stories WHERE workspace_id = ?", (workspace_id,)).fetchone()["n"]
        if count >= MAX_STORIES_PER_WORKSPACE:
            raise LabError(409, "STORY_LIMIT", "story limit reached for this workspace")
        sprint = self.conn.execute(
            "SELECT sprint_id FROM sprints WHERE workspace_id = ? ORDER BY created_at, sprint_id LIMIT 1", (workspace_id,)
        ).fetchone()
        if sprint is None:
            raise LabError(409, "NO_SPRINT", "workspace has no sprint")
        story_id = f"ST-{count + 1:03d}"
        now = utc_now_iso()
        self.conn.execute(
            "INSERT INTO stories(workspace_id, story_id, sprint_id, title, narrative, criteria_json, criteria_version,"
            " scope_confirmed, stage, candidate_id, repair_count, evidence_json, revision, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,1,0,'PLANNED',NULL,0,?,1,?,?,?)",
            (workspace_id, story_id, sprint["sprint_id"], title, narrative, json.dumps(criteria, ensure_ascii=False),
             json.dumps(evidence_refs), self.actor_role, now, now),
        )
        self._event(workspace_id, "story.create", "ok", {"story_id": story_id, "criteria_count": len(criteria)})
        return story_view(get_story(self.conn, workspace_id, story_id))

    def confirm_scope(self, workspace_id: str, story_id: str, expected_revision: int) -> dict[str, Any]:
        """Trusted human-only path (instructor/Product Owner control, wired in a later phase)."""
        row = get_story(self.conn, workspace_id, story_id)
        self._check_revision(workspace_id, row, expected_revision)
        self._update(workspace_id, story_id, expected_revision, scope_confirmed=1)
        self._event(workspace_id, "story.scope_confirmed", "ok", {"story_id": story_id})
        return story_view(get_story(self.conn, workspace_id, story_id))

    def transition(self, workspace_id: str, *, story_id: str, to_stage: str, expected_revision: int,
                   candidate_id: str | None = None, test_run_id: str | None = None) -> dict[str, Any]:
        row = get_story(self.conn, workspace_id, story_id)
        self._check_revision(workspace_id, row, expected_revision)
        from_stage = row["stage"]
        if to_stage not in LEGAL_TRANSITIONS.get(from_stage, frozenset()):
            self._deny(workspace_id, story_id, from_stage, to_stage, "ILLEGAL_TRANSITION",
                       f"{from_stage} -> {to_stage} is not a legal transition")

        changes: dict[str, Any] = {"stage": to_stage}
        evidence = json.loads(row["evidence_json"])
        if from_stage == "PLANNED" and not row["scope_confirmed"]:
            self._deny(workspace_id, story_id, from_stage, to_stage, "SCOPE_NOT_CONFIRMED",
                       "human Product Owner scope confirmation is required first")
        if to_stage == "IN_QA":
            if candidate_id is None:
                self._deny(workspace_id, story_id, from_stage, to_stage, "CANDIDATE_REQUIRED", "candidate_id is required")
            cand = get_candidate(self.conn, workspace_id, candidate_id)
            if cand is None or not verify_integrity(cand):
                self._deny(workspace_id, story_id, from_stage, to_stage, "UNKNOWN_CANDIDATE",
                           "candidate does not exist in this workspace")
            changes["candidate_id"] = candidate_id
        elif candidate_id is not None:
            raise LabError(422, "UNEXPECTED_FIELD", "candidate_id is only accepted when entering IN_QA")
        if from_stage == "IN_QA":
            required = "fail" if to_stage == "CHANGES_REQUESTED" else "pass"
            run = None
            if test_run_id is not None:
                cand = get_candidate(self.conn, workspace_id, row["candidate_id"])
                run = self.conn.execute(
                    "SELECT * FROM test_runs WHERE test_run_id = ? AND workspace_id = ? AND candidate_sha256 = ?",
                    (test_run_id, workspace_id, cand["sha256"] if cand else ""),
                ).fetchone()
            if run is None or run["outcome"] != required:
                self._deny(workspace_id, story_id, from_stage, to_stage, "EVIDENCE_REQUIRED",
                           f"a trusted test run with outcome '{required}' for this exact candidate is required")
            evidence.append(test_run_id)
        elif test_run_id is not None:
            raise LabError(422, "UNEXPECTED_FIELD", "test_run_id is only accepted when leaving IN_QA")
        if from_stage == "CHANGES_REQUESTED":
            if row["repair_count"] >= MAX_REPAIRS:
                self._deny(workspace_id, story_id, from_stage, to_stage, "REPAIR_BUDGET_EXHAUSTED",
                           "the single automatic repair has been used; escalate to the human")
            changes["repair_count"] = row["repair_count"] + 1
        if to_stage == "CLOSED":
            # Story acceptance is a human decision recorded by the protected control flow (Phase 09).
            self._deny(workspace_id, story_id, from_stage, to_stage, "HUMAN_REVIEW_REQUIRED",
                       "closing requires a recorded human review decision")
        changes["evidence_json"] = json.dumps(evidence[-10:])
        self._update(workspace_id, story_id, expected_revision, **changes)
        self._event(workspace_id, "story.transition", "ok",
                    {"story_id": story_id, "from": from_stage, "to": to_stage, "revision": expected_revision + 1})
        return story_view(get_story(self.conn, workspace_id, story_id))

    # -- internals
    def _check_revision(self, workspace_id: str, row: sqlite3.Row, expected: int) -> None:
        if row["revision"] != expected:
            raise LabError(409, "REVISION_CONFLICT", "story revision has changed; re-read state and retry",
                           {"current_revision": row["revision"],
                            "audit": {"story_id": row["story_id"], "expected": expected, "current": row["revision"]}})

    def _deny(self, workspace_id: str, story_id: str, from_stage: str, to_stage: str, code: str, message: str) -> None:
        # The refused write rolls back; main.py records the denial event in a
        # separate transaction from the ``audit`` details so the evidence persists.
        raise LabError(409, code, message, {"audit": {"story_id": story_id, "from": from_stage, "to": to_stage}})

    def _update(self, workspace_id: str, story_id: str, expected_revision: int, **changes: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in changes)
        cur = self.conn.execute(
            f"UPDATE stories SET {cols}, revision = revision + 1, updated_at = ?"
            " WHERE workspace_id = ? AND story_id = ? AND revision = ?",
            (*changes.values(), utc_now_iso(), workspace_id, story_id, expected_revision),
        )
        if cur.rowcount != 1:
            raise LabError(409, "REVISION_CONFLICT", "story revision has changed; re-read state and retry")
