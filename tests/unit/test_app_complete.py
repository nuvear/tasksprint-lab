"""`complete <ID>` interprets the active artifact through the runner (A6; APP-01..APP-04, APP-07)."""
from __future__ import annotations

from typing import Any

from services.lab.runner_client import RunnerClient
from tests.conftest import Lab, headers, in_process_runner


def activate_source(lab: Lab, source: str) -> dict:
    cand = lab.client.post("/v1/candidates", json={"source": source}, headers=headers("developer")).json()
    lab.activate(cand)
    return cand


def tasks(lab: Lab) -> list[dict]:
    return lab.cmd("list").json()["data"]["tasks"]


def test_v0_complete_is_interpreted_feature_unavailable(seeded):
    before = tasks(seeded)
    body = seeded.cmd("complete T001").json()
    assert body["code"] == "FEATURE_UNAVAILABLE" and body["ok"] is False
    ev = body["data"]["evaluation"]
    assert ev["evaluated_by"].startswith("tasksprint-runner/") and ev["status"] == "ok" and ev["ops"] > 0
    assert ev["interpreted_sha256"] == body["data"]["artifact"]["sha256"]  # APP-07: the active hash was executed
    assert tasks(seeded) == before


def test_reference_completes_retains_and_is_idempotent(seeded):
    seeded.cmd("add Third task")
    seeded.activate(seeded.load_fixture("reference_complete"))
    before = {t["id"]: t for t in tasks(seeded)}
    body = seeded.cmd("complete T002").json()
    assert body["ok"] is True and body["code"] == "COMPLETED" and body["data"]["tasks_changed"] == 1
    after = {t["id"]: t for t in tasks(seeded)}
    assert after["T002"]["completed"] is True and after["T002"]["title"] == before["T002"]["title"]
    assert after["T002"]["revision"] == before["T002"]["revision"] + 1
    assert {k: v for k, v in after.items() if k != "T002"} == {k: v for k, v in before.items() if k != "T002"}
    again = seeded.cmd("complete T002").json()
    assert again["ok"] is True and again["data"]["tasks_changed"] == 0
    assert {t["id"]: t for t in tasks(seeded)} == after
    unknown = seeded.cmd("complete T999").json()
    assert unknown["code"] == "TASK_NOT_FOUND" and unknown["ok"] is False
    assert {t["id"]: t for t in tasks(seeded)} == after
    listing = seeded.cmd("list").json()["message"]  # APP-06: completed and incomplete both visible
    assert "T002 [x]" in listing and "T001 [ ]" in listing


def test_faulty_result_is_never_committed(seeded):
    seeded.activate(seeded.load_fixture("faulty_delete"))
    before = tasks(seeded)
    body = seeded.cmd("complete T001").json()
    assert body["code"] == "CANDIDATE_RESULT_REJECTED" and body["ok"] is False
    assert "dropped ['T001']" in body["message"]
    assert tasks(seeded) == before


def test_forbidden_and_exhausting_candidates_change_nothing(seeded):
    before = tasks(seeded)
    activate_source(seeded, "def complete(tasks, task_id):\n    return open('/etc/passwd')\n")
    body = seeded.cmd("complete T001").json()
    assert body["code"] == "CANDIDATE_REJECTED" and body["data"]["candidate_error"]["code"] == "FORBIDDEN_SYNTAX"
    wide = ", ".join(["t"] * 60)
    for i in range(3, 101):
        seeded.cmd(f"add Task {i}")
    before = tasks(seeded)
    activate_source(seeded, f"def complete(tasks, task_id):\n    for t in tasks:\n        x = [{wide}]\n    return x\n")
    body = seeded.cmd("complete T001").json()
    assert body["code"] == "CANDIDATE_FAILED" and body["data"]["candidate_error"]["code"] == "OP_LIMIT_EXCEEDED"
    assert tasks(seeded) == before


def test_runner_unconfigured_changes_nothing(db_path):
    lab = Lab(db_path, runner=False)
    lab.seed()
    before = tasks(lab)
    body = lab.cmd("complete T001").json()
    assert body["code"] == "RUNNER_UNAVAILABLE" and tasks(lab) == before


class StubRunner(RunnerClient):
    """Wraps the real in-process runner; can run a side effect or tamper with the response."""

    def __init__(self, side_effect=None, tamper=None):
        self.inner = in_process_runner()
        self.side_effect, self.tamper = side_effect, tamper

    def evaluate(self, **kw: Any) -> dict:
        doc = self.inner.evaluate(**kw)
        if self.side_effect:
            self.side_effect()
        return self.tamper(doc) if self.tamper else doc


def stub_lab(db_path, **kw) -> Lab:
    stub = StubRunner(**kw)
    lab = Lab(db_path, runner=stub)
    lab.seed()
    lab.activate(lab.load_fixture("reference_complete"))
    return lab


def test_concurrent_task_change_during_evaluation_is_a_conflict(db_path):
    holder: dict = {}
    lab = stub_lab(db_path, side_effect=lambda: holder["lab"].cmd("add Sneaked in during evaluation"))
    holder["lab"] = lab
    before = {t["id"]: t["completed"] for t in tasks(lab)}
    r = lab.cmd("complete T001")
    assert r.status_code == 409 and r.json()["error"]["code"] == "REVISION_CONFLICT"
    after = {t["id"]: t["completed"] for t in tasks(lab)}
    assert after["T001"] is False and set(after) == set(before) | {"T003"}  # the other write was not lost


def test_active_artifact_change_during_evaluation_is_a_conflict(db_path):
    holder: dict = {}

    def switch():
        lab = holder["lab"]
        with lab.store().write() as conn:
            conn.execute("UPDATE active_releases SET release_revision = release_revision + 1")

    lab = stub_lab(db_path, side_effect=switch)
    holder["lab"] = lab
    r = lab.cmd("complete T001")
    assert r.status_code == 409 and tasks(lab)[0]["completed"] is False


def test_runner_cannot_write_task_data_by_altering_its_answer(db_path):
    def tamper(doc):
        doc["result"]["tasks"][1]["title"] = "Overwritten by runner"
        return doc

    lab = stub_lab(db_path, tamper=tamper)
    before = tasks(lab)
    body = lab.cmd("complete T001").json()
    assert body["code"] == "CANDIDATE_RESULT_REJECTED" and tasks(lab) == before


def test_runner_answer_for_a_different_source_hash_is_refused(db_path):
    lab = Lab(db_path, runner=RunnerClient("http://runner.invalid", "x" * 40, http=_TamperingHttp()))
    lab.seed()
    before = tasks(lab)
    assert lab.cmd("complete T001").json()["code"] == "RUNNER_UNAVAILABLE"
    assert tasks(lab) == before


class _TamperingHttp:
    """httpx-like object returning a well-formed envelope for the wrong source hash."""

    def post(self, path, json, headers):  # noqa: A002 - mirrors httpx signature
        import httpx
        return httpx.Response(200, json={"status": "ok", "runner_version": "x", "grammar_version": "y",
                                         "source_sha256": "f" * 64, "result": json["tasks"], "error": None,
                                         "ops": 1, "elapsed_ms": 0, "limits": {}})


def test_complete_events_record_runner_and_hash(seeded):
    seeded.cmd("complete T001")
    events = seeded.client.get("/v1/events", headers=headers("operations")).json()["events"]
    ev = next(e for e in events if e["action"] == "app.complete")
    assert ev["outcome"] == "FEATURE_UNAVAILABLE"
    assert ev["details"]["runner"].startswith("tasksprint-runner/") and len(ev["details"]["artifact_sha256"]) == 64
