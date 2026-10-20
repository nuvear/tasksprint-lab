"""The ``complete(tasks, task_id)`` result contract, checked by trusted lab code.

Used by the protected test suite (to assert) and by the application command
path (to decide what may be committed). The runner's answer is data, never
authority: the lab decides whether a result is well-formed and permissible.
"""
from __future__ import annotations

import re
from typing import Any

RESULT_KEYS = {"ok", "code", "tasks"}
TASK_KEYS = {"id", "title", "completed"}
_CODE = re.compile(r"^[A-Z][A-Z_]{0,39}$")


def shape_problems(result: Any) -> list[str]:
    """Return human-readable contract violations (empty list = well-formed)."""
    if type(result) is not dict:
        return [f"result must be a dict, got {type(result).__name__}"]
    problems: list[str] = []
    if set(result) != RESULT_KEYS:
        problems.append(f"result keys must be exactly {sorted(RESULT_KEYS)}, got {sorted(map(str, result))[:8]}")
    if type(result.get("ok")) is not bool:
        problems.append("ok must be a boolean")
    if type(result.get("code")) is not str or not _CODE.match(result.get("code") or ""):
        problems.append("code must be an UPPER_SNAKE string")
    tasks = result.get("tasks")
    if type(tasks) is not list:
        problems.append("tasks must be a list")
        return problems
    for i, t in enumerate(tasks[:200]):
        if type(t) is not dict or set(t) != TASK_KEYS:
            problems.append(f"tasks[{i}] must be exactly {sorted(TASK_KEYS)}")
            continue
        if type(t["id"]) is not str or type(t["title"]) is not str or type(t["completed"]) is not bool:
            problems.append(f"tasks[{i}] has wrong field types")
    ids = [t.get("id") for t in tasks if type(t) is dict]
    if len(ids) != len(set(map(str, ids))):
        problems.append("tasks contains duplicate ids")
    return problems


def permitted_change(before: list[dict[str, Any]], result: dict[str, Any], task_id: str) -> tuple[bool, str, bool]:
    """Decide whether a well-formed result may be committed to the canonical records.

    Returns (permitted, reason, completes_target). The only permissible data
    change is the target task's ``completed`` flag going from false to true.
    Every other record must come back unchanged, and none may be added or
    dropped. ``ok`` must agree with the data.
    """
    after = {t["id"]: t for t in result["tasks"]}
    prior = {t["id"]: t for t in before}
    if set(after) != set(prior):
        dropped = sorted(set(prior) - set(after))[:5]
        added = sorted(set(after) - set(prior))[:5]
        return False, f"result changes the set of tasks (dropped {dropped}, added {added})", False
    changed = [tid for tid in prior if after[tid] != prior[tid]]
    for tid in changed:
        if tid != task_id:
            return False, f"result modifies non-target task {tid}", False
        a, b = prior[tid], after[tid]
        if a["title"] != b["title"] or not (a["completed"] is False and b["completed"] is True):
            return False, f"result changes {tid} in a way other than completing it", False
    completes = bool(changed)
    if result["ok"]:
        if task_id not in prior or after[task_id]["completed"] is not True:
            return False, "ok=true but the target task is not present and completed", False
    elif changed:
        return False, "ok=false but the result changes task data", False
    return True, "permitted", completes
