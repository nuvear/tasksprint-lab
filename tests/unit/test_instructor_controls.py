"""Phase 09 instructor controls (A8 /v1/instructor/actions, A9 kill switch, A12 drills and reset; REC-01, REC-03)."""
from __future__ import annotations

from datetime import timedelta

from services.lab import clock
from tests.conftest import eval_report, headers


def act(lab, action, workspace="demo-001", role="instructor", **fields):
    return lab.client.post("/v1/instructor/actions", json={"action": action, "workspace_id": workspace, **fields},
                           headers=headers(role, None))


def story(lab, role="coordinator"):
    r = lab.client.post("/v1/stories", json={"title": "Complete a task", "narrative": "As a user...",
                                             "criteria": ["completed tasks stay listed"]}, headers=headers(role))
    assert r.status_code == 201, r.text
    return r.json()


def state(lab):
    return lab.client.get("/v1/state", headers=headers("coordinator")).json()


def transition(lab, story_id, to, rev, **extra):
    return lab.client.post("/v1/state/transitions", json={"story_id": story_id, "to_stage": to,
                                                          "expected_revision": rev, **extra},
                           headers=headers("coordinator"))


def test_confirm_scope_is_instructor_only_and_once(seeded):
    st = story(seeded)
    assert transition(seeded, st["story_id"], "IN_DEVELOPMENT", 1).json()["error"]["code"] == "SCOPE_NOT_CONFIRMED"
    for role in ("coordinator", "product_owner", "developer", "qa", "operations", "application", "human_approver"):
        assert act(seeded, "confirm_scope", role=role, story_id=st["story_id"]).status_code == 403, role
    r = act(seeded, "confirm_scope", story_id=st["story_id"])
    assert r.status_code == 200 and r.json()["story"]["scope_confirmed"] is True
    assert act(seeded, "confirm_scope", story_id=st["story_id"]).json()["error"]["code"] == "SCOPE_ALREADY_CONFIRMED"
    assert transition(seeded, st["story_id"], "IN_DEVELOPMENT", 2).status_code == 200


def test_cross_turn_repair_limit_after_scope_confirmation(seeded):
    """One automatic repair per story, enforced by repair_count across turns/sessions."""
    faulty = seeded.load_fixture("faulty_delete")
    fail1 = seeded.run_tests(faulty["candidate_id"]).json()["test_run_id"]
    st = story(seeded)
    sid = st["story_id"]
    act(seeded, "confirm_scope", story_id=sid)
    rev = 2
    for to, extra in (("IN_DEVELOPMENT", {}), ("IN_QA", {"candidate_id": faulty["candidate_id"]}),
                      ("CHANGES_REQUESTED", {"test_run_id": fail1}), ("IN_DEVELOPMENT", {}),
                      ("IN_QA", {"candidate_id": faulty["candidate_id"]}),
                      ("CHANGES_REQUESTED", {"test_run_id": fail1})):
        r = transition(seeded, sid, to, rev, **extra)
        assert r.status_code == 200, (to, r.text)
        rev = r.json()["revision"]
    assert r.json()["repair_count"] == 1
    r = transition(seeded, sid, "IN_DEVELOPMENT", rev)
    assert r.status_code == 409 and r.json()["error"]["code"] == "REPAIR_BUDGET_EXHAUSTED"


def test_drill_targets_only_the_active_candidate_and_expires(seeded):
    starter = seeded.client.get("/v1/releases", headers=headers("operations")).json()["active"]["candidate_id"]
    faulty = seeded.load_fixture("faulty_delete")
    r = act(seeded, "drill_enable", fault_type="completion_unavailable", candidate_id=faulty["candidate_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "DRILL_TARGET_NOT_ACTIVE"
    assert act(seeded, "drill_enable", fault_type="completion_unavailable", candidate_id=starter,
               ttl_minutes=31).status_code == 422
    r = act(seeded, "drill_enable", fault_type="completion_unavailable", candidate_id=starter, ttl_minutes=5)
    assert r.status_code == 200 and r.json()["app_health"] == "degraded"
    assert seeded.client.get("/healthz").json()["status"] == "ok"  # REC-01: liveness stays healthy
    assert seeded.cmd("complete T001").json()["code"] == "COMPLETION_UNAVAILABLE_DRILL"
    again = act(seeded, "drill_enable", fault_type="completion_unavailable", candidate_id=starter)
    assert again.json()["created"] is False
    clock.advance_for_tests(timedelta(minutes=6))
    assert seeded.client.get("/v1/app-health", headers=headers("operations")).json()["status"] == "healthy"
    act(seeded, "drill_enable", fault_type="completion_unavailable", candidate_id=starter)
    off = act(seeded, "drill_disable", fault_type="completion_unavailable", candidate_id=starter)
    assert off.json()["disabled"] >= 1 and off.json()["app_health"] == "healthy"


def test_unexpected_fields_per_action_are_rejected(seeded):
    assert act(seeded, "stop", fixture="faulty_delete").json()["error"]["code"] == "UNEXPECTED_FIELD"
    assert act(seeded, "seed", confirm="demo-001").json()["error"]["code"] == "UNEXPECTED_FIELD"
    assert act(seeded, "drill_enable", fault_type="delete_everything").status_code == 422
    assert act(seeded, "reset_confirm", workspace="demo-003", confirm="demo-003").json()["error"]["code"] == \
        "WORKSPACE_NOT_DESIGNATED"


def test_stop_cancels_runs_and_refuses_new_ones_until_resume(seeded):
    run = seeded.client.post("/v1/runs", json={"conversation_id": "c1"}, headers=headers("coordinator")).json()
    r = act(seeded, "stop", reason="instructor kill switch")
    assert r.status_code == 200 and run["run_id"] in r.json()["cancelled_runs"]
    nr = seeded.client.post("/v1/runs", json={"conversation_id": "c2"}, headers=headers("coordinator"))
    assert nr.status_code == 409 and nr.json()["error"]["code"] == "WORKSPACE_STOPPED"
    late = seeded.client.post("/v1/stories", json={"title": "t", "narrative": "n", "criteria": ["c"]},
                              headers=headers("coordinator", run=run["run_id"]))
    assert late.status_code == 409 and late.json()["error"]["code"] in ("WORKSPACE_STOPPED", "RUN_NOT_ACTIVE")
    assert act(seeded, "resume").json()["stopped"] is False
    late = seeded.client.post("/v1/stories", json={"title": "t", "narrative": "n", "criteria": ["c"]},
                              headers=headers("coordinator", run=run["run_id"]))
    assert late.json()["error"]["code"] == "RUN_NOT_ACTIVE"  # cancelled runs stay cancelled
    assert state(seeded)["stories"] == []


def test_reset_requires_confirmation_and_is_repeatable_and_scoped(lab):
    lab.seed("demo-001")
    lab.seed("demo-002")
    lab.cmd("add Other workspace task", "demo-002")
    other_before = lab.cmd("list", "demo-002").json()["data"]["tasks"]
    lab.cmd("add Extra")
    story(lab)
    lab.client.post("/v1/memory", json={"key": "summary_length", "value": "short"}, headers=headers("coordinator"))
    act(lab, "stop")
    prev = act(lab, "reset_preview").json()
    assert prev["counts"]["tasks"] == 3 and prev["stopped"] is True and prev["mutation"].startswith("none")
    assert act(lab, "reset_confirm").json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert act(lab, "reset_confirm", confirm="demo-002").json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    first = act(lab, "reset_confirm", confirm="demo-001")
    assert first.status_code == 200, first.text
    after1 = (lab.cmd("list").json()["data"]["tasks"], state(lab)["stories"],
              lab.client.get("/v1/memory", headers=headers("coordinator")).json())
    second = act(lab, "reset_confirm", confirm="demo-001").json()
    after2 = (lab.cmd("list").json()["data"]["tasks"], state(lab)["stories"],
              lab.client.get("/v1/memory", headers=headers("coordinator")).json())
    assert after1 == after2  # REC-03: same clean start
    assert [t["id"] for t in after1[0]] == ["T001", "T002"] and not any(t["completed"] for t in after1[0])
    assert after1[1] == []
    assert second["generation"] == first.json()["generation"] + 1
    assert lab.cmd("add New").json()["data"]["task"]["id"] == "T003"
    assert lab.client.post("/v1/runs", json={"conversation_id": "x"}, headers=headers("coordinator")).status_code == 201
    assert lab.cmd("list", "demo-002").json()["data"]["tasks"] == other_before  # other workspace untouched
    with lab.store().read() as conn:
        exp = conn.execute("SELECT COUNT(*), MIN(length(export_sha256)) FROM workspace_exports").fetchone()
    assert exp[0] == 2 and exp[1] == 64


def test_reset_restores_v0_when_another_version_is_active(seeded):
    ref = seeded.load_fixture("reference_complete")
    seeded.activate(ref)  # TRUSTED TEST-ONLY pointer change
    r = act(seeded, "reset_confirm", confirm="demo-001").json()
    assert r["restored_v0_release_id"].startswith("rel_")
    st = seeded.client.get("/v1/releases", headers=headers("operations")).json()
    assert st["active"]["label"] == "starter-v0" and st["active"]["release_revision"] == 1


def test_evaluator_route_is_evaluator_only_and_the_server_computes_the_verdict(seeded):
    """Phase 10 replaced the Phase 09 stub: a partial report is stored but cannot qualify a manifest."""
    body = eval_report(purpose="partial", cases=["AE-01"], repetitions=1)
    for role in ("coordinator", "developer", "qa", "operations", "instructor", "human_approver"):
        assert seeded.client.post("/v1/agent-evaluations", json=body, headers=headers(role)).status_code == 403
    r = seeded.client.post("/v1/agent-evaluations", json=body, headers=headers("evaluator"))
    assert r.status_code == 201 and r.json()["verdict"] == "NOT_QUALIFIED"
    assert seeded.client.post("/v1/agent-evaluations", json={**body, "qualified": True},
                              headers=headers("evaluator")).status_code == 422
    ready = seeded.client.get("/v1/readiness", headers=headers("operations")).json()
    assert {g["gate"]: g["status"] for g in ready["gates"]}["agent_system_manifest"] == "NOT_QUALIFIED"
