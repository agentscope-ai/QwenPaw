# -*- coding: utf-8 -*-
"""Built-in gate catalog for user-editable loop modes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Type

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config.config import DoomLoopConfig, DoomLoopStageConfig
from .gates.base import StopGate
from .gates.completion import CompletionRubricGate
from .gates.doom_loop import DoomLoopGate
from .gates.iteration import IterationGate
from .gates.limits import TimeoutGate, TokenBudgetGate, ToolCallBudgetGate
from .gates.rubric import StandaloneRubricGate


class _Params(BaseModel):
    """Strict base for gate construction parameters."""

    model_config = ConfigDict(extra="forbid")


class IterationParams(_Params):
    """Iteration gate parameters."""

    max_iterations: int = Field(default=40, ge=1, le=500)


class DoomLoopParams(_Params):
    """Repetition protection parameters."""

    window_size: int = Field(default=3, ge=2, le=20)
    similarity_threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    stages: list[DoomLoopStageConfig] = Field(
        default_factory=lambda: DoomLoopConfig().stages,
    )


class TokenBudgetParams(_Params):
    """Token budget parameters."""

    max_total_tokens: int | None = Field(default=120_000, ge=1)
    max_prompt_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_limit(self) -> "TokenBudgetParams":
        """Require at least one effective token limit."""
        if not any(
            (
                self.max_total_tokens,
                self.max_prompt_tokens,
                self.max_completion_tokens,
            ),
        ):
            raise ValueError("At least one token limit is required")
        return self


class TimeoutParams(_Params):
    """Wall-clock boundary parameters."""

    max_seconds: float = Field(default=1800.0, ge=1.0, le=86400.0)


class ToolCallBudgetParams(_Params):
    """Global and per-tool call limits."""

    max_calls: int | None = Field(default=30, ge=1, le=10000)
    per_tool: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_limits(self) -> "ToolCallBudgetParams":
        """Reject empty and non-positive tool limits."""
        if self.max_calls is None and not self.per_tool:
            raise ValueError("At least one tool call limit is required")
        if any(not name or limit < 1 for name, limit in self.per_tool.items()):
            raise ValueError(
                "Per-tool limits require names and positive values",
            )
        return self


class TextResponseRetryParams(_Params):
    """Text-only response retry parameters."""

    prompt: str = Field(
        default=("Verify the task before stopping. Continue if work remains."),
        min_length=1,
        max_length=8192,
    )
    max_interventions: int = Field(default=1, ge=1, le=10)


class RubricCriterionParams(_Params):
    """One completion rubric criterion."""

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    description: str = Field(min_length=1, max_length=1000)
    required: bool = True
    weight: float = Field(default=1.0, gt=0.0, le=100.0)


class CompletionRubricParams(_Params):
    """Structured completion evaluator parameters."""

    criteria: list[RubricCriterionParams] = Field(
        min_length=1,
        max_length=20,
    )
    pass_threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    max_revisions: int = Field(default=2, ge=0, le=10)
    evaluate_when: Literal["text_response"] = "text_response"
    include_last_tool_results: int = Field(default=5, ge=0, le=20)
    on_grader_error: Literal["stop", "continue_once"] = "stop"

    @model_validator(mode="after")
    def unique_criteria(self) -> "CompletionRubricParams":
        """Require stable unique criterion IDs."""
        ids = [criterion.id for criterion in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("Rubric criterion IDs must be unique")
        return self


@dataclass(frozen=True)
class GateCatalogEntry:
    """One QwenPaw-owned gate available to custom modes."""

    type: str
    title: str
    description: str
    category: str
    params_model: Type[BaseModel]
    factory: Callable[[BaseModel], StopGate]
    cost: Literal["none", "model_call"] = "none"
    conflicts_with: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        """Return stable frontend metadata and JSON Schema."""
        return {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "schema": self.params_model.model_json_schema(),
            "cost": self.cost,
            "conflicts_with": list(self.conflicts_with),
        }


class GateCatalog:
    """Explicit whitelist of built-in user-configurable gates."""

    def __init__(self, entries: list[GateCatalogEntry]) -> None:
        self._entries = {entry.type: entry for entry in entries}

    def describe(self) -> list[dict[str, Any]]:
        """List entries in registration order."""
        return [entry.describe() for entry in self._entries.values()]

    def validate_params(self, gate_type: str, params: dict) -> BaseModel:
        """Validate parameters for one catalog type."""
        entry = self._entry(gate_type)
        return entry.params_model.model_validate(params)

    def create(self, gate_type: str, params: dict) -> StopGate:
        """Construct one built-in gate from validated data."""
        entry = self._entry(gate_type)
        validated = entry.params_model.model_validate(params)
        return entry.factory(validated)

    def conflicts(self, gate_type: str) -> tuple[str, ...]:
        """Return incompatible gate types."""
        return self._entry(gate_type).conflicts_with

    def _entry(self, gate_type: str) -> GateCatalogEntry:
        try:
            return self._entries[gate_type]
        except KeyError as exc:
            raise ValueError(
                f"Unknown built-in gate type: {gate_type}",
            ) from exc


def _dump(params: BaseModel) -> dict[str, Any]:
    return params.model_dump()


def _completion_gate(params: BaseModel) -> StopGate:
    """Construct the evaluator without UI-only trigger metadata."""
    values = params.model_dump()
    values.pop("evaluate_when", None)
    return CompletionRubricGate(**values)


def _entries() -> list[GateCatalogEntry]:
    """Build the immutable catalog declaration."""
    return [
        GateCatalogEntry(
            type="iteration",
            title="Iteration limit",
            description="Stop after a fixed number of loop iterations.",
            category="limits",
            params_model=IterationParams,
            factory=lambda params: IterationGate(**_dump(params)),
        ),
        GateCatalogEntry(
            type="doom_loop",
            title="Repetition protection",
            description="Detect repeated tool calls and change strategy.",
            category="safety",
            params_model=DoomLoopParams,
            factory=lambda params: DoomLoopGate(**_dump(params)),
        ),
        GateCatalogEntry(
            type="token_budget",
            title="Token budget",
            description="Limit prompt and completion token usage.",
            category="limits",
            params_model=TokenBudgetParams,
            factory=lambda params: TokenBudgetGate(**_dump(params)),
        ),
        GateCatalogEntry(
            type="timeout",
            title="Time limit",
            description="Stop at a loop boundary after elapsed time.",
            category="limits",
            params_model=TimeoutParams,
            factory=lambda params: TimeoutGate(**_dump(params)),
        ),
        GateCatalogEntry(
            type="tool_call_budget",
            title="Tool-call budget",
            description="Limit all calls and selected tools.",
            category="limits",
            params_model=ToolCallBudgetParams,
            factory=lambda params: ToolCallBudgetGate(**_dump(params)),
        ),
        GateCatalogEntry(
            type="text_response_retry",
            title="Early-stop retry",
            description="Prompt the agent to verify before ending.",
            category="behavior",
            params_model=TextResponseRetryParams,
            factory=lambda params: StandaloneRubricGate(**_dump(params)),
            conflicts_with=("completion_rubric",),
        ),
        GateCatalogEntry(
            type="completion_rubric",
            title="Completion rubric",
            description="Evaluate explicit completion criteria.",
            category="quality",
            params_model=CompletionRubricParams,
            factory=_completion_gate,
            cost="model_call",
            conflicts_with=("text_response_retry",),
        ),
    ]


_CATALOG = GateCatalog(_entries())


def get_gate_catalog() -> GateCatalog:
    """Return the process-wide immutable built-in catalog."""
    return _CATALOG


__all__ = [
    "CompletionRubricParams",
    "DoomLoopParams",
    "GateCatalog",
    "GateCatalogEntry",
    "IterationParams",
    "TextResponseRetryParams",
    "TimeoutParams",
    "TokenBudgetParams",
    "ToolCallBudgetParams",
    "get_gate_catalog",
]
