"""SQLite store with explicit, versioned migrations (Architecture A5).

One backend worker and one controlled writer: every write goes through
``Store.write()``, which serialises writers with a process lock and an
``BEGIN IMMEDIATE`` transaction. Reads use short-lived connections.

Record types are kept in separate tables; persisting in the same file does not
merge tasks, sprint state, preference memory, candidates, evidence or releases.
Append-only evidence tables are protected by triggers that abort UPDATE/DELETE.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .clock import utc_now_iso


class LabError(Exception):
    """Controlled application error mapped to an HTTP response."""

    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}


SPRINT_STAGES = ("PLANNED", "IN_DEVELOPMENT", "IN_QA", "CHANGES_REQUESTED", "APP_VERIFIED", "READY_FOR_REVIEW", "CLOSED")
RELEASE_PLAN_STATES = ("PLANNED", "AWAITING_APPROVAL", "APPROVED", "EXECUTED", "REJECTED", "EXPIRED", "ROLLED_BACK")
CANDIDATE_ORIGINS = ("fixture", "fixture-faulty", "fixture-reference", "agent-generated")


def _immutable(table: str) -> str:
    return (
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
    )


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


MIGRATION_0001 = f"""
CREATE TABLE workspaces (
    workspace_id   TEXT PRIMARY KEY,
    active         INTEGER NOT NULL CHECK (active IN (0,1)),
    environment    TEXT NOT NULL CHECK (environment = 'demo-production'),
    generation     INTEGER NOT NULL CHECK (generation >= 1),
    next_task_seq  INTEGER NOT NULL CHECK (next_task_seq >= 1),
    baseline_sha256 TEXT NOT NULL CHECK (length(baseline_sha256) = 64),
    revision       INTEGER NOT NULL CHECK (revision >= 1),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE tasks (
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    task_id      TEXT NOT NULL,
    title        TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
    completed    INTEGER NOT NULL CHECK (completed IN (0,1)),
    revision     INTEGER NOT NULL CHECK (revision >= 1),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, task_id)
);
CREATE TABLE sprints (
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    sprint_id    TEXT NOT NULL,
    goal         TEXT NOT NULL,
    revision     INTEGER NOT NULL CHECK (revision >= 1),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, sprint_id)
);
CREATE TABLE stories (
    workspace_id     TEXT NOT NULL REFERENCES workspaces(workspace_id),
    story_id         TEXT NOT NULL,
    sprint_id        TEXT NOT NULL,
    title            TEXT NOT NULL,
    narrative        TEXT NOT NULL,
    criteria_json    TEXT NOT NULL,
    criteria_version INTEGER NOT NULL CHECK (criteria_version >= 1),
    scope_confirmed  INTEGER NOT NULL CHECK (scope_confirmed IN (0,1)),
    stage            TEXT NOT NULL CHECK (stage IN {_in(SPRINT_STAGES)}),
    candidate_id     TEXT,
    repair_count     INTEGER NOT NULL CHECK (repair_count >= 0),
    evidence_json    TEXT NOT NULL,
    revision         INTEGER NOT NULL CHECK (revision >= 1),
    created_by       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (workspace_id, story_id),
    FOREIGN KEY (workspace_id, sprint_id) REFERENCES sprints(workspace_id, sprint_id)
);
CREATE TABLE memories (
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    owner        TEXT NOT NULL,
    pref_key     TEXT NOT NULL,
    pref_value   TEXT NOT NULL,
    source       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, owner, pref_key)
);
CREATE TABLE documents (
    doc_id         TEXT NOT NULL,
    version        TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('approved','archived','draft')),
    effective_from TEXT NOT NULL,
    effective_to   TEXT,
    owner          TEXT NOT NULL,
    title          TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    ingested_at    TEXT NOT NULL,
    PRIMARY KEY (doc_id, version)
);
CREATE TABLE chunks (
    chunk_id       TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL,
    version        TEXT NOT NULL,
    section        TEXT NOT NULL,
    chunk_text     TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    FOREIGN KEY (doc_id, version) REFERENCES documents(doc_id, version)
);
CREATE TABLE skills (
    name          TEXT NOT NULL,
    version       TEXT NOT NULL,
    description   TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    body          TEXT NOT NULL,
    body_sha256   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (name, version)
);
CREATE TABLE candidates (
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    candidate_id TEXT NOT NULL,
    sha256       TEXT NOT NULL CHECK (length(sha256) = 64),
    source       BLOB NOT NULL,
    size_bytes   INTEGER NOT NULL CHECK (size_bytes BETWEEN 1 AND 4096),
    base_sha256  TEXT,
    author_role  TEXT NOT NULL,
    origin       TEXT NOT NULL CHECK (origin IN {_in(CANDIDATE_ORIGINS)}),
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, candidate_id),
    UNIQUE (workspace_id, sha256)
);
CREATE TABLE test_runs (
    test_run_id      TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES workspaces(workspace_id),
    candidate_id     TEXT NOT NULL,
    candidate_sha256 TEXT NOT NULL,
    suite_sha256     TEXT NOT NULL,
    cases_json       TEXT NOT NULL,
    outcome          TEXT NOT NULL CHECK (outcome IN ('pass','fail','error')),
    runner_version   TEXT NOT NULL,
    evidence_json    TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE TABLE agent_eval_reports (
    report_id         TEXT PRIMARY KEY,
    manifest_json     TEXT NOT NULL,
    cases_json        TEXT NOT NULL,
    repetitions       INTEGER NOT NULL,
    outcomes_json     TEXT NOT NULL,
    trajectories_json TEXT NOT NULL,
    created_by        TEXT NOT NULL,
    created_at        TEXT NOT NULL
);
CREATE TABLE release_plans (
    plan_id      TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    generation   INTEGER NOT NULL,
    operation    TEXT NOT NULL CHECK (operation IN ('deploy','rollback')),
    plan_json    TEXT NOT NULL,
    plan_sha256  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE release_plan_states (
    plan_id    TEXT PRIMARY KEY REFERENCES release_plans(plan_id),
    state      TEXT NOT NULL CHECK (state IN {_in(RELEASE_PLAN_STATES)}),
    revision   INTEGER NOT NULL CHECK (revision >= 1),
    updated_at TEXT NOT NULL
);
CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL REFERENCES release_plans(plan_id),
    plan_sha256 TEXT NOT NULL,
    approver    TEXT NOT NULL,
    decision    TEXT NOT NULL CHECK (decision IN ('approve','reject')),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    consumed_at TEXT
);
CREATE TABLE active_releases (
    workspace_id        TEXT PRIMARY KEY REFERENCES workspaces(workspace_id),
    active_candidate_id TEXT NOT NULL,
    active_sha256       TEXT NOT NULL,
    previous_sha256     TEXT,
    release_revision    INTEGER NOT NULL CHECK (release_revision >= 0),
    updated_at          TEXT NOT NULL
);
CREATE TABLE releases (
    release_id       TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES workspaces(workspace_id),
    release_revision INTEGER NOT NULL,
    operation        TEXT NOT NULL CHECK (operation IN ('seed','deploy','rollback')),
    active_sha256    TEXT NOT NULL,
    previous_sha256  TEXT,
    plan_id          TEXT,
    action_id        TEXT UNIQUE,
    receipt_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (workspace_id, release_revision)
);
CREATE TABLE runs (
    run_id            TEXT PRIMARY KEY,
    workspace_id      TEXT NOT NULL REFERENCES workspaces(workspace_id),
    generation        INTEGER NOT NULL,
    role              TEXT NOT NULL,
    session_namespace TEXT NOT NULL,
    parent_run_id     TEXT REFERENCES runs(run_id),
    root_run_id       TEXT NOT NULL,
    depth             INTEGER NOT NULL CHECK (depth BETWEEN 0 AND 2),
    max_actions       INTEGER NOT NULL,
    actions_used      INTEGER NOT NULL,
    tree_max_actions  INTEGER NOT NULL,
    tree_actions_used INTEGER NOT NULL,
    deadline_at       TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('active','completed','cancelled','expired')),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE events (
    event_id     TEXT PRIMARY KEY,
    workspace_id TEXT,
    request_id   TEXT NOT NULL,
    run_id       TEXT,
    actor_role   TEXT NOT NULL,
    action       TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX events_by_workspace ON events(workspace_id);
CREATE TABLE drills (
    drill_id         TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES workspaces(workspace_id),
    fault_type       TEXT NOT NULL CHECK (fault_type IN ('completion_unavailable')),
    candidate_sha256 TEXT NOT NULL,
    enabled          INTEGER NOT NULL CHECK (enabled IN (0,1)),
    expires_at       TEXT NOT NULL,
    created_by       TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
{_immutable("candidates")}
{_immutable("test_runs")}
{_immutable("agent_eval_reports")}
{_immutable("release_plans")}
{_immutable("releases")}
{_immutable("events")}
{_immutable("documents")}
{_immutable("chunks")}
{_immutable("skills")}
"""

# Phase 04: SQLite FTS5 index over knowledge chunks (Architecture A7). The FTS
# rowid equals chunks.rowid. Virtual tables cannot carry the append-only triggers;
# only retrieval.ingest() writes here, and chunks/documents stay append-only.
MIGRATION_0002 = """
CREATE VIRTUAL TABLE chunks_fts USING fts5(section, chunk_text, tokenize = 'porter unicode61');
"""

# (version, name, sql). Never edit an applied migration: add a new version.
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial lab schema (Phase 02)", MIGRATION_0001),
    (2, "FTS5 knowledge chunk index (Phase 04)", MIGRATION_0002),
]


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, db_path: str, journal_mode: str = "TRUNCATE"):
        self.db_path = db_path
        self.journal_mode = journal_mode
        self._write_lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(f"PRAGMA journal_mode = {self.journal_mode}")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """The single controlled writer: serialised, transactional, all-or-nothing."""
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                else:
                    conn.execute("COMMIT")
            finally:
                conn.close()

    def migrate(self) -> list[int]:
        """Apply pending migrations in order; verify checksums of applied ones."""
        applied_now: list[int] = []
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    " version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
                )
                applied = {r["version"]: r["checksum"] for r in conn.execute("SELECT version, checksum FROM schema_migrations")}
                known = {v for v, _, _ in MIGRATIONS}
                if set(applied) - known:
                    raise RuntimeError("database has migrations newer than this code; refusing to start")
                for version, name, sql in sorted(MIGRATIONS):
                    if version in applied:
                        if applied[version] != _checksum(sql):
                            raise RuntimeError(f"migration {version} checksum mismatch; refusing to start")
                        continue
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in _split_sql(sql):
                            conn.execute(statement)
                        conn.execute(
                            "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?,?,?,?)",
                            (version, name, _checksum(sql), utc_now_iso()),
                        )
                        conn.execute("COMMIT")
                    except BaseException:
                        conn.execute("ROLLBACK")
                        raise
                    applied_now.append(version)
            finally:
                conn.close()
        return applied_now

    def schema_version(self) -> int:
        with self.read() as conn:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            return int(row["v"] or 0)


def _split_sql(sql: str) -> list[str]:
    """Split on statement boundaries, keeping trigger bodies (BEGIN ... END;) intact."""
    statements: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip():
        raise RuntimeError("incomplete SQL statement in migration")
    return statements


# ---------------------------------------------------------------- workspace helpers

def get_workspace(conn: sqlite3.Connection, workspace_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone()


def require_active_workspace(conn: sqlite3.Connection, workspace_id: str) -> sqlite3.Row:
    ws = get_workspace(conn, workspace_id)
    if ws is None or not ws["active"]:
        raise LabError(404, "WORKSPACE_NOT_FOUND", "workspace does not exist or is inactive")
    return ws
