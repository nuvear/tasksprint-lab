"""Instructor-only allowlisted actions (Architecture A8 /v1/instructor/actions, A9, A12).

Phase 02: ``seed``, ``reset_preview``. Phase 03: ``load_fixture`` (allowlisted, labelled
faulty/reference fixtures registered as immutable candidates with fixed provenance).
Phase 09: ``confirm_scope`` (the human Product Owner's scope confirmation, recorded via the
controlled story writer), ``drill_enable`` / ``drill_disable`` (``completion_unavailable``
for the ACTIVE candidate only, short expiry), ``stop`` / ``resume`` (kill switch: cancels the
workspace's active runs so late results cannot commit; new runs, plans and executions are
refused while stopped) and ``reset_confirm`` (A12: exports the workspace's evidence, clears
drill/stop flags, cancels pending runs/plans/approvals, reseeds the two known tasks, restores
v0 and advances the generation). Only designated workspaces from
TASKSPRINT_ALLOWED_WORKSPACES can be targeted, only with demo mode enabled, and nothing
here touches another workspace, Langflow, or the hosting services.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from .audit import record_event
from .candidates import get_candidate, put_candidate, sha256_hex, verify_integrity
from .clock import parse_iso, to_iso, utc_now, utc_now_iso
from .config import Settings
from .releases import app_health, get_active, record_seed_release
from .state import StateWriter, get_story
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
        raise LabError(409, "ALREADY_SEEDED", "workspace already exists; use reset_preview / reset_confirm")
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


FIXTURES = {
    "faulty_delete": ("faulty_delete.py", "fixture-faulty", "FIXTURE: known faulty (deletes the completed task)"),
    "reference_complete": ("reference_complete.py", "fixture-reference", "FIXTURE: instructor-only reference"),
}


def load_fixture(conn: sqlite3.Connection, settings: Settings, workspace_id: str, fixture: str | None,
                 request_id: str) -> dict[str, Any]:
    _designated(settings, workspace_id)
    if fixture not in FIXTURES:
        raise LabError(422, "UNKNOWN_FIXTURE", "fixture must be one of: " + ", ".join(sorted(FIXTURES)))
    if get_workspace(conn, workspace_id) is None:
        raise LabError(404, "WORKSPACE_NOT_FOUND", "seed the workspace first")
    filename, origin, label = FIXTURES[fixture]
    path = Path(settings.fixtures_dir) / filename
    if not path.is_file():
        raise LabError(500, "FIXTURE_MISSING", "fixture file is missing")
    view, created = put_candidate(conn, workspace_id=workspace_id, source=path.read_bytes(), origin=origin,
                                  author_role="instructor", label=label)
    record_event(conn, request_id=request_id, actor_role="instructor", action="instructor.load_fixture",
                 outcome="ok" if created else "duplicate", workspace_id=workspace_id,
                 details={"fixture": fixture, "candidate_id": view["candidate_id"], "sha256": view["sha256"],
                          "origin": origin})
    return {"action": "load_fixture", "workspace_id": workspace_id, "fixture": fixture, "created": created,
            "candidate": view}


PREVIEW_TABLES = ("tasks", "stories", "memories", "candidates", "runs", "events", "test_runs", "release_plans",
                  "approvals", "releases", "drills", "a2a_exchanges", "baseline_smoke_runs")
DRILL_MAX_TTL_MIN = 30


def _existing(conn: sqlite3.Connection, settings: Settings, workspace_id: str) -> sqlite3.Row:
    _designated(settings, workspace_id)
    ws = get_workspace(conn, workspace_id)
    if ws is None:
        raise LabError(404, "WORKSPACE_NOT_FOUND", "seed the workspace first")
    return ws


def _counts(conn: sqlite3.Connection, workspace_id: str) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE workspace_id = ?", (workspace_id,)).fetchone()["n"]
            for t in PREVIEW_TABLES}


def _pending(conn: sqlite3.Connection, workspace_id: str) -> dict[str, list[str]]:
    return {
        "active_runs": [r[0] for r in conn.execute(
            "SELECT run_id FROM runs WHERE workspace_id = ? AND status = 'active'", (workspace_id,))],
        "open_plans": [r[0] for r in conn.execute(
            "SELECT p.plan_id FROM release_plans p JOIN release_plan_states s ON s.plan_id = p.plan_id WHERE"
            " p.workspace_id = ? AND s.state IN ('PLANNED','AWAITING_APPROVAL','APPROVED')", (workspace_id,))],
        "active_approvals": [r[0] for r in conn.execute(
            "SELECT approval_id FROM approvals WHERE workspace_id = ? AND status = 'active'", (workspace_id,))],
        "enabled_drills": [r[0] for r in conn.execute(
            "SELECT drill_id FROM drills WHERE workspace_id = ? AND enabled = 1", (workspace_id,))],
    }


def reset_preview(conn: sqlite3.Connection, settings: Settings, workspace_id: str) -> dict[str, Any]:
    _designated(settings, workspace_id)
    ws = get_workspace(conn, workspace_id)
    if ws is None:
        return {"action": "reset_preview", "workspace_id": workspace_id, "exists": False, "mutation": "none"}
    active = get_active(conn, workspace_id)
    return {
        "action": "reset_preview",
        "workspace_id": workspace_id,
        "exists": True,
        "generation": ws["generation"],
        "stopped": bool(ws["stopped"]),
        "active_is_baseline": active["active_sha256"] == ws["baseline_sha256"],
        "release_revision": active["release_revision"],
        "counts": _counts(conn, workspace_id),
        "pending": _pending(conn, workspace_id),
        "would_do": [
            "export this workspace's evidence (append-only export record)", "clear drill/stop flags",
            "cancel active runs, open plans and unused approvals", "delete stories and saved preferences",
            "reseed the two known tasks", "restore v0 as active artifact (if it is not active)",
            f"advance generation to {ws['generation'] + 1}",
            "keep append-only evidence (candidates, test runs, plans, releases, events) and every other workspace",
        ],
        "confirm_with": {"action": "reset_confirm", "workspace_id": workspace_id, "confirm": workspace_id},
        "mutation": "none (preview only)",
    }


def reset_confirm(conn: sqlite3.Connection, settings: Settings, workspace_id: str, confirm: str | None,
                  request_id: str) -> dict[str, Any]:
    ws = _existing(conn, settings, workspace_id)
    if confirm != workspace_id:
        raise LabError(422, "CONFIRMATION_REQUIRED", "reset_confirm needs confirm equal to the workspace id")
    now = utc_now_iso()
    pending = _pending(conn, workspace_id)
    counts_before = _counts(conn, workspace_id)
    # 1. export this workspace's evidence (only this workspace's rows)
    export: dict[str, Any] = {"workspace_id": workspace_id, "generation": ws["generation"], "exported_at": now,
                              "counts": counts_before}
    for table, key in (("tasks", "task_id"), ("stories", "story_id"), ("memories", "pref_key"),
                       ("runs", "run_id"), ("release_plans", "plan_id"), ("approvals", "approval_id"),
                       ("releases", "release_id"), ("drills", "drill_id"), ("test_runs", "test_run_id"),
                       ("baseline_smoke_runs", "smoke_id"), ("a2a_exchanges", "exchange_id"), ("events", "event_id")):
        cols = "*" if table not in ("test_runs",) else "test_run_id, candidate_id, candidate_sha256, suite_sha256, outcome, created_at"
        export[table] = [dict(r) for r in conn.execute(f"SELECT {cols} FROM {table} WHERE workspace_id = ? ORDER BY"
                                                       f" {key}", (workspace_id,))]
    export["release_plan_states"] = [dict(r) for r in conn.execute(
        "SELECT s.* FROM release_plan_states s JOIN release_plans p ON p.plan_id = s.plan_id WHERE p.workspace_id = ?"
        " ORDER BY s.plan_id", (workspace_id,))]
    export_json = json.dumps(export, sort_keys=True, default=str)
    export_sha = hashlib.sha256(export_json.encode()).hexdigest()
    export_id = "exp_" + secrets.token_hex(12)
    conn.execute("INSERT INTO workspace_exports(export_id, workspace_id, generation, export_json, export_sha256,"
                 " created_at) VALUES (?,?,?,?,?,?)", (export_id, workspace_id, ws["generation"], export_json,
                                                       export_sha, now))
    # 2. clear drills and the stop flag; cancel pending work of the old generation
    conn.execute("UPDATE drills SET enabled = 0 WHERE workspace_id = ? AND enabled = 1", (workspace_id,))
    conn.execute("UPDATE runs SET status = 'cancelled', updated_at = ? WHERE workspace_id = ? AND status = 'active'",
                 (now, workspace_id))
    for plan_id in pending["open_plans"]:
        conn.execute("UPDATE release_plan_states SET state = 'EXPIRED', revision = revision + 1, updated_at = ?"
                     " WHERE plan_id = ?", (now, plan_id))
    conn.execute("UPDATE approvals SET status = 'cancelled' WHERE workspace_id = ? AND status = 'active'",
                 (workspace_id,))
    # 3. canonical starting records: no stories/preferences, the two known tasks
    for table in ("stories", "memories", "tasks"):
        conn.execute(f"DELETE FROM {table} WHERE workspace_id = ?", (workspace_id,))
    for task_id, title in SEED_TASKS:
        conn.execute("INSERT INTO tasks(workspace_id, task_id, title, completed, revision, created_at, updated_at)"
                     " VALUES (?,?,?,0,1,?,?)", (workspace_id, task_id, title, now, now))
    # 4. restore v0 (append a release record; release revisions never go backwards)
    active = get_active(conn, workspace_id)
    restored = None
    if active["active_sha256"] != ws["baseline_sha256"]:
        starter = conn.execute("SELECT * FROM candidates WHERE workspace_id = ? AND sha256 = ?",
                               (workspace_id, ws["baseline_sha256"])).fetchone()
        if starter is None or not verify_integrity(starter):
            raise LabError(500, "ARTIFACT_INTEGRITY_ERROR", "the recorded baseline artifact is missing or corrupt")
        rev = active["release_revision"] + 1
        receipt = {"operation": "reset_restore_v0", "candidate_id": starter["candidate_id"],
                   "sha256": starter["sha256"], "previous_sha256": active["active_sha256"], "release_revision": rev,
                   "request_id": request_id, "baseline": True, "export_id": export_id}
        conn.execute("UPDATE active_releases SET active_candidate_id = ?, active_sha256 = ?, previous_sha256 = ?,"
                     " release_revision = ?, updated_at = ? WHERE workspace_id = ?",
                     (starter["candidate_id"], starter["sha256"], active["active_sha256"], rev, now, workspace_id))
        restored = "rel_" + secrets.token_hex(12)
        conn.execute("INSERT INTO releases(release_id, workspace_id, release_revision, operation, active_sha256,"
                     " previous_sha256, plan_id, action_id, receipt_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (restored, workspace_id, rev, "seed", starter["sha256"], active["active_sha256"], None, None,
                      json.dumps(receipt, sort_keys=True), now))
    # 5. advance the generation (old runs/plans/approvals can never act on the new session)
    new_gen = ws["generation"] + 1
    conn.execute("UPDATE workspaces SET generation = ?, next_task_seq = ?, stopped = 0, stopped_at = NULL,"
                 " revision = revision + 1, updated_at = ? WHERE workspace_id = ?",
                 (new_gen, len(SEED_TASKS) + 1, now, workspace_id))
    event_id = record_event(conn, request_id=request_id, actor_role="instructor", action="instructor.reset_confirm",
                            outcome="ok", workspace_id=workspace_id,
                            details={"export_id": export_id, "export_sha256": export_sha, "from_generation":
                                     ws["generation"], "to_generation": new_gen,
                                     "cancelled_runs": len(pending["active_runs"]),
                                     "cancelled_plans": pending["open_plans"][:20],
                                     "cancelled_approvals": pending["active_approvals"][:20],
                                     "restored_release_id": restored})
    return {"action": "reset_confirm", "workspace_id": workspace_id, "generation": new_gen,
            "export": {"export_id": export_id, "export_sha256": export_sha, "counts": counts_before},
            "cancelled": pending, "restored_v0_release_id": restored, "tasks_seeded": [t for t, _ in SEED_TASKS],
            "event_id": event_id,
            "kept": "append-only evidence of this workspace; every other workspace and all Langflow data"}


def confirm_scope(conn: sqlite3.Connection, settings: Settings, workspace_id: str, story_id: str | None,
                  expected_revision: int | None, request_id: str) -> dict[str, Any]:
    _existing(conn, settings, workspace_id)
    if story_id is None:
        raise LabError(422, "STORY_REQUIRED", "confirm_scope needs story_id")
    row = get_story(conn, workspace_id, story_id)
    if row["scope_confirmed"]:
        raise LabError(409, "SCOPE_ALREADY_CONFIRMED", "scope is already confirmed for this story",
                       {"audit": {"story_id": story_id}})
    if row["stage"] != "PLANNED":
        raise LabError(409, "SCOPE_NOT_CONFIRMABLE", f"story stage is {row['stage']}", {"audit": {"story_id": story_id}})
    rev = row["revision"] if expected_revision is None else expected_revision
    story = StateWriter(conn, request_id, "instructor").confirm_scope(workspace_id, story_id, rev)
    return {"action": "confirm_scope", "workspace_id": workspace_id, "story": story,
            "confirmed_criteria_version": story["criteria_version"],
            "note": "Human Product Owner scope confirmation recorded by the protected control. One automatic repair "
                    "cycle remains enforced by repair_count on this story."}


def drill(conn: sqlite3.Connection, settings: Settings, workspace_id: str, enable: bool, fault_type: str | None,
          candidate_id: str | None, ttl_minutes: int | None, request_id: str) -> dict[str, Any]:
    _existing(conn, settings, workspace_id)
    if fault_type != "completion_unavailable" or candidate_id is None:
        raise LabError(422, "DRILL_ARGUMENTS", "drills need fault_type completion_unavailable and candidate_id")
    cand = get_candidate(conn, workspace_id, candidate_id)
    if cand is None:
        raise LabError(404, "CANDIDATE_NOT_FOUND", "candidate does not exist in this workspace")
    now = utc_now()
    if enable:
        active = get_active(conn, workspace_id)
        if active["active_candidate_id"] != candidate_id:
            raise LabError(409, "DRILL_TARGET_NOT_ACTIVE", "a drill may target only the active candidate",
                           {"audit": {"candidate_id": candidate_id}})
        ttl = ttl_minutes or 10
        if not 1 <= ttl <= DRILL_MAX_TTL_MIN:
            raise LabError(422, "DRILL_TTL", f"ttl_minutes must be 1..{DRILL_MAX_TTL_MIN}")
        existing = [r for r in conn.execute("SELECT * FROM drills WHERE workspace_id = ? AND candidate_sha256 = ? AND"
                                            " enabled = 1", (workspace_id, cand["sha256"]))
                    if parse_iso(r["expires_at"]) > now]
        if existing:
            drill_id, created, expires = existing[0]["drill_id"], False, existing[0]["expires_at"]
        else:
            drill_id, created, expires = "drl_" + secrets.token_hex(12), True, to_iso(now + timedelta(minutes=ttl))
            conn.execute("INSERT INTO drills(drill_id, workspace_id, fault_type, candidate_sha256, enabled, expires_at,"
                         " created_by, created_at) VALUES (?,?,?,?,1,?,?,?)",
                         (drill_id, workspace_id, fault_type, cand["sha256"], expires, "instructor", to_iso(now)))
        record_event(conn, request_id=request_id, actor_role="instructor", action="instructor.drill_enable",
                     outcome="ok" if created else "duplicate", workspace_id=workspace_id,
                     details={"drill_id": drill_id, "fault_type": fault_type, "candidate_id": candidate_id,
                              "candidate_sha256": cand["sha256"], "expires_at": expires})
        return {"action": "drill_enable", "workspace_id": workspace_id, "drill_id": drill_id, "created": created,
                "fault_type": fault_type, "candidate_id": candidate_id, "expires_at": expires,
                "app_health": app_health(conn, workspace_id)["status"],
                "note": "Business health is degraded for this candidate only; /healthz liveness stays healthy."}
    cur = conn.execute("UPDATE drills SET enabled = 0 WHERE workspace_id = ? AND candidate_sha256 = ? AND enabled = 1",
                       (workspace_id, cand["sha256"]))
    record_event(conn, request_id=request_id, actor_role="instructor", action="instructor.drill_disable",
                 outcome="ok" if cur.rowcount else "none_enabled", workspace_id=workspace_id,
                 details={"candidate_id": candidate_id, "disabled": cur.rowcount})
    return {"action": "drill_disable", "workspace_id": workspace_id, "candidate_id": candidate_id,
            "disabled": cur.rowcount, "app_health": app_health(conn, workspace_id)["status"]}


def stop(conn: sqlite3.Connection, settings: Settings, workspace_id: str, stopped: bool, reason: str | None,
         request_id: str) -> dict[str, Any]:
    ws = _existing(conn, settings, workspace_id)
    now = utc_now_iso()
    cancelled: list[str] = []
    if stopped:
        cancelled = [r[0] for r in conn.execute("SELECT run_id FROM runs WHERE workspace_id = ? AND status = 'active'",
                                                (workspace_id,))]
        conn.execute("UPDATE runs SET status = 'cancelled', updated_at = ? WHERE workspace_id = ? AND status = 'active'",
                     (now, workspace_id))
        conn.execute("UPDATE workspaces SET stopped = 1, stopped_at = ?, updated_at = ? WHERE workspace_id = ?",
                     (now, now, workspace_id))
    else:
        conn.execute("UPDATE workspaces SET stopped = 0, stopped_at = NULL, updated_at = ? WHERE workspace_id = ?",
                     (now, workspace_id))
    action = "stop" if stopped else "resume"
    was = bool(ws["stopped"])
    event_id = record_event(conn, request_id=request_id, actor_role="instructor", action=f"instructor.{action}",
                            outcome="ok" if was != stopped else "unchanged", workspace_id=workspace_id,
                            details={"cancelled_runs": len(cancelled), "run_ids": cancelled[:20], "reason": reason})
    return {"action": action, "workspace_id": workspace_id, "stopped": stopped, "was_stopped": was,
            "cancelled_runs": cancelled, "event_id": event_id,
            "note": ("Kill switch on: active runs are cancelled, late results cannot commit, and new runs, plans and "
                     "executions are refused until resume. Cancelled runs stay cancelled." if stopped else
                     "Stop flag cleared. Previously cancelled runs stay cancelled; start a new turn.")}
