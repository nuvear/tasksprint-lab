"""Typed request schemas. Unknown fields are rejected everywhere (extra='forbid').

No schema carries credentials, URLs, SQL, paths, roles, approval flags or
budgets: authority comes from the token and server configuration only.
"""
from __future__ import annotations

from typing import Annotated, Literal

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


class AppCommand(Strict):
    command: Annotated[str, Field(min_length=1, max_length=200)]


class InstructorAction(Strict):
    action: Literal["seed", "reset_preview"]
    workspace_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
