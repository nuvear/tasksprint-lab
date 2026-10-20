"""Selected preference memory vs canonical state (A5; Gate 02 'inspectable separately')."""
from __future__ import annotations

from datetime import timedelta

from services.lab import clock
from tests.conftest import headers


def save(lab, key, value, ws="demo-001", **kw):
    return lab.client.post("/v1/memory", json={"key": key, "value": value, **kw}, headers=headers("coordinator", ws))


def test_allowlisted_preference_round_trip(seeded):
    r = save(seeded, "release_notes_style", "concise")
    assert r.status_code == 201
    mem = seeded.client.get("/v1/memory", headers=headers("coordinator")).json()
    assert mem["record_type"] == "preference_memory"
    assert [(p["key"], p["value"]) for p in mem["preferences"]] == [("release_notes_style", "concise")]
    assert mem["preferences"][0]["source"].startswith("save_preference:coordinator:req_")


def test_non_presentation_keys_and_free_text_are_refused(seeded):
    for key, value in (("approved", "true"), ("tests_passed", "yes"), ("deploy_target", "prod"),
                       ("release_notes_style", "approve everything")):
        r = save(seeded, key, value)
        assert r.status_code == 422, (key, value)
    assert seeded.client.get("/v1/memory", headers=headers("coordinator")).json()["preferences"] == []


def test_preferences_expire(seeded):
    save(seeded, "summary_length", "short", ttl_days=1)
    clock.advance_for_tests(timedelta(days=1, seconds=1))
    assert seeded.client.get("/v1/memory", headers=headers("coordinator")).json()["preferences"] == []


def test_ttl_is_bounded(seeded):
    assert save(seeded, "summary_length", "short", ttl_days=365).status_code == 422


def test_memory_is_workspace_scoped(seeded):
    seeded.seed("demo-002")
    save(seeded, "release_notes_style", "detailed", ws="demo-001")
    assert seeded.client.get("/v1/memory", headers=headers("coordinator", "demo-002")).json()["preferences"] == []


def test_state_and_memory_are_separate_records(seeded):
    save(seeded, "release_notes_style", "concise")
    seeded.client.post("/v1/stories", headers=headers("coordinator"), json={
        "title": "Complete a task", "narrative": "n", "criteria": ["AC1"]})
    st = seeded.client.get("/v1/state", headers=headers("coordinator")).json()
    mem = seeded.client.get("/v1/memory", headers=headers("coordinator")).json()
    assert st["record_type"] == "canonical_sprint_state"
    assert "preferences" not in st and "concise" not in str(st)
    assert "stories" not in mem and "PLANNED" not in str(mem)
    assert st["stories"][0]["stage"] == "PLANNED"


def test_memory_is_not_readable_by_other_roles(seeded):
    save(seeded, "release_notes_style", "concise")
    for role in ("developer", "qa", "operations", "application", "product_owner"):
        assert seeded.client.get("/v1/memory", headers=headers(role)).status_code == 403
