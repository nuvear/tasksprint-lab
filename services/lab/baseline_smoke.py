"""Baseline smoke suite for rollback (Architecture A11 step 6; Phase 09).

A rollback must not demand the new feature's tests of the old starter. Instead the
recorded healthy baseline (starter v0) must pass this smoke suite before an approved
rollback can activate it. Trusted lab code runs it on a SCRATCH database, never on
the workspace's canonical records:

* the exact stored baseline bytes (verified against the recorded hash) are installed
  as the active artifact of a throw-away workspace with the two synthetic seed tasks;
* the real command paths run against that scratch copy:
    BS-01 add <title>          -> ADDED, one new record with a server ID
    BS-02 list                 -> LISTED, every record present
    BS-03 status               -> STATUS, active hash = baseline hash, healthy
    BS-04 complete T001        -> FEATURE_UNAVAILABLE through the bounded runner, records identical
    BS-05 complete T999        -> no record changed
* the report is append-only in ``baseline_smoke_runs`` with ``suite_sha256`` = SHA-256
  of this module's bytes and the runner version that interpreted the source.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from . import app_commands
from .audit import record_event
from .candidates import put_candidate, source_text, verify_integrity
from .clock import utc_now_iso
from .releases import record_seed_release
from .runner_client import RunnerClient
from .store import LabError, Store

SMOKE_VERSION = "tasksprint-baseline-smoke/1"
SMOKE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SCRATCH_WS = "smoke-scratch"
SEED_TASKS = (("T001", "Draft workshop agenda"), ("T002", "Book the sprint review room"))


def _check(name: str, passed: bool, expected: Any = None, actual: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "expected": expected, "actual": actual}


def _records(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT task_id, title, completed, revision FROM tasks WHERE workspace_id = ? ORDER BY task_id", (SCRATCH_WS,))]


def _scratch(store: Store, source: bytes, sha256: str) -> None:
    now = utc_now_iso()
    with store.write() as conn:
        conn.execute("INSERT INTO workspaces(workspace_id, active, environment, generation, next_task_seq,"
                     " baseline_sha256, revision, created_at, updated_at) VALUES (?,1,'demo-production',1,?,?,1,?,?)",
                     (SCRATCH_WS, len(SEED_TASKS) + 1, sha256, now, now))
        view, _ = put_candidate(conn, workspace_id=SCRATCH_WS, source=source, origin="fixture",
                                author_role="instructor", label="baseline-under-smoke")
        cand = conn.execute("SELECT * FROM candidates WHERE workspace_id = ? AND candidate_id = ?",
                            (SCRATCH_WS, view["candidate_id"])).fetchone()
        record_seed_release(conn, SCRATCH_WS, cand, "req_smoke")
        for task_id, title in SEED_TASKS:
            conn.execute("INSERT INTO tasks(workspace_id, task_id, title, completed, revision, created_at, updated_at)"
                         " VALUES (?,?,?,0,1,?,?)", (SCRATCH_WS, task_id, title, now, now))


def _run_cases(store: Store, runner: RunnerClient | None, sha256: str) -> tuple[list[dict], set[str]]:
    versions: set[str] = set()
    cases: list[dict] = []

    def case(case_id: str, title: str, checks: list[dict]) -> None:
        cases.append({"case_id": case_id, "title": title, "passed": all(c["passed"] for c in checks),
                      "assertions": checks})

    with store.write() as conn:
        res = app_commands.execute(conn, SCRATCH_WS, app_commands.parse("add Smoke check task"))
        rows = _records(conn)
    case("BS-01", "add persists one record with a server ID",
         [_check("code", res["code"] == "ADDED", "ADDED", res["code"]),
          _check("record_count", len(rows) == 3, 3, len(rows)),
          _check("server_id", res["data"]["task"]["id"] == "T003", "T003", res["data"]["task"]["id"])])
    with store.read() as conn:
        res = app_commands.execute(conn, SCRATCH_WS, app_commands.parse("list"))
    ids = [t["id"] for t in res["data"]["tasks"]]
    case("BS-02", "list shows every record", [_check("code", res["code"] == "LISTED", "LISTED", res["code"]),
                                              _check("ids", ids == ["T001", "T002", "T003"], ["T001", "T002", "T003"], ids)])
    with store.read() as conn:
        res = app_commands.execute(conn, SCRATCH_WS, app_commands.parse("status"))
    case("BS-03", "status reports the baseline hash and healthy business health",
         [_check("code", res["code"] == "STATUS", "STATUS", res["code"]),
          _check("active_sha256", res["data"].get("active_sha256") == sha256, sha256, res["data"].get("active_sha256")),
          _check("health", res["data"]["status"] == "healthy", "healthy", res["data"]["status"])])
    for case_id, task_id, title in (("BS-04", "T001", "complete on the starter returns FEATURE_UNAVAILABLE"),
                                    ("BS-05", "T999", "complete of an unknown ID changes nothing")):
        with store.read() as conn:
            before = _records(conn)
        res = app_commands.complete_task(store, runner, SCRATCH_WS, task_id, record=lambda conn, result: None)
        with store.read() as conn:
            after = _records(conn)
        ev = res["data"].get("evaluation") or {}
        if ev.get("evaluated_by"):
            versions.add(ev["evaluated_by"])
        checks = [_check("runner_evaluated", bool(ev.get("evaluated_by")), "bounded runner", ev.get("evaluated_by")),
                  _check("interpreted_sha256", ev.get("interpreted_sha256") == sha256, sha256,
                         ev.get("interpreted_sha256")),
                  _check("records_unchanged", before == after, "identical", "identical" if before == after else "changed"),
                  _check("tasks_changed", res["data"].get("tasks_changed") == 0, 0, res["data"].get("tasks_changed"))]
        if task_id == "T001":
            checks.insert(0, _check("code", res["code"] == "FEATURE_UNAVAILABLE", "FEATURE_UNAVAILABLE", res["code"]))
        case(case_id, title, checks)
    return cases, versions


def run_baseline_smoke(store: Store, runner: RunnerClient | None, *, workspace_id: str, baseline_sha256: str,
                       request_id: str, actor_role: str, run_id: str | None) -> dict[str, Any]:
    """Run the smoke suite against the stored baseline bytes on a scratch copy and record the report."""
    with store.read() as conn:
        row = conn.execute("SELECT * FROM candidates WHERE workspace_id = ? AND sha256 = ?",
                           (workspace_id, baseline_sha256)).fetchone()
        if row is None or not verify_integrity(row):
            raise LabError(409, "BASELINE_EVIDENCE_MISSING", "the recorded baseline artifact is missing or corrupt")
        source = source_text(row).encode("utf-8")
    error = None
    versions: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="ts-smoke-") as tmp:
        scratch = Store(str(Path(tmp) / "smoke.sqlite3"))
        scratch.migrate()
        _scratch(scratch, source, baseline_sha256)
        try:
            cases, versions = _run_cases(scratch, runner, baseline_sha256)
        except LabError as err:
            cases, error = [], {"code": err.code}
    outcome = "error" if error else ("pass" if cases and all(c["passed"] for c in cases) else "fail")
    smoke_id = "bs_" + secrets.token_hex(12)
    runner_version = "+".join(sorted(versions)) or None
    with store.write() as conn:
        conn.execute("INSERT INTO baseline_smoke_runs(smoke_id, workspace_id, candidate_sha256, suite_sha256,"
                     " cases_json, outcome, runner_version, created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (smoke_id, workspace_id, baseline_sha256, SMOKE_SHA256,
                      json.dumps({"cases": cases, "error": error, "suite_version": SMOKE_VERSION,
                                  "data_scope": "scratch copy; canonical workspace tasks were not read or written"},
                                 sort_keys=True), outcome, runner_version, utc_now_iso()))
        record_event(conn, request_id=request_id, actor_role=actor_role, action="baseline_smoke.run", outcome=outcome,
                     workspace_id=workspace_id, run_id=run_id,
                     details={"smoke_id": smoke_id, "baseline_sha256": baseline_sha256, "suite_sha256": SMOKE_SHA256,
                              "cases": {c["case_id"]: c["passed"] for c in cases}, "error": error})
        return smoke_view(conn.execute("SELECT * FROM baseline_smoke_runs WHERE smoke_id = ?", (smoke_id,)).fetchone())


def passing_smoke(conn: sqlite3.Connection, workspace_id: str, baseline_sha256: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM baseline_smoke_runs WHERE workspace_id = ? AND candidate_sha256 = ? AND"
                        " suite_sha256 = ? AND outcome = 'pass' ORDER BY created_at DESC, rowid DESC LIMIT 1",
                        (workspace_id, baseline_sha256, SMOKE_SHA256)).fetchone()


def smoke_view(row: sqlite3.Row) -> dict[str, Any]:
    doc = json.loads(row["cases_json"])
    return {"record_type": "baseline_smoke_run", "smoke_id": row["smoke_id"], "candidate_sha256": row["candidate_sha256"],
            "suite_version": doc.get("suite_version"), "suite_sha256": row["suite_sha256"], "outcome": row["outcome"],
            "runner_version": row["runner_version"], "cases": doc.get("cases"), "error": doc.get("error"),
            "created_at": row["created_at"]}
