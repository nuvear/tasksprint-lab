"""Immutable candidate artifacts and source-read provenance policy (A5, A6)."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from services.lab.candidates import put_candidate
from tests.conftest import headers

REPO = Path(__file__).resolve().parents[2]
SRC = "def complete(tasks, task_id):\n    return {'ok': False, 'code': 'TODO', 'tasks': tasks}\n"


def submit(lab, source=SRC, role="developer", **extra):
    return lab.client.post("/v1/candidates", json={"source": source, **extra}, headers=headers(role))


def test_submit_is_content_addressed_and_agent_generated(seeded):
    r = submit(seeded)
    assert r.status_code == 201
    body = r.json()
    digest = hashlib.sha256(SRC.encode()).hexdigest()
    assert body["sha256"] == digest and body["candidate_id"] == "cand_" + digest[:24]
    assert body["origin"] == "agent-generated" and body["author_role"] == "developer" and body["created"] is True
    again = submit(seeded).json()
    assert again["created"] is False and again["candidate_id"] == body["candidate_id"]


def test_read_returns_exact_source_and_provenance(seeded):
    cid = submit(seeded).json()["candidate_id"]
    for role in ("developer", "qa", "operations"):
        r = seeded.client.get(f"/v1/candidates/{cid}", headers=headers(role))
        assert r.status_code == 200 and r.json()["source"] == SRC


def test_candidates_cannot_be_overwritten_or_deleted(seeded):
    cid = submit(seeded).json()["candidate_id"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with seeded.store().write() as conn:
            conn.execute("UPDATE candidates SET source = ? WHERE candidate_id = ?", (b"evil", cid))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with seeded.store().write() as conn:
            conn.execute("DELETE FROM candidates WHERE candidate_id = ?", (cid,))


def test_tampered_bytes_fail_closed(seeded):
    cid = submit(seeded).json()["candidate_id"]
    conn = sqlite3.connect(seeded.db_path)
    conn.execute("DROP TRIGGER candidates_no_update")
    conn.execute("UPDATE candidates SET source = ? WHERE candidate_id = ?", (b"def complete(tasks, task_id):\n    pass\n", cid))
    conn.commit()
    conn.close()
    r = seeded.client.get(f"/v1/candidates/{cid}", headers=headers("qa"))
    assert r.status_code == 500 and r.json()["error"]["code"] == "ARTIFACT_INTEGRITY_ERROR"


@pytest.mark.parametrize("extra", [{"origin": "fixture-reference"}, {"author_role": "instructor"},
                                   {"sha256": "0" * 64}, {"candidate_id": "cand_" + "1" * 24}, {"label": "approved"}])
def test_caller_cannot_choose_provenance_or_ids(seeded, extra):
    assert submit(seeded, **extra).status_code == 422


def test_size_limit_and_text_only(seeded):
    assert submit(seeded, source="x" * 4097).status_code == 422
    big_utf8 = "é" * 2100  # 2100 chars but 4200 bytes
    r = submit(seeded, source=big_utf8)
    assert r.status_code == 413 and r.json()["error"]["code"] == "SOURCE_TOO_LARGE"
    assert submit(seeded, source="def f():\x00\n").json()["error"]["code"] == "SOURCE_CONTROL_CHARS"


def test_only_developer_submits(seeded):
    for role in ("qa", "operations", "coordinator", "application", "instructor", "human_approver"):
        assert submit(seeded, role=role).status_code == 403


def _load_fixture(lab, name, origin):
    with lab.store().write() as conn:  # trusted instructor path (labelled fixture loading is a later phase)
        view, _ = put_candidate(conn, workspace_id="demo-001", source=(REPO / "instructor" / "fixtures" / name).read_bytes(),
                                origin=origin, author_role="instructor", label=f"FIXTURE {name}")
    return view


def test_reference_fixture_source_is_never_model_readable(seeded):
    ref = _load_fixture(seeded, "reference_complete.py", "fixture-reference")
    for role in ("developer", "qa", "operations"):
        r = seeded.client.get(f"/v1/candidates/{ref['candidate_id']}", headers=headers(role))
        assert r.status_code == 403 and r.json()["error"]["code"] == "SOURCE_NOT_PERMITTED"
        assert "def complete" not in r.text


def test_faulty_fixture_is_developer_readable_only_after_selection(seeded):
    bad = _load_fixture(seeded, "faulty_delete.py", "fixture-faulty")
    assert seeded.client.get(f"/v1/candidates/{bad['candidate_id']}", headers=headers("developer")).status_code == 403
    assert seeded.client.get(f"/v1/candidates/{bad['candidate_id']}", headers=headers("qa")).status_code == 200
    with seeded.store().write() as conn:  # instructor selects it for the demo story (stand-in for later control flow)
        conn.execute("INSERT INTO stories(workspace_id, story_id, sprint_id, title, narrative, criteria_json, criteria_version,"
                     " scope_confirmed, stage, candidate_id, repair_count, evidence_json, revision, created_by, created_at, updated_at)"
                     " VALUES ('demo-001','ST-001','SPRINT-1','t','n','[]',1,1,'IN_QA',?,0,'[]',1,'test','x','x')",
                     (bad["candidate_id"],))
    r = seeded.client.get(f"/v1/candidates/{bad['candidate_id']}", headers=headers("developer"))
    assert r.status_code == 200 and r.json()["origin"] == "fixture-faulty"


def test_identical_bytes_with_other_provenance_conflict(seeded):
    starter = (REPO / "instructor" / "fixtures" / "starter_v0.py").read_text()
    r = submit(seeded, source=starter)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CANDIDATE_EXISTS"


def test_base_hash_must_exist(seeded):
    assert submit(seeded, base_sha256="a" * 64).json()["error"]["code"] == "UNKNOWN_BASE"
    starter_sha = seeded.client.get("/v1/releases", headers=headers("operations")).json()["active"]["sha256"]
    assert submit(seeded, base_sha256=starter_sha).status_code == 201
