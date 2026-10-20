"""Sprint stage machine, evidence preconditions and optimistic concurrency (A5, SEC-10)."""
from __future__ import annotations

import json
import threading

from services.lab.state import StateWriter
from tests.conftest import headers

STORY = {"title": "Complete a task", "narrative": "As a participant I want to mark a task complete while keeping it.",
         "criteria": ["AC1 completed task retained", "AC4 unknown ID returns TASK_NOT_FOUND"],
         "evidence_refs": ["tasksprint-product-brief@1.0"]}


def make_story(lab):
    r = lab.client.post("/v1/stories", json=STORY, headers=headers("coordinator"))
    assert r.status_code == 201, r.text
    return r.json()


def transition(lab, story, to, rev, **extra):
    return lab.client.post("/v1/state/transitions", headers=headers("coordinator"),
                           json={"story_id": story["story_id"], "to_stage": to, "expected_revision": rev, **extra})


def confirm_scope(lab, story_id, rev):
    with lab.store().write() as conn:  # trusted human-only path; no model route exists in Phase 02
        return StateWriter(conn, "req_test", "instructor").confirm_scope("demo-001", story_id, rev)


def submit(lab, src="def complete(tasks, task_id):\n    return {'ok': False, 'code': 'X', 'tasks': tasks}\n"):
    r = lab.client.post("/v1/candidates", json={"source": src}, headers=headers("developer"))
    assert r.status_code == 201, r.text
    return r.json()


def add_test_run(lab, cand, outcome, run_id):
    with lab.store().write() as conn:  # trusted testing code stand-in (Phase 03 builds the real one)
        conn.execute("INSERT INTO test_runs(test_run_id, workspace_id, candidate_id, candidate_sha256, suite_sha256,"
                     " cases_json, outcome, runner_version, evidence_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (run_id, "demo-001", cand["candidate_id"], cand["sha256"], "0" * 64, "[]", outcome, "test",
                      "{}", "2026-10-20T00:00:00Z"))


def test_story_starts_planned_with_revision_1(seeded):
    s = make_story(seeded)
    assert (s["story_id"], s["stage"], s["revision"], s["scope_confirmed"]) == ("ST-001", "PLANNED", 1, False)


def test_development_requires_human_scope_confirmation(seeded):
    s = make_story(seeded)
    r = transition(seeded, s, "IN_DEVELOPMENT", 1)
    assert r.status_code == 409 and r.json()["error"]["code"] == "SCOPE_NOT_CONFIRMED"
    confirm_scope(seeded, s["story_id"], 1)
    r = transition(seeded, s, "IN_DEVELOPMENT", 2)
    assert r.status_code == 200 and r.json()["stage"] == "IN_DEVELOPMENT" and r.json()["revision"] == 3


def test_illegal_transitions_are_rejected(seeded):
    s = make_story(seeded)
    for to in ("IN_QA", "APP_VERIFIED", "READY_FOR_REVIEW", "CLOSED", "CHANGES_REQUESTED"):
        r = transition(seeded, s, to, 1)
        assert r.status_code == 409 and r.json()["error"]["code"] == "ILLEGAL_TRANSITION", to
    assert transition(seeded, s, "DEPLOYED", 1).status_code == 422  # not a sprint stage at all


def test_stale_revision_is_a_conflict_and_changes_nothing(seeded):
    s = make_story(seeded)
    confirm_scope(seeded, s["story_id"], 1)
    r = transition(seeded, s, "IN_DEVELOPMENT", 1)  # stale: current is 2
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "REVISION_CONFLICT" and err["details"]["current_revision"] == 2
    st = seeded.client.get("/v1/state", headers=headers("coordinator")).json()["stories"][0]
    assert (st["stage"], st["revision"]) == ("PLANNED", 2)
    events = seeded.client.get("/v1/events", headers=headers("coordinator")).json()["events"]
    assert any(e["action"] == "story.transition" and e["outcome"] == "rejected"
               and e["details"].get("code") == "REVISION_CONFLICT" for e in events)


def test_simultaneous_writers_one_wins_no_silent_loss(seeded):
    s = make_story(seeded)
    confirm_scope(seeded, s["story_id"], 1)
    results: list[int] = []

    def worker():
        results.append(transition(seeded, s, "IN_DEVELOPMENT", 2).status_code)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200] + [409] * 5
    st = seeded.client.get("/v1/state", headers=headers("coordinator")).json()["stories"][0]
    assert st["revision"] == 3


def test_qa_entry_requires_existing_candidate(seeded):
    s = make_story(seeded)
    confirm_scope(seeded, s["story_id"], 1)
    transition(seeded, s, "IN_DEVELOPMENT", 2)
    assert transition(seeded, s, "IN_QA", 3).json()["error"]["code"] == "CANDIDATE_REQUIRED"
    assert transition(seeded, s, "IN_QA", 3, candidate_id="cand_" + "0" * 24).json()["error"]["code"] == "UNKNOWN_CANDIDATE"
    cand = submit(seeded)
    r = transition(seeded, s, "IN_QA", 3, candidate_id=cand["candidate_id"])
    assert r.status_code == 200 and r.json()["candidate_id"] == cand["candidate_id"]


def test_verification_requires_trusted_passing_evidence_for_exact_candidate(seeded):
    s = make_story(seeded)
    confirm_scope(seeded, s["story_id"], 1)
    transition(seeded, s, "IN_DEVELOPMENT", 2)
    cand = submit(seeded)
    transition(seeded, s, "IN_QA", 3, candidate_id=cand["candidate_id"])
    # No evidence, or a caller-invented ID: refused.
    assert transition(seeded, s, "APP_VERIFIED", 4).json()["error"]["code"] == "EVIDENCE_REQUIRED"
    assert transition(seeded, s, "APP_VERIFIED", 4, test_run_id="tr_invented").json()["error"]["code"] == "EVIDENCE_REQUIRED"
    # A failing run cannot verify; a passing run for a different candidate cannot either.
    add_test_run(seeded, cand, "fail", "tr_fail")
    assert transition(seeded, s, "APP_VERIFIED", 4, test_run_id="tr_fail").json()["error"]["code"] == "EVIDENCE_REQUIRED"
    other = submit(seeded, "def complete(tasks, task_id):\n    return {'ok': True, 'code': 'Y', 'tasks': tasks}\n")
    add_test_run(seeded, other, "pass", "tr_other")
    assert transition(seeded, s, "APP_VERIFIED", 4, test_run_id="tr_other").json()["error"]["code"] == "EVIDENCE_REQUIRED"
    add_test_run(seeded, cand, "pass", "tr_pass")
    r = transition(seeded, s, "APP_VERIFIED", 4, test_run_id="tr_pass")
    assert r.status_code == 200 and "tr_pass" in r.json()["evidence_refs"]


def test_one_repair_then_escalate_and_closing_needs_human_review(seeded):
    s = make_story(seeded)
    confirm_scope(seeded, s["story_id"], 1)
    rev = transition(seeded, s, "IN_DEVELOPMENT", 2).json()["revision"]
    cand = submit(seeded)
    rev = transition(seeded, s, "IN_QA", rev, candidate_id=cand["candidate_id"]).json()["revision"]
    add_test_run(seeded, cand, "fail", "tr_f1")
    rev = transition(seeded, s, "CHANGES_REQUESTED", rev, test_run_id="tr_f1").json()["revision"]
    r = transition(seeded, s, "IN_DEVELOPMENT", rev)
    assert r.json()["repair_count"] == 1
    rev = r.json()["revision"]
    rev = transition(seeded, s, "IN_QA", rev, candidate_id=cand["candidate_id"]).json()["revision"]
    rev = transition(seeded, s, "CHANGES_REQUESTED", rev, test_run_id="tr_f1").json()["revision"]
    r = transition(seeded, s, "IN_DEVELOPMENT", rev)
    assert r.status_code == 409 and r.json()["error"]["code"] == "REPAIR_BUDGET_EXHAUSTED"
    # Separate story to reach READY_FOR_REVIEW and attempt CLOSED.
    s2 = make_story(seeded)
    confirm_scope(seeded, s2["story_id"], 1)
    rev = transition(seeded, s2, "IN_DEVELOPMENT", 2).json()["revision"]
    rev = transition(seeded, s2, "IN_QA", rev, candidate_id=cand["candidate_id"]).json()["revision"]
    add_test_run(seeded, cand, "pass", "tr_p2")
    rev = transition(seeded, s2, "APP_VERIFIED", rev, test_run_id="tr_p2").json()["revision"]
    rev = transition(seeded, s2, "READY_FOR_REVIEW", rev).json()["revision"]
    r = transition(seeded, s2, "CLOSED", rev)
    assert r.status_code == 409 and r.json()["error"]["code"] == "HUMAN_REVIEW_REQUIRED"


def test_test_runs_are_append_only(seeded):
    import sqlite3
    import pytest
    cand = submit(seeded)
    add_test_run(seeded, cand, "fail", "tr_x")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with seeded.store().write() as conn:
            conn.execute("UPDATE test_runs SET outcome = 'pass' WHERE test_run_id = 'tr_x'")
