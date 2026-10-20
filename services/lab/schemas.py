"""Typed request schemas. Unknown fields are rejected everywhere (extra='forbid').

No schema carries credentials, URLs, SQL, paths, roles, approval flags or
budgets: authority comes from the token and server configuration only.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .store import SPRINT_STAGES


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


RefId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:@-]{1,128}$")]
Revision = Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
StageName = Literal[SPRINT_STAGES]  # type: ignore[valid-type]


class RunCreate(Strict):
    conversation_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
    parent_run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")] | None = None


class StoryCreate(Strict):
    title: Annotated[str, Field(min_length=1, max_length=120)]
    narrative: Annotated[str, Field(min_length=1, max_length=1000)]
    criteria: Annotated[list[Annotated[str, Field(min_length=1, max_length=300)]], Field(min_length=1, max_length=10)]
    evidence_refs: Annotated[list[RefId], Field(max_length=10)] = []


class TransitionRequest(Strict):
    story_id: Annotated[str, Field(pattern=r"^ST-\d{3}$")]
    to_stage: StageName
    expected_revision: Revision
    candidate_id: Annotated[str, Field(pattern=r"^cand_[0-9a-f]{24}$")] | None = None
    test_run_id: RefId | None = None


class MemorySave(Strict):
    key: Annotated[str, Field(pattern=r"^[a-z_]{1,64}$")]
    value: Annotated[str, Field(min_length=1, max_length=32)]
    ttl_days: Annotated[int, Field(strict=True, ge=1, le=30)] = 7


class CandidateSubmit(Strict):
    source: Annotated[str, Field(min_length=1, max_length=4096)]
    base_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None


class TestRunCreate(Strict):
    candidate_id: Annotated[str, Field(pattern=r"^cand_[0-9a-f]{24}$")]


class AppCommand(Strict):
    command: Annotated[str, Field(min_length=1, max_length=200)]


WorkspaceId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
INSTRUCTOR_ACTION_FIELDS: dict[str, frozenset[str]] = {
    "seed": frozenset(), "reset_preview": frozenset(), "reset_confirm": frozenset({"confirm"}),
    "load_fixture": frozenset({"fixture"}), "confirm_scope": frozenset({"story_id", "expected_revision"}),
    "drill_enable": frozenset({"fault_type", "candidate_id", "ttl_minutes"}),
    "drill_disable": frozenset({"fault_type", "candidate_id"}),
    "stop": frozenset({"reason"}), "resume": frozenset(),
}


class InstructorAction(Strict):
    """Allowlisted instructor actions; each action accepts only its own optional fields."""
    action: Literal["seed", "reset_preview", "reset_confirm", "load_fixture", "confirm_scope", "drill_enable",
                    "drill_disable", "stop", "resume"]
    workspace_id: WorkspaceId
    # load_fixture: an allowlisted, labelled instructor fixture name.
    fixture: Literal["faulty_delete", "reference_complete"] | None = None
    # confirm_scope
    story_id: Annotated[str, Field(pattern=r"^ST-\d{3}$")] | None = None
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=1_000_000)] | None = None
    # drill_enable / drill_disable
    fault_type: Literal["completion_unavailable"] | None = None
    candidate_id: Annotated[str, Field(pattern=r"^cand_[0-9a-f]{24}$")] | None = None
    ttl_minutes: Annotated[int, Field(strict=True, ge=1, le=30)] | None = None
    # reset_confirm: must equal workspace_id
    confirm: WorkspaceId | None = None
    # stop: short human note
    reason: Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$")] | None = None

    def unexpected_fields(self) -> list[str]:
        allowed = INSTRUCTOR_ACTION_FIELDS[self.action]
        return sorted(k for k, v in self.model_dump(exclude={"action", "workspace_id"}).items()
                      if v is not None and k not in allowed)


class KnowledgeSearch(Strict):
    query: Annotated[str, Field(min_length=1, max_length=300)]


class InstructorKnowledgeSearch(Strict):
    """Instructor-only: may include archived documents to demonstrate the metadata filter."""
    query: Annotated[str, Field(min_length=1, max_length=300)]
    include_archived: bool = True


CandidateId = Annotated[str, Field(pattern=r"^cand_[0-9a-f]{24}$")]
TestRunId = Annotated[str, Field(pattern=r"^tr_[0-9a-f]{24}$")]


class ReadinessQuery(Strict):
    candidate_id: CandidateId | None = None


class ReleasePlanCreate(Strict):
    """Operations asks for a plan; the server binds environment, hashes, revision and evidence."""
    action: Literal["deploy", "rollback"]
    candidate_id: CandidateId
    app_test_run_id: TestRunId | None = None


class A2AExchangeCreate(Strict):
    """Written only by the trusted Sprint Room A2A adapter (coordinator credential); no MCP tool."""
    parent_run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]
    peer_flow_id: Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
    card_url: Annotated[str, Field(max_length=300, pattern=r"^https://[A-Za-z0-9.\-]+(:\d{1,5})?/api/v1/a2a/"
                                   r"[0-9a-f-]{36}/\.well-known/agent-card\.json$")]
    protocol_version: Annotated[str, Field(pattern=r"^[0-9]{1,3}\.[0-9]{1,3}(\.[0-9]{1,3})?$")] | None = None
    transport: Annotated[str, Field(max_length=32)] | None = None
    adapter_version: Annotated[str, Field(min_length=1, max_length=64)]
    request: dict[str, Any]
    outcome: Literal["completed", "failed", "rejected", "unreachable", "unauthorized", "timeout", "protocol_error",
                     "not_sent"]
    task: dict[str, Any] | None = None
    task_get: dict[str, Any] | None = None
    http: Annotated[list[dict[str, Any]], Field(max_length=12)] = []
    error: dict[str, Any] | None = None
    started_at: Annotated[str, Field(max_length=40)]
    finished_at: Annotated[str, Field(max_length=40)]


PlanId = Annotated[str, Field(pattern=r"^plan_[0-9a-f]{24}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ApprovalCreate(Strict):
    """Human approver only (no MCP tool). There is no 'approved' flag: the decision quotes exact hashes."""
    plan_id: PlanId
    plan_sha256: Sha256
    snapshot_sha256: Sha256
    decision: Literal["approve", "reject"]
    # A label shown with the record. It confers no authority (identity = the token's role).
    display_name: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")] | None = None
    # The Langflow Human Input request id (``<node>:<run>``), for joining the native pause to this record.
    hitl_request_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:\-]{1,160}$")] | None = None


class ReleaseExecutionCreate(Strict):
    """Operations only. The server derives the action ID from the plan unless a trusted client supplies one."""
    plan_id: PlanId
    plan_sha256: Sha256 | None = None
    action_id: Annotated[str, Field(pattern=r"^act_[0-9a-f]{24}$")] | None = None


class AgentEvaluationCreate(Strict):
    """Evaluator only (Phase 09 stub; Phase 10 defines qualification). Stored, never self-qualifying."""
    harness_version: Annotated[str, Field(min_length=1, max_length=64)]
    manifest: dict[str, Any]
    cases: Annotated[list[dict[str, Any]], Field(max_length=50)]
    repetitions: Annotated[int, Field(strict=True, ge=1, le=10)]
    outcomes: dict[str, Any]
    trajectories: Annotated[list[dict[str, Any]], Field(max_length=200)] = []
