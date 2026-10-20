"""Trusted lab operations shared by the REST routes and the MCP tool catalog.

Both front ends authenticate first, then call these functions in-process with
the authenticated identity and a trusted context (workspace, run, request ID).
Authorization lives in ``auth.PERMISSIONS`` (checked by the caller before an
operation runs); validation, invariants, budgets and audit events live here and
in the modules they call, so a tool call cannot skip a check a REST call gets.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from . import audit, candidates, memory, releases, retrieval, runs, state, testing
from .auth import Identity
from .config import Settings
from .retrieval import KnowledgeBase
from .runner_client import RunnerClient
from .schemas import (CandidateSubmit, InstructorKnowledgeSearch, KnowledgeSearch, MemorySave, StoryCreate,
                      TestRunCreate, TransitionRequest)
from .skills import NAME_RE, VERSION_RE, SkillCatalog
from .store import LabError, Store, require_active_workspace

log = logging.getLogger("tasksprint.lab")


@dataclass(frozen=True)
class Ctx:
    identity: Identity
    workspace_id: str
    run_id: str | None
    request_id: str


class LabOps:
    def __init__(self, settings: Settings, store: Store, runner: RunnerClient | None, knowledge: KnowledgeBase,
                 skills: SkillCatalog):
        self.settings = settings
        self.store = store
        self.runner = runner
        self.knowledge = knowledge
        self.skills = skills

    # ---------------------------------------------------------------- plumbing
    def denial_event(self, request_id: str, identity: Identity, action: str, workspace_id: str | None,
                     run_id: str | None, err: LabError) -> None:
        details = {"code": err.code, **err.extra.get("audit", {})}
        try:
            with self.store.write() as conn:
                if workspace_id is not None and conn.execute(
                        "SELECT 1 FROM workspaces WHERE workspace_id = ?", (workspace_id,)).fetchone() is None:
                    workspace_id = None
                audit.record_event(conn, request_id=request_id, actor_role=identity.role, action=action,
                                   outcome="denied" if err.status in (401, 403) else "rejected",
                                   workspace_id=workspace_id, run_id=run_id, details=details)
        except sqlite3.Error:
            log.exception("could not record denial event request_id=%s", request_id)

    def bind(self, identity: Identity, workspace_id: str, run_id: str | None, request_id: str) -> Ctx:
        """Resolve the trusted context; with a run ID, count one action against that run's budget."""
        failed: LabError | None = None
        with self.store.write() if run_id else self.store.read() as conn:
            ws = require_active_workspace(conn, workspace_id)
            if run_id:
                try:
                    runs.consume_action(conn, run_id=run_id, role=identity.role, workspace=ws)
                except LabError as err:
                    failed = err
        if failed is not None:
            self.denial_event(request_id, identity, "run.action", workspace_id, None, failed)
            raise failed
        return Ctx(identity, workspace_id, run_id, request_id)

    def audited(self, c: Ctx, action: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except LabError as err:
            if err.status in (403, 409, 422, 429):
                self.denial_event(c.request_id, c.identity, action, c.workspace_id, c.run_id, err)
            raise

    def write_op(self, c: Ctx, action: str, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        def run() -> Any:
            with self.store.write() as conn:
                return fn(conn)
        return self.audited(c, action, run)

    # ---------------------------------------------------------------- state and memory
    def get_state(self, c: Ctx) -> dict:
        with self.store.read() as conn:
            return state.read_state(conn, c.workspace_id)

    def record_story(self, c: Ctx, body: StoryCreate) -> dict:
        return self.write_op(c, "story.create", lambda conn: state.StateWriter(conn, c.request_id, c.identity.role, c.run_id)
                             .create_story(c.workspace_id, title=body.title, narrative=body.narrative,
                                           criteria=list(body.criteria), evidence_refs=list(body.evidence_refs)))

    def transition(self, c: Ctx, body: TransitionRequest) -> dict:
        return self.write_op(c, "story.transition", lambda conn: state.StateWriter(conn, c.request_id, c.identity.role, c.run_id)
                             .transition(c.workspace_id, story_id=body.story_id, to_stage=body.to_stage,
                                         expected_revision=body.expected_revision, candidate_id=body.candidate_id,
                                         test_run_id=body.test_run_id))

    def read_memory(self, c: Ctx) -> dict:
        with self.store.read() as conn:
            return memory.read_preferences(conn, workspace_id=c.workspace_id, owner=c.identity.principal)

    def save_memory(self, c: Ctx, body: MemorySave) -> dict:
        def op(conn: sqlite3.Connection) -> dict:
            saved = memory.save_preference(conn, workspace_id=c.workspace_id, owner=c.identity.principal, key=body.key,
                                           value=body.value, ttl_days=body.ttl_days,
                                           source=f"save_preference:{c.identity.role}:{c.request_id}")
            audit.record_event(conn, request_id=c.request_id, actor_role=c.identity.role, action="memory.save",
                               outcome="ok", workspace_id=c.workspace_id, run_id=c.run_id,
                               details={"key": body.key, "value": body.value})
            return saved
        return self.write_op(c, "memory.save", op)

    # ---------------------------------------------------------------- candidates and tests
    def read_candidate(self, c: Ctx, candidate_id: str) -> dict:
        if not candidate_id.startswith("cand_") or len(candidate_id) != 29:
            raise LabError(404, "CANDIDATE_NOT_FOUND", "candidate does not exist in this workspace")
        with self.store.read() as conn:
            row = candidates.get_candidate(conn, c.workspace_id, candidate_id)
            if row is None:
                raise LabError(404, "CANDIDATE_NOT_FOUND", "candidate does not exist in this workspace")
            if not candidates.verify_integrity(row):
                raise LabError(500, "ARTIFACT_INTEGRITY_ERROR", "stored candidate does not match its hash")
            allowed = candidates.source_read_allowed(conn, c.workspace_id, c.identity.role, row)
            diff = candidates.diff_from_base(conn, c.workspace_id, c.identity.role, row) if allowed else None
        if not allowed:
            self.denial_event(c.request_id, c.identity, "candidate.read", c.workspace_id, c.run_id,
                              LabError(403, "SOURCE_NOT_PERMITTED", "", {"audit": {"candidate_id": candidate_id}}))
            raise LabError(403, "SOURCE_NOT_PERMITTED", "this candidate's source is not readable by this role")
        return {**candidates.candidate_view(row, include_source=True), "base_diff": diff}

    def submit_candidate(self, c: Ctx, body: CandidateSubmit) -> dict:
        def op(conn: sqlite3.Connection) -> dict:
            view, created = candidates.put_candidate(conn, workspace_id=c.workspace_id, source=body.source.encode("utf-8"),
                                                     origin="agent-generated", author_role=c.identity.role,
                                                     label="agent-submission", base_sha256=body.base_sha256)
            audit.record_event(conn, request_id=c.request_id, actor_role=c.identity.role, action="candidate.submit",
                               outcome="ok" if created else "duplicate", workspace_id=c.workspace_id, run_id=c.run_id,
                               details={"candidate_id": view["candidate_id"], "sha256": view["sha256"]})
            return {**view, "created": created}
        return self.write_op(c, "candidate.submit", op)

    def create_test_run(self, c: Ctx, body: TestRunCreate) -> dict:
        return self.audited(c, "test_run.create", lambda: testing.run_protected_suite(
            self.store, self.runner, workspace_id=c.workspace_id, candidate_id=body.candidate_id,
            request_id=c.request_id, actor_role=c.identity.role, run_id=c.run_id))

    def read_test_run(self, c: Ctx, test_run_id: str) -> dict:
        if not (test_run_id.startswith("tr_") and len(test_run_id) == 27):
            raise LabError(404, "TEST_RUN_NOT_FOUND", "test run does not exist in this workspace")
        with self.store.read() as conn:
            return testing.get_report(conn, c.workspace_id, test_run_id)

    # ---------------------------------------------------------------- release status, health, events
    def release_status(self, c: Ctx) -> dict:
        with self.store.read() as conn:
            return releases.release_status(conn, c.workspace_id)

    def app_health(self, c: Ctx) -> dict:
        with self.store.read() as conn:
            return releases.app_health(conn, c.workspace_id)

    def events(self, c: Ctx, limit: int) -> dict:
        with self.store.read() as conn:
            return {"events": audit.list_events(conn, c.workspace_id, limit)}

    # ---------------------------------------------------------------- knowledge (A7)
    def knowledge_search(self, c: Ctx, body: KnowledgeSearch) -> dict:
        with self.store.read() as conn:
            result = self.knowledge.search(conn, body.query)
        with self.store.write() as conn:
            result["event_id"] = audit.record_event(
                conn, request_id=c.request_id, actor_role=c.identity.role, action="knowledge.search",
                outcome=result["status"], workspace_id=c.workspace_id, run_id=c.run_id,
                details={"terms": result["query_terms"][:8], "results": retrieval.citation_refs(result),
                         "hashes": [r["citation"]["hash"][:16] for r in result["results"]],
                         "abstention": (result["abstention"] or {}).get("code"),
                         "corpus": result["corpus_manifest_sha256"][:16]})
        return result

    def instructor_knowledge_search(self, identity: Identity, request_id: str, body: InstructorKnowledgeSearch) -> dict:
        with self.store.read() as conn:
            result = self.knowledge.search(conn, body.query, include_archived=body.include_archived)
        with self.store.write() as conn:
            result["event_id"] = audit.record_event(
                conn, request_id=request_id, actor_role=identity.role, action="knowledge.search.instructor",
                outcome=result["status"], workspace_id=None, run_id=None,
                details={"terms": result["query_terms"][:8], "include_archived": body.include_archived,
                         "results": retrieval.citation_refs(result)})
        return result

    # ---------------------------------------------------------------- skills (A7)
    def list_skills(self, c: Ctx) -> dict:
        return {"skills": self.skills.list(),
                "note": "Metadata only. Load a skill by exact name and version. Skills grant no permissions."}

    def load_skill(self, c: Ctx, name: str, version: str) -> dict:
        skill = self.skills.get(name, version) if NAME_RE.match(name) and VERSION_RE.match(version) else None
        if skill is None:
            raise LabError(404, "SKILL_NOT_FOUND", "no approved skill with this name and version")
        with self.store.write() as conn:
            event_id = audit.record_event(
                conn, request_id=c.request_id, actor_role=c.identity.role, action="skill_loaded", outcome="ok",
                workspace_id=c.workspace_id, run_id=c.run_id,
                details={"name": skill.name, "version": skill.version, "body_sha256": skill.body_sha256})
        return {**skill.summary(), "body": skill.body, "package_sha256": skill.package_sha256,
                "event_id": event_id, "grants_permissions": False}
