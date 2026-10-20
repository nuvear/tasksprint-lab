"""A9 / SEC-13: the run is re-checked INSIDE each write transaction, so a result that arrives after the
run's deadline, a stop/cancel or a workspace reset cannot commit (Phase 07 finding 4, approved)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from services.lab import clock
from services.lab.auth import Identity
from services.lab.schemas import CandidateSubmit, MemorySave, StoryCreate
from services.lab.store import LabError
from tests.conftest import Lab, headers, in_process_runner

SOURCE = "def complete(tasks, task_id):\n    return {'ok': False, 'code': 'TASK_NOT_FOUND', 'tasks': tasks}\n"


def run_for(lab, role):
    r = lab.client.post("/v1/runs", json={"conversation_id": "c1"}, headers=headers(role))
    assert r.status_code == 201
    return r.json()["run_id"]


def count(lab, table):
    with lab.store().read() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.mark.parametrize("change", ["expire", "cancel"])
def test_story_memory_and_candidate_writes_recheck_the_run(seeded, change):
    ops = seeded.app.state.ops
    cases = (("coordinator", "stories", lambda c: ops.record_story(c, StoryCreate(title="t", narrative="n",
                                                                                   criteria=["c"]))),
             ("coordinator", "memories", lambda c: ops.save_memory(c, MemorySave(key="summary_length", value="short"))),
             ("developer", "candidates", lambda c: ops.submit_candidate(c, CandidateSubmit(source=SOURCE))))
    for role, table, write in cases:
        clock.reset_for_tests()
        run = run_for(seeded, role)
        c = ops.bind(Identity(role), "demo-001", run, "req_test")  # admitted while live
        if change == "expire":
            clock.advance_for_tests(timedelta(seconds=200))
        else:
            with seeded.store().write() as conn:
                conn.execute("UPDATE runs SET status = 'cancelled' WHERE run_id = ?", (run,))
        before = count(seeded, table)
        with pytest.raises(LabError) as exc:
            write(c)
        assert exc.value.code == ("RUN_EXPIRED" if change == "expire" else "RUN_NOT_ACTIVE"), table
        assert count(seeded, table) == before, table


class SlowRunner:
    """Runner wrapper: the run's deadline passes while the protected suite is being evaluated."""

    def __init__(self, inner, delay_s: int):
        self.inner, self.delay_s, self.advanced = inner, delay_s, False

    def evaluate(self, **kw):
        if not self.advanced:
            self.advanced = True
            clock.advance_for_tests(timedelta(seconds=self.delay_s))
        return self.inner.evaluate(**kw)


def test_test_run_admitted_before_deadline_cannot_commit_after_it(db_path):
    lab = Lab(db_path, runner=SlowRunner(in_process_runner(), 200))
    lab.seed()
    ref = lab.load_fixture("reference_complete")
    run = run_for(lab, "qa")
    r = lab.client.post("/v1/test-runs", json={"candidate_id": ref["candidate_id"]}, headers=headers("qa", run=run))
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_EXPIRED"
    assert "re-checked at commit" in r.json()["error"]["message"]
    assert count(lab, "test_runs") == 0
    ev = lab.client.get("/v1/events", headers=headers("qa")).json()["events"][0]
    assert ev["action"] == "test_run.create" and ev["outcome"] == "rejected"


def test_live_run_still_commits(seeded):
    ref = seeded.load_fixture("reference_complete")
    run = run_for(seeded, "qa")
    r = seeded.client.post("/v1/test-runs", json={"candidate_id": ref["candidate_id"]}, headers=headers("qa", run=run))
    assert r.status_code == 201 and r.json()["evidence"]["run_id"] == run
