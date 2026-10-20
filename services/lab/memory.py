"""Selected preference memory (Architecture A5; nine-term "Memory and State").

Only allowlisted presentation preferences with enumerated values can be stored.
Records are scoped to (workspace, owner), carry a source and an expiry, and are
kept apart from canonical sprint state. Memory is never approval or evidence.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from .clock import parse_iso, to_iso, utc_now
from .store import LabError

ALLOWED_PREFERENCES: dict[str, frozenset[str]] = {
    "release_notes_style": frozenset({"concise", "detailed"}),
    "summary_length": frozenset({"short", "medium", "long"}),
    "response_language": frozenset({"en", "ja", "zh-Hans"}),
    "evidence_format": frozenset({"ids_only", "ids_with_titles"}),
}
DEFAULT_TTL_DAYS = 7
MAX_TTL_DAYS = 30
MAX_PREFERENCES_PER_OWNER = len(ALLOWED_PREFERENCES)


def save_preference(conn: sqlite3.Connection, *, workspace_id: str, owner: str, key: str, value: str,
                    ttl_days: int, source: str) -> dict[str, Any]:
    allowed = ALLOWED_PREFERENCES.get(key)
    if allowed is None:
        raise LabError(422, "PREFERENCE_NOT_ALLOWED", "only allowlisted presentation preferences can be remembered",
                       {"allowed_keys": sorted(ALLOWED_PREFERENCES)})
    if value not in allowed:
        raise LabError(422, "PREFERENCE_VALUE_NOT_ALLOWED", "value is not one of the allowed options",
                       {"allowed_values": sorted(allowed)})
    if not 1 <= ttl_days <= MAX_TTL_DAYS:
        raise LabError(422, "INVALID_TTL", f"ttl_days must be 1..{MAX_TTL_DAYS}")
    now = utc_now()
    conn.execute(
        "INSERT INTO memories(workspace_id, owner, pref_key, pref_value, source, created_at, expires_at)"
        " VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(workspace_id, owner, pref_key) DO UPDATE SET"
        " pref_value = excluded.pref_value, source = excluded.source,"
        " created_at = excluded.created_at, expires_at = excluded.expires_at",
        (workspace_id, owner, key, value, source, to_iso(now), to_iso(now + timedelta(days=ttl_days))),
    )
    return {"key": key, "value": value, "owner": owner, "source": source,
            "created_at": to_iso(now), "expires_at": to_iso(now + timedelta(days=ttl_days))}


def read_preferences(conn: sqlite3.Connection, *, workspace_id: str, owner: str) -> dict[str, Any]:
    now = utc_now()
    rows = conn.execute(
        "SELECT pref_key, pref_value, source, created_at, expires_at FROM memories"
        " WHERE workspace_id = ? AND owner = ? ORDER BY pref_key",
        (workspace_id, owner),
    ).fetchall()
    prefs = [
        {"key": r["pref_key"], "value": r["pref_value"], "source": r["source"],
         "created_at": r["created_at"], "expires_at": r["expires_at"]}
        for r in rows
        if parse_iso(r["expires_at"]) > now
    ]
    return {"record_type": "preference_memory", "owner": owner, "preferences": prefs,
            "note": "Presentation preferences only. Not state, evidence or approval."}
