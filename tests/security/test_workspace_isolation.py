"""Workspace isolation: data, runs, candidates and seeding are namespace-bound."""
from __future__ import annotations

from tests.conftest import headers


def test_tasks_do_not_leak_between_workspaces(seeded):
    seeded.seed("demo-002")
    seeded.cmd("add Only in one", workspace="demo-001")
    one = seeded.cmd("list", workspace="demo-001").json()["data"]["tasks"]
    two = seeded.cmd("list", workspace="demo-002").json()["data"]["tasks"]
    assert any(t["title"] == "Only in one" for t in one)
    assert all(t["title"] != "Only in one" for t in two)
    assert len(two) == 2


def test_candidates_are_not_visible_across_workspaces(seeded):
    seeded.seed("demo-002")
    cid = seeded.client.post("/v1/candidates", json={"source": "def complete(tasks, task_id):\n    return 2\n"},
                             headers=headers("developer", "demo-001")).json()["candidate_id"]
    r = seeded.client.get(f"/v1/candidates/{cid}", headers=headers("qa", "demo-002"))
    assert r.status_code == 404


def test_stories_and_events_are_workspace_scoped(seeded):
    seeded.seed("demo-002")
    seeded.client.post("/v1/stories", json={"title": "t", "narrative": "n", "criteria": ["a"]},
                       headers=headers("coordinator", "demo-001"))
    assert seeded.client.get("/v1/state", headers=headers("coordinator", "demo-002")).json()["stories"] == []
    ev2 = seeded.client.get("/v1/events", headers=headers("operations", "demo-002")).json()["events"]
    assert all(e["action"] != "story.create" for e in ev2)


def test_unknown_or_missing_workspace_is_refused(seeded):
    assert seeded.cmd("list", workspace="demo-404").json()["error"]["code"] == "WORKSPACE_NOT_FOUND"
    r = seeded.client.post("/v1/app/commands", json={"command": "list"}, headers=headers("application", None))
    assert r.json()["error"]["code"] == "WORKSPACE_REQUIRED"
    r = seeded.client.post("/v1/app/commands", json={"command": "list"},
                           headers=headers("application", "../../etc"))
    assert r.json()["error"]["code"] == "WORKSPACE_REQUIRED"


def test_body_cannot_select_workspace(seeded):
    seeded.seed("demo-002")
    r = seeded.client.post("/v1/app/commands", json={"command": "add x", "workspace_id": "demo-002"},
                           headers=headers("application", "demo-001"))
    assert r.status_code == 422
    assert len(seeded.cmd("list", workspace="demo-002").json()["data"]["tasks"]) == 2


def test_only_designated_workspaces_can_be_seeded(seeded):
    r = seeded.client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": "prod-001"},
                           headers=headers("instructor", None))
    assert r.status_code == 403 and r.json()["error"]["code"] == "WORKSPACE_NOT_DESIGNATED"
    r = seeded.client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": "demo-001"},
                           headers=headers("instructor", None))
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_SEEDED"


def test_demo_actions_require_demo_mode(db_path):
    from tests.conftest import Lab
    lab = Lab(db_path, demo_enabled=False)
    r = lab.client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": "demo-001"},
                        headers=headers("instructor", None))
    assert r.status_code == 403 and r.json()["error"]["code"] == "DEMO_DISABLED"


def test_reset_preview_is_read_only(seeded):
    seeded.cmd("add One more")
    before = seeded.cmd("list").json()["data"]["tasks"]
    r = seeded.client.post("/v1/instructor/actions", json={"action": "reset_preview", "workspace_id": "demo-001"},
                           headers=headers("instructor", None))
    assert r.status_code == 200
    assert r.json()["counts"]["tasks"] == 3 and r.json()["mutation"].startswith("none")
    assert seeded.cmd("list").json()["data"]["tasks"] == before
