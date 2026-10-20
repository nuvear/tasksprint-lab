"""Deterministic To-do App grammar and starter v0 behaviour (Build Guide 02.4)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from services.lab.app_commands import parse
from services.lab.store import LabError
from tests.conftest import headers

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("text,verb,arg", [
    ("add Prepare sprint review", "add", "Prepare sprint review"),
    ("  add   Tidy   spaces  ", "add", "Tidy spaces"),
    ("list", "list", None),
    ("status", "status", None),
    ("complete T001", "complete", "T001"),
    ("COMPLETE T002", "complete", "T002"),
])
def test_grammar_accepts_only_the_four_commands(text, verb, arg):
    cmd = parse(text)
    assert (cmd.verb, cmd.arg) == (verb, arg)


@pytest.mark.parametrize("text,code", [
    ("delete T001", "UNKNOWN_COMMAND"),
    ("run tests", "UNKNOWN_COMMAND"),
    ("SELECT * FROM tasks", "UNKNOWN_COMMAND"),
    ("list everything", "UNEXPECTED_ARGUMENT"),
    ("complete 1; drop table tasks", "INVALID_TASK_ID"),
    ("complete t001", "INVALID_TASK_ID"),
    ("complete", "INVALID_TASK_ID"),
    ("add ", "INVALID_TITLE"),
    ("add " + "x" * 121, "INVALID_TITLE"),
    ("add hello‮evil", "INVALID_TITLE"),
    ("list\nadd x", "COMMAND_TOO_LONG"),
    ("", "UNKNOWN_COMMAND"),
])
def test_grammar_rejects_everything_else(text, code):
    with pytest.raises(LabError) as exc:
        parse(text)
    assert exc.value.code == code


def test_seed_creates_v0_and_two_synthetic_tasks(seeded):
    r = seeded.cmd("list")
    assert r.status_code == 200
    tasks = r.json()["data"]["tasks"]
    assert [(t["id"], t["completed"]) for t in tasks] == [("T001", False), ("T002", False)]


def test_starter_candidate_is_hashed_fixture(seeded):
    starter_bytes = (REPO / "instructor" / "fixtures" / "starter_v0.py").read_bytes()
    expected = hashlib.sha256(starter_bytes).hexdigest()
    rel = seeded.client.get("/v1/releases", headers=headers("operations")).json()
    assert rel["active"]["sha256"] == expected
    assert rel["active"]["origin"] == "fixture"
    assert rel["active"]["release_revision"] == 0
    assert rel["history"][0]["operation"] == "seed"


def test_add_assigns_server_ids_and_list_shows_records(seeded):
    r = seeded.cmd("add Prepare sprint review")
    assert r.status_code == 200 and r.json()["code"] == "ADDED"
    assert r.json()["data"]["task"]["id"] == "T003"
    assert seeded.cmd("add Second").json()["data"]["task"]["id"] == "T004"
    listing = seeded.cmd("list").json()
    assert "T003 [ ] Prepare sprint review" in listing["message"]
    assert len(listing["data"]["tasks"]) == 4


def test_complete_on_v0_is_feature_unavailable_and_changes_nothing(seeded):
    before = seeded.cmd("list").json()["data"]["tasks"]
    r = seeded.cmd("complete T001")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["code"] == "FEATURE_UNAVAILABLE"
    assert body["data"]["artifact"]["sha256"] == seeded.client.get(
        "/v1/releases", headers=headers("application")).json()["active"]["sha256"]
    assert body["data"]["tasks_changed"] == 0
    assert seeded.cmd("list").json()["data"]["tasks"] == before
    # Unknown ID on v0: the starter returns FEATURE_UNAVAILABLE for any input, still no mutation.
    assert seeded.cmd("complete T999").json()["code"] == "FEATURE_UNAVAILABLE"
    assert seeded.cmd("list").json()["data"]["tasks"] == before


def test_status_reports_hash_revision_and_business_health(seeded):
    body = seeded.cmd("status").json()
    assert body["code"] == "STATUS"
    data = body["data"]
    assert len(data["active_sha256"]) == 64
    assert data["release_revision"] == 0
    assert data["status"] == "healthy"
    assert data["features"]["complete"].startswith("FEATURE_UNAVAILABLE")
    assert data["active_sha256"] in body["message"]


def test_non_baseline_active_artifact_is_not_executed(seeded):
    """Phase 02 has no runner: any non-baseline artifact yields RUNNER_UNAVAILABLE, no mutation."""
    sub = seeded.client.post("/v1/candidates", json={"source": "def complete(tasks, task_id):\n    return 1\n"},
                             headers=headers("developer")).json()
    with seeded.store().write() as conn:  # trusted test-only pointer change (no deploy path exists yet)
        conn.execute("UPDATE active_releases SET active_candidate_id = ?, active_sha256 = ? WHERE workspace_id = 'demo-001'",
                     (sub["candidate_id"], sub["sha256"]))
    before = seeded.cmd("list").json()["data"]["tasks"]
    body = seeded.cmd("complete T001").json()
    assert body["code"] == "RUNNER_UNAVAILABLE" and body["ok"] is False
    assert seeded.cmd("list").json()["data"]["tasks"] == before


def test_app_events_are_recorded(seeded):
    seeded.cmd("add Audit me")
    seeded.cmd("complete T001")
    events = seeded.client.get("/v1/events", headers=headers("operations")).json()["events"]
    actions = [(e["action"], e["outcome"]) for e in events]
    assert ("app.add", "ADDED") in actions
    assert ("app.complete", "FEATURE_UNAVAILABLE") in actions
    assert all(e["request_id"].startswith("req_") for e in events)
