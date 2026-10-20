"""Approved skill catalog (A7; Build Guide 04.3/04.4)."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from services.lab.config import REPO_ROOT
from services.lab.skills import SkillCatalog, SkillIntegrityError
from services.lab.store import Store
from tests.conftest import headers

NAMES = {"implement-todo-change", "release-and-recover"}
# Owner-approved Phase 05 bump: implement-todo-change 1.1.0 adds the grammar limits.
VERSIONS = {"implement-todo-change": "1.1.0", "release-and-recover": "1.0.0"}


def test_list_is_metadata_only(seeded):
    r = seeded.client.get("/v1/skills", headers=headers("developer"))
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert {s["name"] for s in skills} == NAMES
    for s in skills:
        assert set(s) == {"name", "version", "description", "owner", "body_sha256"}
        assert s["version"] == VERSIONS[s["name"]]
    assert "Procedure" not in json.dumps(r.json())  # no body text in the listing


def test_load_returns_exact_body_and_logs_version_and_hash(seeded):
    r = seeded.client.get("/v1/skills/release-and-recover/1.0.0", headers=headers("developer"))
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "release-and-recover" and body["version"] == "1.0.0"
    assert hashlib.sha256(body["body"].encode()).hexdigest() == body["body_sha256"]
    raw = (REPO_ROOT / "skills" / "release-and-recover" / "SKILL.md").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == body["package_sha256"]
    assert body["body"].startswith("# Release and recover") and body["grants_permissions"] is False
    with seeded.store().read() as conn:
        ev = conn.execute("SELECT * FROM events WHERE event_id = ?", (body["event_id"],)).fetchone()
    assert ev["action"] == "skill_loaded" and ev["actor_role"] == "developer"
    details = json.loads(ev["details_json"])
    assert details == {"name": "release-and-recover", "version": "1.0.0", "body_sha256": body["body_sha256"]}


def test_skill_load_does_not_grant_release_routes(seeded):
    assert seeded.client.get("/v1/skills/release-and-recover/1.0.0", headers=headers("developer")).status_code == 200
    # Still denied after loading the release skill.
    assert seeded.client.get("/v1/releases", headers=headers("developer")).status_code == 403
    assert seeded.client.post("/v1/test-runs", json={"candidate_id": "cand_" + "0" * 24},
                              headers=headers("developer")).status_code == 403


def test_unknown_or_wrong_version_is_404_and_roles_are_scoped(seeded):
    assert seeded.client.get("/v1/skills/release-and-recover/9.9.9", headers=headers("operations")).status_code == 404
    assert seeded.client.get("/v1/skills/..%2F..%2Fetc/1", headers=headers("operations")).status_code == 404
    for role in ("qa", "coordinator", "product_owner", "application", "instructor"):
        assert seeded.client.get("/v1/skills", headers=headers(role)).status_code == 403, role
        assert seeded.client.get("/v1/skills/release-and-recover/1.0.0", headers=headers(role)).status_code == 403


def test_skills_are_a_separate_catalog_from_knowledge(seeded):
    with seeded.store().read() as conn:
        chunk_text = " ".join(r[0] for r in conn.execute("SELECT chunk_text FROM chunks"))
        assert conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 2
    assert "Release procedure" not in chunk_text and "Stop and escalate" not in chunk_text


def test_changed_skill_without_version_bump_refuses(tmp_path: Path):
    d = tmp_path / "skills"
    shutil.copytree(REPO_ROOT / "skills", d)
    store = Store(str(tmp_path / "s.sqlite3"))
    store.migrate()
    SkillCatalog(store, d).load()
    p = d / "implement-todo-change" / "SKILL.md"
    p.write_text(p.read_text().replace("one repair", "two repairs"))
    with pytest.raises(SkillIntegrityError, match="without a version bump"):
        SkillCatalog(store, d).load()


def test_skill_name_must_match_folder(tmp_path: Path):
    d = tmp_path / "skills"
    shutil.copytree(REPO_ROOT / "skills", d)
    (d / "implement-todo-change").rename(d / "other-name")
    store = Store(str(tmp_path / "s.sqlite3"))
    store.migrate()
    with pytest.raises(SkillIntegrityError):
        SkillCatalog(store, d).load()


def test_implement_skill_1_1_0_carries_the_grammar_limits(seeded):
    r = seeded.client.get("/v1/skills/implement-todo-change/1.1.0", headers=headers("developer"))
    assert r.status_code == 200
    body = r.json()["body"]
    for text in ("Not allowed: any call", "no `-1` index", "`True != 1`", "4 KiB source, 256 syntax nodes",
                 "a validator rejection you cannot fix within this grammar"):
        assert text in body, text
    assert "def complete(tasks, task_id):" not in body  # limits only, never a solution
    assert seeded.client.get("/v1/skills/implement-todo-change/1.0.0",
                             headers=headers("developer")).status_code == 404  # not served from the file any more


def test_version_bump_appends_to_a_database_holding_the_old_version(tmp_path: Path):
    """An existing lab database (owner VM, later the Railway volume) that recorded 1.0.0
    accepts the bumped file: the new version is appended, the old row is kept."""
    d = tmp_path / "skills"
    shutil.copytree(REPO_ROOT / "skills", d)
    p = d / "implement-todo-change" / "SKILL.md"
    current = p.read_text()
    p.write_text(current.replace('version: "1.1.0"', 'version: "1.0.0"').replace("Not allowed: any call", "x"))
    store = Store(str(tmp_path / "s.sqlite3"))
    store.migrate()
    SkillCatalog(store, d).load()
    p.write_text(current)
    listed = SkillCatalog(store, d).load()
    assert {s["name"]: s["version"] for s in listed} == VERSIONS
    with store.read() as conn:
        rows = conn.execute("SELECT version FROM skills WHERE name = 'implement-todo-change' ORDER BY version").fetchall()
    assert [r[0] for r in rows] == ["1.0.0", "1.1.0"]
