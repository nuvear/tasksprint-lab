"""Protected application test suite (Architecture A5 test_runs, A6, A8; Build Guide 03.3).

Trusted lab code runs this suite. QA can only ask for a run against a candidate
ID; it cannot supply cases, expectations, results or a PASS flag, and it cannot
read or alter this module. Each case sends a fresh COPY of a fixed synthetic
task list (never canonical workspace data) to the separate runner, then asserts
on the runner's computed result. The report is built only from those
assertions and is stored append-only in ``test_runs`` with:

* the candidate's verified source SHA-256,
* ``suite_sha256`` = SHA-256 of this module's own bytes (any edit to the suite
  changes it),
* the runner version that interpreted the source,
* an evidence ID per runner evaluation (input/result digests, status, op count).

Cases (Acceptance APP-01..APP-04 plus contract checks):
    TC-01 completes an incomplete target with completed=true (APP-01)
    TC-02 retains every non-target task unchanged (APP-02, retention)
    TC-03 idempotent on an already-completed task and on re-application (APP-03)
    TC-04 unknown ID -> TASK_NOT_FOUND with identical records (APP-04)
    TC-05 output shape is exactly {ok, code, tasks[{id, title, completed}]}
    TC-06 the lab-held input copy is not mutated and results are deterministic
"""
from __future__ import annotations

import copy
import hashlib
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .audit import record_event
from .candidates import load_verified, source_text
from .clock import utc_now_iso
from .contract import shape_problems
from .runner_client import RunnerClient
from .store import LabError, Store

SUITE_VERSION = "tasksprint-app-suite/1"
SUITE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# Synthetic data only. Never canonical workspace tasks.
SYNTHETIC_TASKS: tuple[dict[str, Any], ...] = (
    {"id": "T001", "title": "Draft workshop agenda", "completed": False},
    {"id": "T002", "title": "Book the sprint review room", "completed": False},
    {"id": "T003", "title": "Prepare sprint review", "completed": True},
)
UNKNOWN_ID = "T999"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def dataset_sha256() -> str:
    return _digest(list(SYNTHETIC_TASKS))


def fresh_tasks() -> list[dict[str, Any]]:
    return copy.deepcopy(list(SYNTHETIC_TASKS))


def _summary(result: Any) -> Any:
    """Bounded description of a result for the report (ids and flags, not full payloads)."""
    if type(result) is not dict:
        return {"type": type(result).__name__}
    tasks = result.get("tasks")
    listed = None
    if type(tasks) is list:
        listed = [[t.get("id"), t.get("completed")] if type(t) is dict else type(t).__name__ for t in tasks[:10]]
    return {"ok": result.get("ok"), "code": str(result.get("code"))[:40], "tasks": listed}


class _Evaluator:
    def __init__(self, runner: RunnerClient, source: str, sha256: str):
        self.runner, self.source, self.sha256 = runner, source, sha256
        self.evidence: list[dict[str, Any]] = []
        self.runner_versions: set[str] = set()

    def __call__(self, tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
        sent = copy.deepcopy(tasks)
        doc = self.runner.evaluate(source=self.source, source_sha256=self.sha256, tasks=sent, task_id=task_id)
        self.runner_versions.add(doc["runner_version"])
        ev = {"evidence_id": "ev_" + secrets.token_hex(8), "task_id": task_id, "input_sha256": _digest(tasks),
              "status": doc["status"], "error_code": (doc.get("error") or {}).get("code"),
              "result_sha256": _digest(doc["result"]) if doc["status"] == "ok" else None, "ops": doc["ops"]}
        self.evidence.append(ev)
        return {**doc, "evidence_id": ev["evidence_id"]}


def _check(name: str, passed: bool, expected: Any = None, actual: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if not passed:
        out["expected"] = expected
        out["actual"] = actual
    return out


def _ran(doc: dict[str, Any]) -> dict[str, Any]:
    ok = doc["status"] == "ok"
    return _check("candidate evaluated by runner", ok, "status ok",
                  {"status": doc["status"], "error": doc.get("error")})


def _well_formed(doc: dict[str, Any]) -> bool:
    return doc["status"] == "ok" and not shape_problems(doc["result"])


def _by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in result["tasks"]}


def case_complete_target(ev: _Evaluator) -> tuple[list[dict], list[str]]:
    doc = ev(fresh_tasks(), "T001")
    checks = [_ran(doc)]
    if _well_formed(doc):
        r = doc["result"]
        tasks = _by_id(r)
        checks.append(_check("ok is true", r["ok"] is True, True, r["ok"]))
        checks.append(_check("code is COMPLETED", r["code"] == "COMPLETED", "COMPLETED", r["code"]))
        checks.append(_check("target T001 still present", "T001" in tasks, "present", sorted(tasks)))
        if "T001" in tasks:
            checks.append(_check("target title unchanged", tasks["T001"]["title"] == SYNTHETIC_TASKS[0]["title"],
                                 SYNTHETIC_TASKS[0]["title"], tasks["T001"]["title"]))
            checks.append(_check("target completed is true", tasks["T001"]["completed"] is True, True,
                                 tasks["T001"]["completed"]))
    elif doc["status"] == "ok":
        checks.append(_check("result is well-formed", False, "contract shape", shape_problems(doc["result"])[:3]))
    return checks, [doc["evidence_id"]]


def case_retains_others(ev: _Evaluator) -> tuple[list[dict], list[str]]:
    doc = ev(fresh_tasks(), "T002")
    checks = [_ran(doc)]
    if _well_formed(doc):
        tasks = _by_id(doc["result"])
        expected_ids = [t["id"] for t in SYNTHETIC_TASKS]
        checks.append(_check("task count unchanged", len(doc["result"]["tasks"]) == len(SYNTHETIC_TASKS),
                             len(SYNTHETIC_TASKS), len(doc["result"]["tasks"])))
        checks.append(_check("all task ids retained", sorted(tasks) == expected_ids, expected_ids, sorted(tasks)))
        for original in SYNTHETIC_TASKS:
            if original["id"] == "T002":
                continue
            checks.append(_check(f"non-target {original['id']} unchanged", tasks.get(original["id"]) == original,
                                 original, tasks.get(original["id"])))
        if "T002" in tasks:
            checks.append(_check("target T002 retained with completed=true", tasks["T002"]["completed"] is True,
                                 True, tasks["T002"]["completed"]))
    elif doc["status"] == "ok":
        checks.append(_check("result is well-formed", False, "contract shape", shape_problems(doc["result"])[:3]))
    return checks, [doc["evidence_id"]]


def case_idempotent(ev: _Evaluator) -> tuple[list[dict], list[str]]:
    ids: list[str] = []
    doc = ev(fresh_tasks(), "T003")
    ids.append(doc["evidence_id"])
    checks = [_ran(doc)]
    if _well_formed(doc):
        r = doc["result"]
        checks.append(_check("already-completed task: records identical", r["tasks"] == list(SYNTHETIC_TASKS),
                             [t["id"] for t in SYNTHETIC_TASKS], _summary(r)["tasks"]))
        checks.append(_check("already-completed task: ok is true", r["ok"] is True, True, r["ok"]))
    first = ev(fresh_tasks(), "T001")
    ids.append(first["evidence_id"])
    if _well_formed(first):
        second = ev(copy.deepcopy(first["result"]["tasks"]), "T001")
        ids.append(second["evidence_id"])
        same = _well_formed(second) and second["result"]["tasks"] == first["result"]["tasks"]
        checks.append(_check("re-applying complete leaves data unchanged", same, _summary(first["result"]),
                             _summary(second.get("result"))))
    else:
        checks.append(_check("re-applying complete leaves data unchanged", False, "well-formed first result",
                             _summary(first.get("result"))))
    return checks, ids


def case_unknown_id(ev: _Evaluator) -> tuple[list[dict], list[str]]:
    doc = ev(fresh_tasks(), UNKNOWN_ID)
    checks = [_ran(doc)]
    if _well_formed(doc):
        r = doc["result"]
        checks.append(_check("ok is false", r["ok"] is False, False, r["ok"]))
        checks.append(_check("code is TASK_NOT_FOUND", r["code"] == "TASK_NOT_FOUND", "TASK_NOT_FOUND", r["code"]))
        checks.append(_check("records identical (no mutation)", r["tasks"] == list(SYNTHETIC_TASKS),
                             [[t["id"], t["completed"]] for t in SYNTHETIC_TASKS], _summary(r)["tasks"]))
    elif doc["status"] == "ok":
        checks.append(_check("result is well-formed", False, "contract shape", shape_problems(doc["result"])[:3]))
    return checks, [doc["evidence_id"]]


def case_output_shape(ev: _Evaluator) -> tuple[list[dict], list[str]]:
    checks: list[dict] = []
    ids: list[str] = []
    for task_id in ("T001", UNKNOWN_ID):
        doc = ev(fresh_tasks(), task_id)
        ids.append(doc["evidence_id"])
        checks.append(_ran(doc))
        if doc["status"] == "ok":
            problems = shape_problems(doc["result"])
            checks.append(_check(f"result for {task_id} matches the contract shape", not problems, "no problems",
                                 problems[:3]))
    return checks, ids


def case_no_input_mutation(ev: _Evaluator) -> tuple[list[dict], list[str]]:
    held = fresh_tasks()
    pristine = copy.deepcopy(held)
    a = ev(held, "T001")
    b = ev(held, "T001")
    checks = [_ran(a), _check("lab-held input copy unchanged after evaluation", held == pristine, "unchanged", "changed")]
    if a["status"] == "ok" and b["status"] == "ok":
        checks.append(_check("identical input gives identical result", a["result"] == b["result"],
                             _summary(a["result"]), _summary(b["result"])))
    return checks, [a["evidence_id"], b["evidence_id"]]


CASES: tuple[tuple[str, str, str, Callable[[_Evaluator], tuple[list[dict], list[str]]]], ...] = (
    ("TC-01", "APP-01", "completes an incomplete target with completed=true", case_complete_target),
    ("TC-02", "APP-02", "retains every non-target task (retention)", case_retains_others),
    ("TC-03", "APP-03", "idempotent on already-completed task and re-application", case_idempotent),
    ("TC-04", "APP-04", "unknown id returns TASK_NOT_FOUND with no mutation", case_unknown_id),
    ("TC-05", "CONTRACT", "output shape is exactly {ok, code, tasks}", case_output_shape),
    ("TC-06", "CONTRACT", "input copy not mutated; deterministic result", case_no_input_mutation),
)


def _execute_suite(runner: RunnerClient, source: str, sha256: str) -> tuple[list[dict], _Evaluator, str]:
    ev = _Evaluator(runner, source, sha256)
    cases: list[dict] = []
    for case_id, app_check, title, fn in CASES:
        checks, ids = fn(ev)
        cases.append({"case_id": case_id, "acceptance": app_check, "title": title,
                      "passed": all(c["passed"] for c in checks), "assertions": checks, "evidence_ids": ids})
    outcome = "pass" if all(c["passed"] for c in cases) else "fail"
    return cases, ev, outcome


def run_protected_suite(store: Store, runner: RunnerClient | None, *, workspace_id: str, candidate_id: str,
                        request_id: str, actor_role: str, run_id: str | None) -> dict[str, Any]:
    with store.read() as conn:
        row = load_verified(conn, workspace_id, candidate_id)
        source, sha256, origin, label = source_text(row), row["sha256"], row["origin"], row["label"]
    error: dict[str, Any] | None = None
    ev: _Evaluator | None = None
    if runner is None:
        cases, outcome, error = [], "error", {"code": "RUNNER_NOT_CONFIGURED"}
    else:
        try:
            cases, ev, outcome = _execute_suite(runner, source, sha256)
        except LabError as err:
            if err.code != "RUNNER_UNAVAILABLE":
                raise
            cases, outcome, error = [], "error", {"code": err.code, **err.extra.get("audit", {})}
    evidence = ev.evidence if ev else []
    versions = sorted(ev.runner_versions) if ev else []
    runner_version = versions[0] if len(versions) == 1 else ("unavailable" if not versions else "+".join(versions))
    passed = sum(1 for c in cases for a in c["assertions"] if a["passed"])
    failed = sum(1 for c in cases for a in c["assertions"] if not a["passed"])
    evidence_doc = {
        "suite_version": SUITE_VERSION, "dataset_sha256": dataset_sha256(), "request_id": request_id,
        "requested_by": actor_role, "run_id": run_id, "candidate_origin": origin, "candidate_label": label,
        "fixture_label": ("FIXTURE (instructor-provided, labelled): " + origin) if origin.startswith("fixture") else None,
        "assertions": {"passed": passed, "failed": failed}, "evaluations": evidence,
        "evidence_ids": [e["evidence_id"] for e in evidence], "error": error,
        "data_scope": "synthetic copy; canonical workspace tasks were not read or written",
    }
    test_run_id = "tr_" + secrets.token_hex(12)
    now = utc_now_iso()
    with store.write() as conn:
        conn.execute(
            "INSERT INTO test_runs(test_run_id, workspace_id, candidate_id, candidate_sha256, suite_sha256, cases_json,"
            " outcome, runner_version, evidence_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (test_run_id, workspace_id, candidate_id, sha256, SUITE_SHA256, json.dumps(cases, sort_keys=True),
             outcome, runner_version, json.dumps(evidence_doc, sort_keys=True), now))
        record_event(conn, request_id=request_id, actor_role=actor_role, action="test_run.create", outcome=outcome,
                     workspace_id=workspace_id, run_id=run_id,
                     details={"test_run_id": test_run_id, "candidate_id": candidate_id, "candidate_sha256": sha256,
                              "suite_sha256": SUITE_SHA256, "passed": passed, "failed": failed})
        return report_view(conn.execute("SELECT * FROM test_runs WHERE test_run_id = ?", (test_run_id,)).fetchone())


def report_view(row: sqlite3.Row) -> dict[str, Any]:
    evidence = json.loads(row["evidence_json"])
    return {
        "record_type": "protected_test_run",
        "test_run_id": row["test_run_id"], "candidate_id": row["candidate_id"],
        "candidate_sha256": row["candidate_sha256"], "suite_sha256": row["suite_sha256"],
        "suite_version": evidence.get("suite_version"), "outcome": row["outcome"],
        "runner_version": row["runner_version"], "cases": json.loads(row["cases_json"]),
        "evidence": evidence, "created_at": row["created_at"],
        "report_sha256": hashlib.sha256((row["cases_json"] + row["evidence_json"]).encode()).hexdigest(),
    }


def get_report(conn: sqlite3.Connection, workspace_id: str, test_run_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM test_runs WHERE test_run_id = ? AND workspace_id = ?",
                       (test_run_id, workspace_id)).fetchone()
    if row is None:
        raise LabError(404, "TEST_RUN_NOT_FOUND", "test run does not exist in this workspace")
    return report_view(row)
