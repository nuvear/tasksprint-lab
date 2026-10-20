"""Protected application suite: real assertions, immutable reports, role rules (Build Guide 03.3, APP-01..04)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from services.lab import testing
from tests.conftest import Lab, headers

REPO = Path(__file__).resolve().parents[2]


def case(report: dict, case_id: str) -> dict:
    return next(c for c in report["cases"] if c["case_id"] == case_id)


def starter_id(lab: Lab) -> str:
    return lab.client.get("/v1/releases", headers=headers("operations")).json()["active"]["candidate_id"]


def test_reference_fixture_passes_every_case(seeded):
    ref = seeded.load_fixture("reference_complete")
    r = seeded.run_tests(ref["candidate_id"])
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["outcome"] == "pass"
    assert [c["case_id"] for c in rep["cases"]] == ["TC-01", "TC-02", "TC-03", "TC-04", "TC-05", "TC-06"]
    assert all(c["passed"] for c in rep["cases"])
    assert rep["candidate_sha256"] == ref["sha256"]
    assert rep["evidence"]["fixture_label"].startswith("FIXTURE")
    assert "def complete" not in json.dumps(rep)  # the report never carries reference source


def test_faulty_fixture_fails_retention_and_unknown_id(seeded):
    bad = seeded.load_fixture("faulty_delete")
    rep = seeded.run_tests(bad["candidate_id"]).json()
    assert rep["outcome"] == "fail"
    tc02 = case(rep, "TC-02")
    assert not tc02["passed"]
    failed = {a["name"] for a in tc02["assertions"] if not a["passed"]}
    assert {"task count unchanged", "all task ids retained"} <= failed
    assert not case(rep, "TC-01")["passed"]  # target removed instead of completed
    tc04 = case(rep, "TC-04")
    assert not tc04["passed"]
    assert any(a["name"] == "code is TASK_NOT_FOUND" and a["actual"] == "COMPLETED" for a in tc04["assertions"])


def test_starter_v0_is_healthy_but_does_not_satisfy_the_story(seeded):
    rep = seeded.run_tests(starter_id(seeded)).json()
    assert rep["outcome"] == "fail"
    assert not case(rep, "TC-01")["passed"] and not case(rep, "TC-04")["passed"]
    assert case(rep, "TC-05")["passed"] and case(rep, "TC-06")["passed"]  # well-formed and non-mutating


def test_forbidden_syntax_candidate_fails_with_validator_evidence(seeded):
    src = "def complete(tasks, task_id):\n    return __import__('os')\n"
    cand = seeded.client.post("/v1/candidates", json={"source": src}, headers=headers("developer")).json()
    rep = seeded.run_tests(cand["candidate_id"]).json()
    assert rep["outcome"] == "fail"
    first = case(rep, "TC-01")["assertions"][0]
    assert first["passed"] is False and first["actual"]["status"] == "rejected"
    assert all(e["status"] == "rejected" for e in rep["evidence"]["evaluations"])


def test_report_records_suite_hash_runner_version_and_evidence_ids(seeded):
    ref = seeded.load_fixture("reference_complete")
    rep = seeded.run_tests(ref["candidate_id"]).json()
    assert rep["suite_sha256"] == hashlib.sha256((REPO / "services" / "lab" / "testing.py").read_bytes()).hexdigest()
    assert rep["suite_sha256"] == testing.SUITE_SHA256
    assert rep["runner_version"].startswith("tasksprint-runner/")
    ids = rep["evidence"]["evidence_ids"]
    assert len(ids) == len(set(ids)) == len(rep["evidence"]["evaluations"]) >= 6
    assert {i for c in rep["cases"] for i in c["evidence_ids"]} == set(ids)
    assert rep["evidence"]["assertions"]["failed"] == 0 and rep["evidence"]["assertions"]["passed"] > 10


def test_reports_are_immutable_and_readable_by_permitted_roles_only(seeded):
    ref = seeded.load_fixture("reference_complete")
    rep = seeded.run_tests(ref["candidate_id"]).json()
    for role in ("qa", "operations", "coordinator"):
        r = seeded.client.get(f"/v1/test-runs/{rep['test_run_id']}", headers=headers(role))
        assert r.status_code == 200 and r.json()["report_sha256"] == rep["report_sha256"]
    for role in ("developer", "product_owner", "application", "human_approver"):
        assert seeded.client.get(f"/v1/test-runs/{rep['test_run_id']}", headers=headers(role)).status_code == 403
    with seeded.store().write() as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE test_runs SET outcome = 'pass' WHERE test_run_id = ?", (rep["test_run_id"],))
    with seeded.store().write() as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM test_runs WHERE test_run_id = ?", (rep["test_run_id"],))
    again = seeded.client.get(f"/v1/test-runs/{rep['test_run_id']}", headers=headers("qa")).json()
    assert again["report_sha256"] == rep["report_sha256"]


def test_only_qa_can_start_a_run_and_cannot_supply_results(seeded):
    sid = starter_id(seeded)
    for role in ("developer", "operations", "coordinator", "application", "instructor"):
        assert seeded.run_tests(sid, role=role).status_code == 403
    for extra in ({"outcome": "pass"}, {"cases": []}, {"suite_sha256": "0" * 64}, {"passed": True}):
        r = seeded.client.post("/v1/test-runs", json={"candidate_id": sid, **extra}, headers=headers("qa"))
        assert r.status_code == 422


def test_suite_never_touches_canonical_tasks(seeded):
    seeded.cmd("add Canonical record")
    before = seeded.cmd("list").json()["data"]["tasks"]
    ref = seeded.load_fixture("reference_complete")
    assert seeded.run_tests(ref["candidate_id"]).json()["outcome"] == "pass"
    assert seeded.cmd("list").json()["data"]["tasks"] == before


def test_runner_unavailable_is_recorded_as_error_never_pass(db_path):
    lab = Lab(db_path, runner=False)
    lab.seed()
    rep = lab.run_tests(starter_id(lab)).json()
    assert rep["outcome"] == "error" and rep["cases"] == [] and rep["runner_version"] == "unavailable"


def test_unknown_and_cross_workspace_candidates_are_not_found(seeded):
    seeded.seed("demo-002")
    ref = seeded.load_fixture("reference_complete", workspace="demo-002")  # registered only in demo-002
    assert seeded.run_tests("cand_" + "0" * 24).status_code == 404
    assert seeded.run_tests(ref["candidate_id"], workspace="demo-001").status_code == 404
    assert seeded.run_tests(ref["candidate_id"], workspace="demo-002").status_code == 201


def test_tampered_candidate_fails_closed_without_a_report(seeded):
    cand = seeded.client.post("/v1/candidates", json={"source": "def complete(tasks, task_id):\n    return 1\n"},
                              headers=headers("developer")).json()
    with seeded.store().write() as conn:
        conn.execute("DROP TRIGGER candidates_no_update")
        conn.execute("UPDATE candidates SET source = ? WHERE candidate_id = ?",
                     (b"def complete(tasks, task_id):\n    return 2\n", cand["candidate_id"]))
    r = seeded.run_tests(cand["candidate_id"])
    assert r.status_code == 500 and r.json()["error"]["code"] == "ARTIFACT_INTEGRITY_ERROR"
    with seeded.store().read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM test_runs").fetchone()[0] == 0
