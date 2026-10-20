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


# ------------------------------------------------------------------ Phase 10: TEST-ONLY evaluation reports
TEST_SYSTEM = {
    "langflow": {"version": "test-only"},
    "flows": {"TS-10": {"flow_id": "test-only", "export_sha256": "0" * 64}},
    "models": {"agents": {"TS-10": {"model_name": "test-only"}}},
    "a2a": {"protocol_version": "0.3.0"},
    "harness": {"harness_version": "test-only", "case_set_version": "tasksprint-agent-cases/1",
                "grader_sha256": "1" * 64},
}


def eval_report(*, repetitions: int = 3, purpose: str = "qualification", cases=None, fail: tuple = (),
                system: dict | None = None, label: str = "TEST-ONLY report", evidence: dict | None = None,
                end_offset_s: int = 20) -> dict:
    """A syntactically valid report with one check per case. TEST-ONLY: no agent was run."""
    from services.lab.agent_evaluations import REQUIRED_CASES
    from services.lab.clock import to_iso, utc_now
    from datetime import timedelta
    cases = list(cases or REQUIRED_CASES)
    # Trial windows end ``end_offset_s`` before now so setup events (seed, fixture) are outside every window.
    end = utc_now() - timedelta(seconds=end_offset_s)
    start = end - timedelta(seconds=len(cases) * repetitions + 5)
    trials, t = [], start
    for rep in range(1, repetitions + 1):
        for cid in cases:
            t1 = t + timedelta(seconds=1)
            failed = (cid, rep) in fail
            trials.append({"case_id": cid, "repetition": rep, "status": "fail" if failed else "pass",
                           "started_at": to_iso(t), "ended_at": to_iso(t1), "latency_ms": 1000,
                           "session_id": f"test-{cid}-{rep}", "flow": "TS-10",
                           "evidence_refs": list((evidence or {}).get((cid, rep), [])),
                           "checks": [{"check_id": f"{cid}.outcome", "passed": not failed, "observed": "test-only"}],
                           "usage": None, "usage_unavailable_reason": "test-only"})
            t = t1
    return {"harness_version": "test-only", "purpose": purpose, "label": label, "repetitions": repetitions,
            "started_at": to_iso(start), "ended_at": to_iso(end), "system": system or TEST_SYSTEM,
            "check_catalog": [{"check_id": f"{c}.outcome", "case_id": c, "description": "test-only outcome",
                               "critical": True, "method": "state"} for c in REQUIRED_CASES],
            "trials": trials, "trajectory_digest_sha256": "2" * 64}


def qualify(client, workspace: str = "demo-001") -> dict:
    """Record a TEST-ONLY qualifying report through the real evaluator route."""
    r = client.post("/v1/agent-evaluations", json=eval_report(), headers=headers("evaluator", workspace))
    assert r.status_code == 201, r.text
    assert r.json()["verdict"] == "QUALIFIED", r.json()
    return r.json()
