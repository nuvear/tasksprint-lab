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
    "outage_enable": frozenset({"tool", "ttl_minutes"}), "outage_disable": frozenset({"tool"}),
}


class InstructorAction(Strict):
    """Allowlisted instructor actions; each action accepts only its own optional fields."""
    action: Literal["seed", "reset_preview", "reset_confirm", "load_fixture", "confirm_scope", "drill_enable",
                    "drill_disable", "stop", "resume", "outage_enable", "outage_disable"]
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
    # outage_enable / outage_disable (Phase 10, AE-05): a controlled unavailable result for one tool
    tool: Literal["run_candidate_tests", "get_app_health"] | None = None
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


IsoUtc = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")]
EvidenceRef = Annotated[str, Field(pattern=r"^(evt|run|tr|cand|plan|a2ax|apr|rel)_[0-9a-f]{24,32}$")]
CaseId = Annotated[str, Field(pattern=r"^AE-0[1-8]$")]
CheckId = Annotated[str, Field(pattern=r"^AE-0[1-8]\.[a-z0-9_]{1,40}$")]


class EvalCheckDef(Strict):
    check_id: CheckId
    case_id: CaseId
    description: Annotated[str, Field(min_length=1, max_length=240)]
    critical: bool
    method: Literal["state", "trajectory", "lexical", "langflow"]


class EvalCheckResult(Strict):
    check_id: CheckId
    passed: bool | None
    evidence: Annotated[list[EvidenceRef], Field(max_length=12)] = []
    observed: Annotated[str, Field(max_length=200)] = ""


class EvalTrial(Strict):
    case_id: CaseId
    repetition: Annotated[int, Field(strict=True, ge=1, le=10)]
    status: Literal["pass", "fail", "not_run", "error"]
    started_at: IsoUtc
    ended_at: IsoUtc
    latency_ms: Annotated[int, Field(strict=True, ge=0, le=3_600_000)] | None = None
    session_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
    flow: Annotated[str, Field(pattern=r"^TS-(01|02|03|10|20|30)$")]
    run_ids: Annotated[list[Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]], Field(max_length=12)] = []
    evidence_refs: Annotated[list[EvidenceRef], Field(max_length=40)] = []
    checks: Annotated[list[EvalCheckResult], Field(max_length=16)] = []
    usage: dict[str, Annotated[int, Field(strict=True, ge=0)]] | None = None
    usage_unavailable_reason: Annotated[str, Field(max_length=160)] | None = None
    not_run_reason: Annotated[str, Field(max_length=200)] | None = None
    fault_injection: Annotated[str, Field(max_length=200)] | None = None


class AgentEvaluationCreate(Strict):
    """Evaluator only (trusted harness, no MCP tool). The server recomputes the verdict and the lab-side manifest."""
    harness_version: Annotated[str, Field(min_length=1, max_length=64)]
    purpose: Literal["qualification", "partial", "class"]
    label: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")]
    repetitions: Annotated[int, Field(strict=True, ge=1, le=10)]
    started_at: IsoUtc
    ended_at: IsoUtc
    system: dict[str, Any]
    check_catalog: Annotated[list[EvalCheckDef], Field(min_length=1, max_length=120)]
    trials: Annotated[list[EvalTrial], Field(min_length=1, max_length=90)]
    trajectory_digest_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    telemetry_notes: Annotated[str, Field(max_length=500)] = ""


class ManifestAttestationCreate(Strict):
    """Evaluator only: the harness's freshly computed live Langflow/harness system manifest."""
    system: dict[str, Any]
