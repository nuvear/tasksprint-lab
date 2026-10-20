"""Immutable candidate artifacts (Architecture A5, A6).

Source bytes are stored exactly as received and never modified; the table is
append-only (triggers). The candidate ID is derived from the SHA-256 of the
bytes. Provenance is fixed at first registration. This module never parses,
compiles or executes candidate source: Phase 03 adds the separate runner.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any

from .clock import utc_now_iso
from .store import CANDIDATE_ORIGINS, LabError

MAX_SOURCE_BYTES = 4096
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_CONTROL = {"\n", "\r", "\t"}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def candidate_id_for(sha256: str) -> str:
    return "cand_" + sha256[:24]


def _validate_source(source: bytes) -> None:
    if not 1 <= len(source) <= MAX_SOURCE_BYTES:
        raise LabError(413, "SOURCE_TOO_LARGE", f"candidate source must be 1..{MAX_SOURCE_BYTES} bytes")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LabError(422, "SOURCE_NOT_UTF8", "candidate source must be UTF-8 text") from exc
    if any((ord(ch) < 32 and ch not in _ALLOWED_CONTROL) or ord(ch) == 127 for ch in text):
        raise LabError(422, "SOURCE_CONTROL_CHARS", "candidate source contains disallowed control characters")


def put_candidate(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    source: bytes,
    origin: str,
    author_role: str,
    label: str,
    base_sha256: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Register immutable source. Returns (record, created). Never overwrites."""
    if origin not in CANDIDATE_ORIGINS:
        raise LabError(422, "INVALID_ORIGIN", "unknown candidate origin")
    _validate_source(source)
    if base_sha256 is not None:
        if not _HEX64.match(base_sha256):
            raise LabError(422, "INVALID_BASE_HASH", "base_sha256 must be a SHA-256 hex digest")
        if conn.execute(
            "SELECT 1 FROM candidates WHERE workspace_id = ? AND sha256 = ?", (workspace_id, base_sha256)
        ).fetchone() is None:
            raise LabError(422, "UNKNOWN_BASE", "base_sha256 does not name a candidate in this workspace")
    digest = sha256_hex(source)
    existing = conn.execute(
        "SELECT * FROM candidates WHERE workspace_id = ? AND sha256 = ?", (workspace_id, digest)
    ).fetchone()
    if existing is not None:
        if existing["origin"] != origin or existing["author_role"] != author_role:
            raise LabError(409, "CANDIDATE_EXISTS", "identical source is already registered with different provenance")
        return candidate_view(existing, include_source=False), False
    cid = candidate_id_for(digest)
    conn.execute(
        "INSERT INTO candidates(workspace_id, candidate_id, sha256, source, size_bytes, base_sha256, author_role, origin, label, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (workspace_id, cid, digest, source, len(source), base_sha256, author_role, origin, label, utc_now_iso()),
    )
    row = conn.execute("SELECT * FROM candidates WHERE workspace_id = ? AND candidate_id = ?", (workspace_id, cid)).fetchone()
    return candidate_view(row, include_source=False), True


def get_candidate(conn: sqlite3.Connection, workspace_id: str, candidate_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM candidates WHERE workspace_id = ? AND candidate_id = ?", (workspace_id, candidate_id)
    ).fetchone()


def verify_integrity(row: sqlite3.Row) -> bool:
    return sha256_hex(bytes(row["source"])) == row["sha256"] and candidate_id_for(row["sha256"]) == row["candidate_id"]


def candidate_view(row: sqlite3.Row, *, include_source: bool) -> dict[str, Any]:
    view: dict[str, Any] = {
        "candidate_id": row["candidate_id"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "base_sha256": row["base_sha256"],
        "author_role": row["author_role"],
        "origin": row["origin"],
        "label": row["label"],
        "created_at": row["created_at"],
    }
    if include_source:
        view["source"] = bytes(row["source"]).decode("utf-8")
    return view


def source_read_allowed(conn: sqlite3.Connection, workspace_id: str, role: str, row: sqlite3.Row) -> bool:
    """Source-read policy (A6, A8): reference fixtures are never model-readable;
    the faulty fixture is developer-readable only once selected for a story."""
    origin = row["origin"]
    if origin == "fixture-reference":
        return False
    if origin == "fixture-faulty" and role == "developer":
        selected = conn.execute(
            "SELECT 1 FROM stories WHERE workspace_id = ? AND candidate_id = ?", (workspace_id, row["candidate_id"])
        ).fetchone()
        return selected is not None
    return True
