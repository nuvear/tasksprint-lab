"""Source-byte provenance, base-hash diffs and Developer read rules (Build Guide 03.2, A6)."""
from __future__ import annotations

import sqlite3

import pytest

from services.lab.candidates import put_candidate
from services.lab.store import LabError
from tests.conftest import headers

STARTER_EDIT = ("# Instructor fixture: known healthy baseline. Not a current-feature implementation.\n"
                "def complete(tasks, task_id):\n"
                "    for task in tasks:\n"
                "        if task[\"id\"] == task_id:\n"
                "            task[\"completed\"] = True\n"
                "            return {\"ok\": True, \"code\": \"COMPLETED\", \"tasks\": tasks}\n"
                "    return {\"ok\": False, \"code\": \"TASK_NOT_FOUND\", \"tasks\": tasks}\n")


def starter(lab) -> dict:
    return lab.client.get("/v1/releases", headers=headers("operations")).json()["active"]


def submit(lab, source, base=None):
    body = {"source": source} | ({"base_sha256": base} if base else {})
    return lab.client.post("/v1/candidates", json=body, headers=headers("developer"))


def test_read_includes_verified_provenance_and_diff_from_base(seeded):
    cand = submit(seeded, STARTER_EDIT, base=starter(seeded)["sha256"]).json()
    view = seeded.client.get(f"/v1/candidates/{cand['candidate_id']}", headers=headers("developer")).json()
    assert view["provenance"] == {"origin": "agent-generated", "author_role": "developer",
                                  "base_sha256": starter(seeded)["sha256"], "sha256_verified": True}
    diff = view["base_diff"]["diff"]
    assert diff.startswith("--- cand_") and "-    return {\"ok\": False, \"code\": \"FEATURE_UNAVAILABLE\"" in diff
    assert "+            task[\"completed\"] = True" in diff and view["base_diff"]["withheld"] is None


def test_candidate_without_base_has_no_diff(seeded):
    cand = submit(seeded, "def complete(tasks, task_id):\n    return 1\n").json()
    view = seeded.client.get(f"/v1/candidates/{cand['candidate_id']}", headers=headers("qa")).json()
    assert view["base_diff"] == {"base_sha256": None, "diff": None, "withheld": None}


def test_reference_fixture_cannot_be_used_as_a_diff_base(seeded):
    ref = seeded.load_fixture("reference_complete")
    r = submit(seeded, "def complete(tasks, task_id):\n    return 1\n", base=ref["sha256"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_BASE"  # same answer as a missing base
    assert "def complete" not in r.text


def test_unselected_faulty_fixture_is_not_a_developer_base(seeded):
    bad = seeded.load_fixture("faulty_delete")
    assert submit(seeded, "def complete(tasks, task_id):\n    return 2\n", base=bad["sha256"]).status_code == 422


def test_diff_is_withheld_when_the_reader_cannot_read_the_base(seeded):
    bad = seeded.load_fixture("faulty_delete")  # not selected for a story: not developer-readable
    with seeded.store().write() as conn:  # trusted path: instructor-authored candidate based on the faulty fixture
        view, _ = put_candidate(conn, workspace_id="demo-001", source=b"def complete(tasks, task_id):\n    return 3\n",
                                origin="fixture", author_role="instructor", label="x", base_sha256=bad["sha256"])
    qa = seeded.client.get(f"/v1/candidates/{view['candidate_id']}", headers=headers("qa")).json()
    assert qa["base_diff"]["withheld"] is None and "-    remaining" in qa["base_diff"]["diff"]
    r = seeded.client.get(f"/v1/candidates/{view['candidate_id']}", headers=headers("developer")).json()
    assert r["base_diff"]["diff"] is None and r["base_diff"]["withheld"] == "BASE_NOT_READABLE"


@pytest.mark.parametrize("origin,author", [("agent-generated", "instructor"), ("fixture-reference", "developer"),
                                           ("fixture", "qa")])
def test_provenance_must_match_the_author_role(seeded, origin, author):
    with seeded.store().write() as conn:
        with pytest.raises(LabError) as exc:
            put_candidate(conn, workspace_id="demo-001", source=b"def complete(tasks, task_id):\n    return 4\n",
                          origin=origin, author_role=author, label="x")
    assert exc.value.code == "INVALID_PROVENANCE"


def test_inconsistent_stored_provenance_fails_closed(seeded):
    src = b"def complete(tasks, task_id):\n    return 5\n"
    import hashlib
    digest = hashlib.sha256(src).hexdigest()
    with seeded.store().write() as conn:  # bypass put_candidate to simulate a corrupted row
        conn.execute("INSERT INTO candidates(workspace_id, candidate_id, sha256, source, size_bytes, base_sha256,"
                     " author_role, origin, label, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ("demo-001", "cand_" + digest[:24], digest, src, len(src), None, "developer",
                      "fixture-reference", "forged", "2026-10-20T00:00:00Z"))
    r = seeded.client.get(f"/v1/candidates/cand_{digest[:24]}", headers=headers("qa"))
    assert r.status_code == 500 and r.json()["error"]["code"] == "ARTIFACT_INTEGRITY_ERROR"
    assert seeded.run_tests("cand_" + digest[:24]).status_code == 500


def test_submission_is_never_an_overwrite(seeded):
    first = submit(seeded, STARTER_EDIT).json()
    second = submit(seeded, STARTER_EDIT).json()
    assert first["created"] is True and second["created"] is False
    assert (first["candidate_id"], first["sha256"], first["created_at"]) == (second["candidate_id"], second["sha256"],
                                                                              second["created_at"])
    with seeded.store().write() as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE candidates SET source = x'00' WHERE candidate_id = ?", (first["candidate_id"],))


def test_fixture_loading_is_instructor_only_allowlisted_and_idempotent(seeded):
    first = seeded.load_fixture("faulty_delete")
    assert first["origin"] == "fixture-faulty" and first["label"].startswith("FIXTURE")
    again = seeded.client.post("/v1/instructor/actions", json={"action": "load_fixture", "workspace_id": "demo-001",
                                                               "fixture": "faulty_delete"},
                               headers=headers("instructor", None)).json()
    assert again["created"] is False and again["candidate"]["candidate_id"] == first["candidate_id"]
    bad = seeded.client.post("/v1/instructor/actions", json={"action": "load_fixture", "workspace_id": "demo-001",
                                                             "fixture": "../../etc/passwd"},
                             headers=headers("instructor", None))
    assert bad.status_code == 422
    for role in ("developer", "qa", "operations"):
        r = seeded.client.post("/v1/instructor/actions", json={"action": "load_fixture", "workspace_id": "demo-001",
                                                               "fixture": "reference_complete"}, headers=headers(role, None))
        assert r.status_code == 403
    r = seeded.client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": "demo-002",
                                                           "fixture": "faulty_delete"}, headers=headers("instructor", None))
    assert r.status_code == 422
