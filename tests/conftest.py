"""Shared fixtures. All credentials here are FAKE and exist only for tests."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.lab import clock
from services.lab.config import ROLES, Settings
from services.lab.main import create_app
from services.lab.runner_client import RunnerClient
from services.runner.main import RunnerSettings
from services.runner.main import create_app as create_runner_app

FAKE_TOKENS = {role: f"ts_fake{role.replace('_', '')}_" + hashlib.sha256(f"fake-{role}".encode()).hexdigest()[:40]
               for role in sorted(ROLES)}
INVALID_TOKEN = "ts_fakeintruder_" + "0" * 40
FAKE_RUNNER_TOKEN = "fake-runner-transport-" + hashlib.sha256(b"fake-runner").hexdigest()[:40]


def runner_app(**overrides):
    return create_runner_app(RunnerSettings(token=FAKE_RUNNER_TOKEN, **overrides))


def in_process_runner(**overrides) -> RunnerClient:
    """Lab-side client bound to an in-process runner app (unit tests; integration uses a real process)."""
    return RunnerClient("http://runner.invalid", FAKE_RUNNER_TOKEN, http=TestClient(runner_app(**overrides)))


def fake_settings(db_path: Path, **overrides) -> Settings:
    base = dict(
        db_path=str(db_path),
        demo_enabled=True,
        token_hashes={r: hashlib.sha256(t.encode()).hexdigest() for r, t in FAKE_TOKENS.items()},
        allowed_workspaces=("demo-001", "demo-002"),
    )
    base.update(overrides)
    return Settings(**base)


def headers(role: str | None, workspace: str | None = "demo-001", run: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {}
    if role is not None:
        h["Authorization"] = f"Bearer {FAKE_TOKENS[role]}"
    if workspace is not None:
        h["X-TaskSprint-Workspace"] = workspace
    if run is not None:
        h["X-TaskSprint-Run"] = run
    return h


class Lab:
    """Small helper around a TestClient bound to one DB file."""

    def __init__(self, db_path: Path, runner: RunnerClient | None | bool = True, **overrides):
        self.db_path = db_path
        self.settings = fake_settings(db_path, **overrides)
        if runner is True:
            runner = in_process_runner()
        self.app = create_app(self.settings, runner=runner or None)
        self.client = TestClient(self.app)

    def seed(self, workspace: str = "demo-001"):
        r = self.client.post("/v1/instructor/actions", json={"action": "seed", "workspace_id": workspace},
                             headers=headers("instructor", None))
        assert r.status_code == 200, r.text
        return r.json()

    def cmd(self, text: str, workspace: str = "demo-001", run: str | None = None):
        return self.client.post("/v1/app/commands", json={"command": text}, headers=headers("application", workspace, run))

    def store(self):
        return self.app.state.store

    def load_fixture(self, fixture: str, workspace: str = "demo-001"):
        r = self.client.post("/v1/instructor/actions",
                             json={"action": "load_fixture", "workspace_id": workspace, "fixture": fixture},
                             headers=headers("instructor", None))
        assert r.status_code == 200, r.text
        return r.json()["candidate"]

    def activate(self, candidate: dict, workspace: str = "demo-001"):
        """TRUSTED TEST-ONLY pointer change. No deploy path exists before Phase 09."""
        with self.store().write() as conn:
            conn.execute("UPDATE active_releases SET active_candidate_id = ?, active_sha256 = ? WHERE workspace_id = ?",
                         (candidate["candidate_id"], candidate["sha256"], workspace))

    def run_tests(self, candidate_id: str, role: str = "qa", workspace: str = "demo-001"):
        return self.client.post("/v1/test-runs", json={"candidate_id": candidate_id}, headers=headers(role, workspace))


@pytest.fixture(autouse=True)
def _reset_clock():
    clock.reset_for_tests()
    yield
    clock.reset_for_tests()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "lab.sqlite3"


@pytest.fixture
def lab(db_path: Path) -> Lab:
    return Lab(db_path)


@pytest.fixture
def seeded(lab: Lab) -> Lab:
    lab.seed("demo-001")
    return lab
