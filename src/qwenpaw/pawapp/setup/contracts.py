# -*- coding: utf-8 -*-
"""Versioned, secret-free contracts for PawApp setup coordination."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from ..tasks.contracts import (
    Contract,
    Identity,
    ProjectRef,
    TaskScope,
    canonical_json,
)

SetupAuthority = Literal["HostBinding", "AppLocal", "ExternalManaged"]
SetupPresentation = Literal["chat_card", "secure_form", "app_entry"]
ReadinessState = Literal[
    "ready",
    "needs_input",
    "needs_configuration",
    "needs_authorization",
    "unavailable",
    "unknown",
]
SetupState = Literal[
    "requested",
    "opened",
    "waiting_external",
    "saved",
    "cancelled",
    "failed",
    "expired",
]
SetupOutcome = Literal["saved", "cancelled", "failed"]
Revision = Annotated[int, Field(ge=0)]


class SetupRequirement(Contract):
    """One stable, declarative prerequisite without configuration values."""

    schema_version: Literal[1] = 1
    id: Identity
    summary: Annotated[str, Field(min_length=1, max_length=2000)]
    required_for: tuple[Identity, ...] = Field(min_length=1)
    authority: SetupAuthority
    setup_entry_ref: Identity
    check_ref: Identity
    type_ref: Identity | None = None

    @model_validator(mode="after")
    def validate_references(self) -> SetupRequirement:
        if len(set(self.required_for)) != len(self.required_for):
            raise ValueError("required_for must be unique")
        return self


class ReadinessResult(Contract):
    """A bounded check result. It contains public references, never secrets."""

    schema_version: Literal[1] = 1
    requirement_id: Identity
    state: ReadinessState
    reason_code: Identity | None = None
    reason: Annotated[str, Field(max_length=2000)] = ""
    checked_revision: Revision | None = None
    checked_at: float
    expires_at: float
    resolved_refs: tuple[Identity, ...] = Field(default=(), max_length=128)
    provenance: tuple[Identity, ...] = Field(default=(), max_length=32)
    candidate_refs: tuple[Identity, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_window(self) -> ReadinessResult:
        if self.expires_at < self.checked_at:
            raise ValueError("readiness expiry precedes its check")
        if self.state == "ready" and (self.reason_code or self.reason):
            raise ValueError("ready results cannot carry a blocker")
        if self.state != "ready" and not self.reason_code:
            raise ValueError("non-ready results require a reason_code")
        for values, label in (
            (self.resolved_refs, "resolved_refs"),
            (self.provenance, "provenance"),
            (self.candidate_refs, "candidate_refs"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        return self


class PrepareResult(Contract):
    """Merged preparation result for one action and one scoped caller."""

    schema_version: Literal[1] = 1
    app_id: Identity
    action_id: Identity
    descriptor_digest: Identity
    state: Literal["ready", "blocked", "unknown"]
    requirements: tuple[SetupRequirement, ...] = ()
    results: tuple[ReadinessResult, ...] = ()
    checked_at: float
    expires_at: float

    @model_validator(mode="after")
    def validate_results(self) -> PrepareResult:
        ids = [item.id for item in self.requirements]
        result_ids = [item.requirement_id for item in self.results]
        if len(ids) != len(set(ids)) or len(result_ids) != len(
            set(result_ids),
        ):
            raise ValueError("prepare requirement IDs must be unique")
        if set(ids) != set(result_ids):
            raise ValueError("prepare results must match requirements")
        expected = "ready"
        if any(item.state == "unknown" for item in self.results):
            expected = "unknown"
        if any(
            item.state not in {"ready", "unknown"} for item in self.results
        ):
            expected = "blocked"
        if self.state != expected:
            raise ValueError("prepare state does not match readiness results")
        if self.expires_at < self.checked_at:
            raise ValueError("prepare expiry precedes its check")
        return self

    @property
    def blocking_results(self) -> tuple[ReadinessResult, ...]:
        return tuple(item for item in self.results if item.state != "ready")


class SetupEntryDescriptor(Contract):
    """App-owned presentation target registered against its manifest."""

    schema_version: Literal[1] = 1
    id: Identity
    entry_ref: Identity
    focus: Identity
    presentations: tuple[SetupPresentation, ...] = Field(min_length=1)
    context_schema_version: Identity = "pawapp:setup-context@1"

    @model_validator(mode="after")
    def validate_presentations(self) -> SetupEntryDescriptor:
        if len(set(self.presentations)) != len(self.presentations):
            raise ValueError("setup presentations must be unique")
        return self


class SuggestedValue(Contract):
    """A non-secret suggestion whose source remains visible to the App."""

    name: Identity
    value: Any
    provenance: Identity

    @model_validator(mode="after")
    def validate_json(self) -> SuggestedValue:
        canonical_json(self.value)
        return self


class SetupRequest(Contract):
    """Host-owned durable request. Scope is derived, not caller supplied."""

    schema_version: Literal[1] = 1
    request_id: Identity
    scope: TaskScope
    descriptor_digest: Identity
    entry_id: Identity
    requirement_ids: tuple[Identity, ...] = Field(min_length=1)
    origin_ref: Identity
    task_id: Identity | None = None
    action_id: Identity | None = None
    project_ref: ProjectRef | None = None
    plan_digest: Identity | None = None
    expected_revisions: dict[Identity, Revision] = Field(default_factory=dict)
    scopes: tuple[Identity, ...] = ()
    suggested_values: tuple[SuggestedValue, ...] = ()
    presentation: SetupPresentation
    expires_at: float
    return_target: Identity
    state: SetupState = "requested"
    created_at: float
    updated_at: float

    @model_validator(mode="after")
    def validate_request(self) -> SetupRequest:
        if len(set(self.requirement_ids)) != len(self.requirement_ids):
            raise ValueError("setup requirement IDs must be unique")
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("setup scopes must be unique")
        if self.expires_at <= self.created_at:
            raise ValueError("setup expiry must follow creation")
        if self.updated_at < self.created_at:
            raise ValueError("setup update precedes creation")
        return self


class SetupResult(Contract):
    """Terminal App-backend receipt; saved does not imply readiness."""

    schema_version: Literal[1] = 1
    request_id: Identity
    result_id: Identity
    outcome: SetupOutcome
    changed_requirement_ids: tuple[Identity, ...] = ()
    config_revisions: dict[Identity, Revision] = Field(default_factory=dict)
    public_refs: tuple[Identity, ...] = ()
    pending_effects: tuple[Identity, ...] = ()
    error_code: Identity | None = None

    @model_validator(mode="after")
    def validate_result(self) -> SetupResult:
        if len(set(self.changed_requirement_ids)) != len(
            self.changed_requirement_ids,
        ):
            raise ValueError("changed requirement IDs must be unique")
        if self.outcome == "failed" and self.error_code is None:
            raise ValueError("failed setup requires an error_code")
        if self.outcome != "failed" and self.error_code is not None:
            raise ValueError("only failed setup accepts an error_code")
        return self


class SetupOpenAction(Contract):
    """Safe navigation returned by a registered App entry handler."""

    schema_version: Literal[1] = 1
    app_id: Identity
    request_id: Identity
    entry_id: Identity
    presentation: SetupPresentation
    path: Annotated[str, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def validate_path(self) -> SetupOpenAction:
        prefix = f"/apps/{self.app_id}"
        path = self.path.split("?", 1)[0]
        if path != prefix and not path.startswith(prefix + "/"):
            raise ValueError("setup path must belong to the App")
        if any(item in self.path for item in ("\\", "#", "%")):
            raise ValueError("setup path must be a local App path")
        if ".." in path.split("/"):
            raise ValueError("setup path cannot traverse directories")
        return self
