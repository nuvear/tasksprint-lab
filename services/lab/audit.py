"""Redacted audit events with request IDs (Architecture A5 runs/events, A9)."""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from typing import Any

from .clock import utc_now_iso

_SENSITIVE_KEY = re.compile(r"(token|secret|password|passwd|authorization|api[_-]?key|credential|cookie)", re.I)
_SENSITIVE_VALUE = re.compile(r"(Bearer\s+\S+|ts_[a-z]+_[A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9_\-]{8,})")
_MAX_STR = 200
_MAX_ITEMS = 20
_MAX_DEPTH = 4
REDACTED = "[REDACTED]"


def new_request_id() -> str:
    return "req_" + secrets.token_hex(12)


def redact(value: Any, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_ITEMS:
                out["_truncated"] = True
                break
            key = str(k)[:64]
            out[key] = REDACTED if _SENSITIVE_KEY.search(key) else redact(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [redact(v, depth + 1) for v in list(value)[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            items.append("[TRUNCATED]")
        return items
    if isinstance(value, str):
        cleaned = _SENSITIVE_VALUE.sub(REDACTED, value)
        return cleaned if len(cleaned) <= _MAX_STR else cleaned[:_MAX_STR] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value), depth + 1)


def record_event(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    actor_role: str,
    action: str,
    outcome: str,
    workspace_id: str | None = None,
    run_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    """Append one event inside the caller's transaction. Events are immutable."""
    event_id = "evt_" + secrets.token_hex(12)
    conn.execute(
        "INSERT INTO events(event_id, workspace_id, request_id, run_id, actor_role, action, outcome, details_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            workspace_id,
            request_id,
            run_id,
            actor_role,
            action,
            outcome,
            json.dumps(redact(details or {}), sort_keys=True, ensure_ascii=False),
            utc_now_iso(),
        ),
    )
    return event_id


def list_events(conn: sqlite3.Connection, workspace_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT event_id, request_id, run_id, actor_role, action, outcome, details_json, created_at"
        " FROM events WHERE workspace_id = ? ORDER BY rowid DESC LIMIT ?",
        (workspace_id, limit),
    ).fetchall()
    return [
        {
            "event_id": r["event_id"],
            "request_id": r["request_id"],
            "run_id": r["run_id"],
            "actor_role": r["actor_role"],
            "action": r["action"],
            "outcome": r["outcome"],
            "details": json.loads(r["details_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
