"""Deterministic To-do App command console (Build Guide 02.4, Architecture A8).

Grammar (nothing else is accepted):

    add <title>        persist one task with a server-generated ID
    list               stored IDs, titles and completion flags
    complete <ID>      resolve the active artifact by hash and apply it
    status             active artifact hash, release revision, business health

The parser cannot execute code, select endpoints, run SQL or carry credentials.
Phase 02 has no runner: for the registered starter baseline, ``complete``
returns FEATURE_UNAVAILABLE (the starter's documented contract, see
instructor/fixtures/starter_v0.py); for any other active artifact it returns
RUNNER_UNAVAILABLE and changes nothing. Phase 03 replaces this with the
bounded interpreter's result. Candidate source is never executed here.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

from .clock import utc_now_iso
from .releases import active_drill, app_health, is_baseline, resolve_active_candidate
from .store import LabError

MAX_COMMAND_CHARS = 200
MAX_TITLE_CHARS = 120
MAX_TASKS = 100
TASK_ID = re.compile(r"^T\d{3,6}$")
HELP = "Commands: add <title> | list | complete <ID> | status"


@dataclass(frozen=True)
class Command:
    verb: str
    arg: str | None = None


def _clean_title(raw: str) -> str:
    title = " ".join(raw.split())
    if not 1 <= len(title) <= MAX_TITLE_CHARS:
        raise LabError(400, "INVALID_TITLE", f"title must be 1..{MAX_TITLE_CHARS} characters")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co") for ch in title):
        raise LabError(400, "INVALID_TITLE", "title contains control or format characters")
    return title


def parse(text: str) -> Command:
    if not isinstance(text, str) or not text.strip():
        raise LabError(400, "UNKNOWN_COMMAND", HELP)
    if len(text) > MAX_COMMAND_CHARS or "\n" in text or "\r" in text:
        raise LabError(400, "COMMAND_TOO_LONG", f"one command per message, at most {MAX_COMMAND_CHARS} characters")
    stripped = text.strip()
    verb, _, rest = stripped.partition(" ")
    verb = verb.lower()
    rest = rest.strip()
    if verb == "add":
        return Command("add", _clean_title(rest))
    if verb in ("list", "status"):
        if rest:
            raise LabError(400, "UNEXPECTED_ARGUMENT", f"'{verb}' takes no argument")
        return Command(verb)
    if verb == "complete":
        if not TASK_ID.match(rest):
            raise LabError(400, "INVALID_TASK_ID", "usage: complete <ID>, for example complete T001")
        return Command("complete", rest)
    raise LabError(400, "UNKNOWN_COMMAND", HELP)


def _tasks(conn: sqlite3.Connection, workspace_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT task_id, title, completed, revision FROM tasks WHERE workspace_id = ? ORDER BY task_id", (workspace_id,)
    ).fetchall()
    return [{"id": r["task_id"], "title": r["title"], "completed": bool(r["completed"]), "revision": r["revision"]}
            for r in rows]


def _format_list(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks."
    return "\n".join(f"{t['id']} [{'x' if t['completed'] else ' '}] {t['title']}" for t in tasks)


def add_task(conn: sqlite3.Connection, workspace_id: str, title: str) -> dict[str, Any]:
    count = conn.execute("SELECT COUNT(*) AS n FROM tasks WHERE workspace_id = ?", (workspace_id,)).fetchone()["n"]
    if count >= MAX_TASKS:
        raise LabError(409, "TASK_LIMIT", f"the demo workspace holds at most {MAX_TASKS} tasks")
    ws = conn.execute("SELECT next_task_seq FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()
    seq = ws["next_task_seq"]
    task_id = f"T{seq:03d}"
    now = utc_now_iso()
    conn.execute("UPDATE workspaces SET next_task_seq = next_task_seq + 1, updated_at = ? WHERE workspace_id = ?",
                 (now, workspace_id))
    conn.execute(
        "INSERT INTO tasks(workspace_id, task_id, title, completed, revision, created_at, updated_at) VALUES (?,?,?,0,1,?,?)",
        (workspace_id, task_id, title, now, now),
    )
    return {"id": task_id, "title": title, "completed": False, "revision": 1}


def execute(conn: sqlite3.Connection, workspace_id: str, command: Command) -> dict[str, Any]:
    """Run one parsed command. Call inside ``Store.write()`` (add) or a read connection."""
    if command.verb == "add":
        task = add_task(conn, workspace_id, command.arg or "")
        return {"ok": True, "code": "ADDED", "message": f"Added {task['id']}: {task['title']}", "data": {"task": task}}
    if command.verb == "list":
        tasks = _tasks(conn, workspace_id)
        return {"ok": True, "code": "LISTED", "message": _format_list(tasks), "data": {"tasks": tasks}}
    if command.verb == "status":
        health = app_health(conn, workspace_id)
        msg = (f"Active artifact {health.get('active_candidate_id')} sha256={health.get('active_sha256')}\n"
               f"Release revision {health.get('release_revision')}; business health: {health['status']}")
        return {"ok": True, "code": "STATUS", "message": msg, "data": health}
    if command.verb == "complete":
        active, cand = resolve_active_candidate(conn, workspace_id)
        artifact = {"candidate_id": cand["candidate_id"], "sha256": cand["sha256"],
                    "release_revision": active["release_revision"]}
        if active_drill(conn, workspace_id, cand["sha256"]) is not None:
            return {"ok": False, "code": "COMPLETION_UNAVAILABLE_DRILL",
                    "message": "Completion is temporarily unavailable (instructor incident drill).",
                    "data": {"artifact": artifact}}
        if is_baseline(conn, workspace_id, cand["sha256"]):
            return {"ok": False, "code": "FEATURE_UNAVAILABLE",
                    "message": "Task completion is not available in the starter version (v0).",
                    "data": {"artifact": artifact, "task_id": command.arg, "tasks_changed": 0,
                             "evaluated_by": "registered starter-baseline contract; candidate source not executed (runner is Phase 03)"}}
        return {"ok": False, "code": "RUNNER_UNAVAILABLE",
                "message": "The bounded candidate runner is not built yet (Phase 03); nothing was changed.",
                "data": {"artifact": artifact, "task_id": command.arg, "tasks_changed": 0}}
    raise LabError(400, "UNKNOWN_COMMAND", HELP)
