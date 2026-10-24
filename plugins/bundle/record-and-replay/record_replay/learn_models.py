# -*- coding: utf-8 -*-
"""Versioned plugin contracts for learning a Skill from a recording."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LearnModelTarget(BaseModel):
    """Exact model destination shown before evidence leaves the process."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    is_local: bool


class LearnEvidenceLocator(BaseModel):
    """Semantic UI locator copied from redacted recording evidence."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: str | None = Field(default=None, max_length=512)
    app_name: str | None = Field(default=None, max_length=512)
    window_role: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=128)
    subrole: str | None = Field(default=None, max_length=128)
    identifier: str | None = Field(default=None, max_length=512)
    name: str | None = Field(default=None, max_length=512)


class LearnEvidenceEvent(BaseModel):
    """One bounded semantic event supplied to the Learn task."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^event-[0-9]{4}$")
    source_sequences: list[int] = Field(min_length=1, max_length=2000)
    type: Literal["activate", "drag", "scroll", "redacted_input"]
    locator: LearnEvidenceLocator
    action: dict[str, object] = Field(default_factory=dict)
    redacted: bool = False

    @field_validator("source_sequences")
    @classmethod
    def source_sequences_are_ordered(cls, value: list[int]) -> list[int]:
        """Keep compact evidence traceable without duplicate source ids."""
        if value != sorted(set(value)):
            raise ValueError("source_sequences must be ordered and unique")
        return value


class LearnCaptureContract(BaseModel):
    """Facts that constrain how a model may interpret the evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    recording_event_schema_version: Literal[1] = 1
    coordinates_included: Literal[False] = False
    keyboard_content_recorded: Literal[False] = False
    semantic_locators_are_evidence: Literal[True] = True
    event_log_is_not_a_macro: Literal[True] = True


class LearnIntegritySummary(BaseModel):
    """Completeness and compaction facts for one evidence envelope."""

    model_config = ConfigDict(extra="forbid")

    persisted_event_count: int = Field(ge=0)
    selected_event_count: int = Field(ge=0)
    evidence_event_count: int = Field(ge=1)
    dropped_event_count: int = Field(ge=0)
    redacted_event_count: int = Field(ge=0)


class LearnIntentContext(BaseModel):
    """User-owned intent supplied separately from observed UI evidence."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=500)
    confirmed_context: str = Field(default="", max_length=2000)

    @field_validator("goal", "confirmed_context")
    @classmethod
    def strip_text(cls, value: str) -> str:
        """Normalize user-owned intent at the application boundary."""
        return value.strip()


class LearnEvidenceEnvelope(BaseModel):
    """The complete, versioned payload allowed to reach a Learn model."""

    model_config = ConfigDict(extra="forbid")

    learn_evidence_schema_version: Literal[1] = 1
    recording_id: UUID
    capture_contract: LearnCaptureContract
    integrity: LearnIntegritySummary
    intent: LearnIntentContext
    events: list[LearnEvidenceEvent] = Field(min_length=1, max_length=256)


class LearnEvidencePreview(BaseModel):
    """Low-sensitivity consent screen; it contains no event payload."""

    model_config = ConfigDict(extra="forbid")

    api_schema_version: Literal[1] = 1
    recording_id: UUID
    consent_token: UUID
    expires_at: datetime
    model_target: LearnModelTarget
    external_transfer: bool
    persisted_event_count: int = Field(ge=0)
    selected_event_count: int = Field(ge=0)
    evidence_event_count: int = Field(ge=1)
    dropped_event_count: int = Field(ge=0)
    redacted_event_count: int = Field(ge=0)
    field_scope: list[str]


class RecordingReview(BaseModel):
    """Local-only semantic timeline used to select Learn evidence."""

    model_config = ConfigDict(extra="forbid")

    api_schema_version: Literal[1] = 1
    recording_id: UUID
    persisted_event_count: int = Field(ge=0)
    dropped_event_count: int = Field(ge=0)
    events: list[LearnEvidenceEvent] = Field(max_length=256)


class SkillDraftInput(BaseModel):
    """One reusable value that should be requested at invocation time."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    description: str = Field(min_length=1, max_length=240)
    required: bool = True


class SkillDraftStep(BaseModel):
    """One model-proposed step grounded to a compact evidence event."""

    model_config = ConfigDict(extra="forbid")

    source_event_id: str = Field(pattern=r"^event-[0-9]{4}$")
    action: Literal["activate", "drag", "scroll", "request-input"]
    locator: LearnEvidenceLocator
    instruction: str = Field(min_length=1, max_length=500)
    verification: str = Field(min_length=1, max_length=500)


class StructuredSkillDraft(BaseModel):
    """Strict model response before local grounding and Markdown rendering."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)
    description: str = Field(min_length=1, max_length=240)
    goal: str = Field(min_length=1, max_length=500)
    inputs: list[SkillDraftInput] = Field(default_factory=list, max_length=16)
    steps: list[SkillDraftStep] = Field(min_length=1, max_length=64)
    ignored_event_ids: list[str] = Field(default_factory=list, max_length=256)
    ambiguities: list[str] = Field(default_factory=list, max_length=16)
    assumptions: list[str] = Field(default_factory=list, max_length=16)


class ReviewedSkillDraft(BaseModel):
    """User-reviewable artifact produced after strict local validation."""

    model_config = ConfigDict(extra="forbid")

    api_schema_version: Literal[1] = 1
    draft_id: UUID
    recording_id: UUID
    name: str
    description: str
    content: str
    inputs: list[SkillDraftInput]
    steps: list[SkillDraftStep]
    source_sequences: list[int]
    ignored_source_sequences: list[int]
    ambiguities: list[str]
    assumptions: list[str]
    needs_confirmation: bool


class MaterializedSkill(BaseModel):
    """Result returned only after SkillService commits the reviewed draft."""

    model_config = ConfigDict(extra="forbid")

    api_schema_version: Literal[1] = 1
    created: Literal[True] = True
    name: str
    enabled: bool
    reload_scheduled: bool


__all__ = [
    "LearnCaptureContract",
    "LearnEvidenceEnvelope",
    "LearnEvidenceEvent",
    "LearnEvidenceLocator",
    "LearnEvidencePreview",
    "LearnIntegritySummary",
    "LearnIntentContext",
    "LearnModelTarget",
    "MaterializedSkill",
    "RecordingReview",
    "ReviewedSkillDraft",
    "SkillDraftInput",
    "SkillDraftStep",
    "StructuredSkillDraft",
]
