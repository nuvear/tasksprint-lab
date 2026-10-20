"""Instructor-only allowlisted actions (Architecture A8 /v1/instructor/actions, A12).

Phase 02 implements ``seed`` and ``reset_preview``. Fixture loading, drills,
stop and the confirmed reset are later phases. Only designated workspaces from
TASKSPRINT_ALLOWED_WORKSPACES can be targeted, and only with demo mode enabled.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .audit import record_event
from .candidates import put_candidate, sha256_hex
from .clock import utc_now_iso
from .config import Settings
from .releases import record_seed_release
from .store import LabError, get_workspace

STARTER_FILE = "starter_v0.py"
SEED_SPRINT = ("SPRINT-1", "Let participants mark a task complete while keeping it in the list")
SEED_TASKS = (("T001", "Draft workshop agenda"), ("T002", "Book the sprint review room"))


def _designated(settings: Settings, workspace_id: str) -> None:
    if not settings.demo_enabled:
        raise LabError(403, "DEMO_DISABLED", "demo instructor actions are disabled")
    if workspace_id not in settings.allowed_workspaces:
        raise LabError(403, "WORKSPACE_NOT_DESIGNATED", "workspace is not a designated synthetic demo workspace")


def seed(conn: sqlite3.Connection, settings: Settings, workspace_id: str, request_id: str) -> dict[str, Any]:
    _designated(settings, workspace_id)
    if get_workspace(conn, workspace_id) is not None:
        raise LabError(409, "ALREADY_SEEDED", "workspace already exists; use the confirmed reset (later phase)")
    starter_path = Path(settings.fixtures_dir) / STARTER_FILE
    if not starter_path.is_file():
        raise LabError(500, "STARTER_FIXTURE_MISSING", "starter v0 fixture file is missing")
    source = starter_path.read_bytes()
    now = utc_now_iso()
    baseline = sha256_hex(source)
    conn.execute(
        "INSERT INTO workspaces(workspace_id, active, environment, generation, next_task_seq, baseline_sha256, revision, created_at, updated_at)"
        " VALUES (?,1,'demo-production',1,?,?,1,?,?)",
        (workspace_id, len(SEED_TASKS) + 1, baseline, now, now),
    )
    conn.execute("INSERT INTO sprints(workspace_id, sprint_id, goal, revision, created_at) VALUES (?,?,?,1,?)",
                 (workspace_id, SEED_SPRINT[0], SEED_SPRINT[1], now))
    cand_view, _ = put_candidate(conn, workspace_id=workspace_id, source=source, origin="fixture",
                                 author_role="instructor", label="starter-v0")
    cand = conn.execute("SELECT * FROM candidates WHERE workspace_id = ? AND candidate_id = ?",
                        (workspace_id, cand_view["candidate_id"])).fetchone()
    receipt = record_seed_release(conn, workspace_id, cand, request_id)
    for task_id, title in SEED_TASKS:
        conn.execute(
            "INSERT INTO tasks(workspace_id, task_id, title, completed, revision, created_at, updated_at) VALUES (?,?,?,0,1,?,?)",
            (workspace_id, task_id, title, now, now),
        )
    record_event(conn, request_id=request_id, actor_role="instructor", action="instructor.seed", outcome="ok",
                 workspace_id=workspace_id,
                 details={"starter_candidate_id": cand_view["candidate_id"], "starter_sha256": cand_view["sha256"],
                          "tasks": len(SEED_TASKS)})
    return {"action": "seed", "workspace_id": workspace_id, "generation": 1,
            "starter": {**cand_view, "fixture_label": "FIXTURE: known healthy starter baseline"},
            "release": receipt, "tasks_seeded": [t for t, _ in SEED_TASKS], "sprint_id": SEED_SPRINT[0]}


def reset_preview(conn: sqlite3.Connection, settings: Settings, workspace_id: str) -> dict[str, Any]:
    _designated(settings, workspace_id)
    ws = get_workspace(conn, workspace_id)
    if ws is None:
        return {"action": "reset_preview", "workspace_id": workspace_id, "exists": False, "mutation": "none"}
    counts = {}
    for table in ("tasks", "stories", "memories", "candidates", "runs", "events", "test_runs", "release_plans", "drills"):
        counts[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE workspace_id = ?", (workspace_id,)).fetchone()["n"]
    return {
        "action": "reset_preview",
        "workspace_id": workspace_id,
        "exists": True,
        "generation": ws["generation"],
        "counts": counts,
        "would_do": [
            "export this workspace's evidence", "clear drill/stop flags", "cancel pending runs and plans",
            "reseed the two known tasks", "restore v0 as active artifact", f"advance generation to {ws['generation'] + 1}",
        ],
        "mutation": "none (preview only; confirmed reset is implemented in a later phase)",
    }
