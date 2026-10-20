"""Deterministic To-do App command console (Build Guide 02.4, Architecture A8).

Grammar (nothing else is accepted):

    add <title>        persist one task with a server-generated ID
    list               stored IDs, titles and completion flags
    complete <ID>      resolve the active artifact by hash and apply it
    status             active artifact hash, release revision, business health

The parser cannot execute code, select endpoints, run SQL or carry credentials.

``complete`` (Phase 03) resolves the active artifact by content hash, verifies
the stored bytes, takes a snapshot of the workspace's task records and their
row revisions, and sends the source plus a COPY of those records to the
separate bounded runner. The runner's result is data: trusted lab code checks
its shape and permits exactly one kind of change (the target task's completed
flag false -> true; nothing added, dropped or edited). The change is committed
only if the active release and every task revision are unchanged since the
snapshot (otherwise 409 REVISION_CONFLICT, nothing written). Candidate source
is never executed in this process.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable

from .candidates import source_text
from .clock import utc_now_iso
from .contract import permitted_change, shape_problems
from .releases import active_drill, app_health, get_active, resolve_active_candidate
from .runner_client import RunnerClient
from .store import LabError, Store

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
        raise LabError(500, "INTERNAL_ERROR", "complete is handled by complete_task (runner path)")
    raise LabError(400, "UNKNOWN_COMMAND", HELP)


_MESSAGES = {
    "FEATURE_UNAVAILABLE": "Task completion is not available in the active version.",
    "TASK_NOT_FOUND": "No task with ID {task_id}; nothing was changed.",
}


def _result(ok: bool, code: str, message: str, **data: Any) -> dict[str, Any]:
    return {"ok": ok, "code": code, "message": message, "data": data}


def complete_task(store: Store, runner: RunnerClient | None, workspace_id: str, task_id: str, *,
                  record: Callable[[sqlite3.Connection, dict[str, Any]], None]) -> dict[str, Any]:
    """Interpret the active artifact for ``complete <ID>`` and commit a permitted result."""
    with store.read() as conn:
        active, cand = resolve_active_candidate(conn, workspace_id)
        artifact = {"candidate_id": cand["candidate_id"], "sha256": cand["sha256"], "origin": cand["origin"],
                    "release_revision": active["release_revision"]}
        drill = active_drill(conn, workspace_id, cand["sha256"]) is not None
        snapshot = _tasks(conn, workspace_id)
        source = source_text(cand)

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        with store.write() as conn:
            record(conn, result)
        return result

    base = {"artifact": artifact, "task_id": task_id, "tasks_changed": 0}
    if drill:
        return finish(_result(False, "COMPLETION_UNAVAILABLE_DRILL",
                              "Completion is temporarily unavailable (instructor incident drill).", **base))
    if runner is None:
        return finish(_result(False, "RUNNER_UNAVAILABLE",
                              "The bounded runner is not configured; nothing was changed.", **base))
    inputs = [{"id": t["id"], "title": t["title"], "completed": t["completed"]} for t in snapshot]
    try:
        doc = runner.evaluate(source=source, source_sha256=cand["sha256"], tasks=inputs, task_id=task_id)
    except LabError as err:
        if err.code != "RUNNER_UNAVAILABLE":
            raise
        return finish(_result(False, "RUNNER_UNAVAILABLE",
                              "The bounded runner is unavailable; nothing was changed.", **base))
    evaluation = {"evaluated_by": doc["runner_version"], "grammar_version": doc.get("grammar_version"),
                  "status": doc["status"], "ops": doc["ops"], "interpreted_sha256": doc["source_sha256"]}
    base["evaluation"] = evaluation
    if doc["status"] == "rejected":
        code = doc["error"]["code"]
        return finish(_result(False, "CANDIDATE_REJECTED",
                              f"The active version was rejected by the runner's validator ({code}); nothing was changed.",
                              **base, candidate_error=doc["error"]))
    if doc["status"] == "error":
        code = doc["error"]["code"]
        return finish(_result(False, "CANDIDATE_FAILED",
                              f"The active version failed during bounded evaluation ({code}); nothing was changed.",
                              **base, candidate_error=doc["error"]))
    result = doc["result"]
    problems = shape_problems(result)
    if problems:
        return finish(_result(False, "CANDIDATE_RESULT_INVALID",
                              "The active version returned a malformed result; nothing was changed.",
                              **base, problems=problems[:5]))
    permitted, reason, completes = permitted_change(inputs, result, task_id)
    if not permitted:
        return finish(_result(False, "CANDIDATE_RESULT_REJECTED",
                              f"The active version's result was not accepted ({reason}); nothing was changed.",
                              **base, candidate_code=result["code"]))
    code = result["code"]
    if not completes:
        if result["ok"]:
            message = f"{task_id} is already complete; nothing was changed."
        else:
            message = _MESSAGES.get(code, f"The active version returned {code}; nothing was changed.").format(
                task_id=task_id)
        return finish(_result(bool(result["ok"]), code, message, **base))

    target = next(t for t in snapshot if t["id"] == task_id)
    with store.write() as conn:
        current_active = get_active(conn, workspace_id)
        if (current_active["active_sha256"] != cand["sha256"]
                or current_active["release_revision"] != active["release_revision"]):
            raise LabError(409, "REVISION_CONFLICT", "the active artifact changed during evaluation; nothing was changed",
                           {"audit": {"task_id": task_id}})
        if active_drill(conn, workspace_id, cand["sha256"]) is not None:
            raise LabError(409, "REVISION_CONFLICT", "an incident drill started during evaluation; nothing was changed",
                           {"audit": {"task_id": task_id}})
        now_rows = [(t["id"], t["revision"]) for t in _tasks(conn, workspace_id)]
        if now_rows != [(t["id"], t["revision"]) for t in snapshot]:
            raise LabError(409, "REVISION_CONFLICT", "task records changed during evaluation; nothing was changed",
                           {"audit": {"task_id": task_id}})
        cur = conn.execute(
            "UPDATE tasks SET completed = 1, revision = revision + 1, updated_at = ?"
            " WHERE workspace_id = ? AND task_id = ? AND revision = ? AND completed = 0",
            (utc_now_iso(), workspace_id, task_id, target["revision"]))
        if cur.rowcount != 1:
            raise LabError(409, "REVISION_CONFLICT", "task record changed during evaluation; nothing was changed")
        updated = {"id": task_id, "title": target["title"], "completed": True, "revision": target["revision"] + 1}
        out = _result(True, code, f"Completed {task_id}: {target['title']}",
                      **{**base, "tasks_changed": 1, "task": updated})
        record(conn, out)
    return out
