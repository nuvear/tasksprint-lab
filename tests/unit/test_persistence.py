"""APP-08 (close/reopen part): records survive re-creating the app on the same DB.

This is the close/reopen check. The separate real process restart is in
tests/integration/test_process_restart.py.
"""
from __future__ import annotations

import sqlite3

import pytest

from services.lab.store import MIGRATIONS, Store
from tests.conftest import Lab, headers


def test_add_and_list_persist_across_backend_restart(db_path):
    first = Lab(db_path)
    first.seed()
    assert first.cmd("add Prepare sprint review").json()["data"]["task"]["id"] == "T003"
    before = first.cmd("list").json()["data"]["tasks"]
    del first  # drop the app, its store and connections

    second = Lab(db_path)  # new app instance, re-runs migrations, reopens the file
    after = second.cmd("list").json()["data"]["tasks"]
    assert after == before
    assert second.cmd("add After restart").json()["data"]["task"]["id"] == "T004"
    # Release pointer and starter hash also survive.
    assert second.client.get("/v1/releases", headers=headers("application")).json()["active"]["release_revision"] == 0


def test_migrations_are_versioned_and_idempotent(db_path):
    store = Store(str(db_path))
    assert store.migrate() == [v for v, _, _ in MIGRATIONS]
    assert store.migrate() == []
    assert store.schema_version() == max(v for v, _, _ in MIGRATIONS)


def test_migration_checksum_drift_refuses_to_start(db_path):
    store = Store(str(db_path))
    store.migrate()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        Store(str(db_path)).migrate()


def test_failed_write_rolls_back_entirely(seeded):
    from services.lab.store import LabError
    with pytest.raises(LabError):
        with seeded.store().write() as conn:
            conn.execute("INSERT INTO tasks(workspace_id, task_id, title, completed, revision, created_at, updated_at)"
                         " VALUES ('demo-001','T900','partial',0,1,'x','x')")
            raise LabError(409, "TEST", "abort")
    assert "T900" not in seeded.cmd("list").json()["message"]
