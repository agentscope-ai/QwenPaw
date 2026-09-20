# -*- coding: utf-8 -*-
"""Model identity, capability, and user configuration records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field, model_validator

from .context_windows import DEFAULT_CONTEXT_WINDOW
from .model_ranking import RankingEvidence
from .thinking import ThinkingControl


def release_date(value: Any) -> str | None:
    """Normalize documented release dates and API creation timestamps."""
    try:
        if type(value) in (int, float) and value > 0:
            date = datetime.fromtimestamp(value, tz=timezone.utc)
        elif isinstance(value, datetime):
            date = value
        elif isinstance(value, str) and value.strip():
            date = datetime.fromisoformat(value.replace(f"Z", f"+00:00"))
        else:
            return None
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")
    released_at: str | None = Field(
        default=None,
        description=f"Documented model release or creation date.",
    )
    supports_multimodal: bool | None = Field(
        default=None,
        description="Whether this model supports multimodal input "
        "(image/audio/video). None means not yet probed.",
    )
    supports_image: bool | None = Field(
        default=None,
        description="Whether this model supports image input. "
        "None means not yet probed.",
    )
    supports_video: bool | None = Field(
        default=None,
        description="Whether this model supports video input. "
        "None means not yet probed.",
    )
    probe_source: str | None = Field(
        default=None,
        description=(
            "Probe result source: 'documentation' (from docs)"
            " or 'probed' (actual probe)"
        ),
    )
    is_free: bool = Field(
        default=False,
        description="Whether this model is free to use (e.g., no API cost)",
    )
    is_recommended: bool = Field(
        default=False,
        description="Whether the maintained catalog recommends this model.",
    )
    source: Literal["builtin", "discovered", "user"] = Field(
        default="builtin",
        description="Where the model entry came from.",
    )
    discovered_at: str | None = Field(
        default=None,
        description="UTC timestamp of the latest successful discovery.",
    )
    discovery_origin: Literal["api", "catalog", "both"] | None = Field(
        default=None,
        description="Candidate source: provider API, catalog, or both.",
    )
    availability_status: Literal[
        "available",
        "permission_denied",
        "model_not_found",
        "incompatible_api",
        "rate_limited",
        "transient_error",
        "unverified",
    ] = Field(default="unverified")
    availability_message: str | None = Field(default=None)
    availability_http_status: int | None = Field(default=None)
    availability_retryable: bool = Field(default=True)
    availability_checked_at: str | None = Field(default=None)
    availability_verification: Literal[
        "live",
        "provider_only",
        "catalog",
        "unverified",
    ] = Field(default="unverified")
    config_overrides: List[str] = Field(
        default_factory=list,
        description="Model fields explicitly changed by the user.",
    )
    max_output_length: int | None = Field(
        default=None,
        ge=1,
        description="Maximum output capability reported for this model.",
    )
    max_output_length_source: Literal[
        "api",
        "catalog",
        "adapter",
        "user",
        "unknown",
        "template",
    ] = Field(
        default="unknown",
        description="Source of the maximum output capability.",
    )
    max_output_length_updated_at: str | None = Field(
        default=None,
        description="UTC timestamp of the output capability update.",
    )
    max_input_length: int = Field(
        default=DEFAULT_CONTEXT_WINDOW,
        ge=1000,
        description="Maximum input context window size (tokens). "
        "Controls when context compaction is triggered.",
    )
    max_input_length_configured: bool = Field(
        default=False,
        description=(
            "Whether max_input_length was explicitly configured. This keeps "
            "an intentional 131072-token override distinct from the default."
        ),
    )
    max_input_length_auto_detected: int | None = Field(
        default=None,
        ge=1000,
        description="Context window reported by the provider API.",
    )
    template_id: str | None = None
    ranking_id: str | None = None
    ranking: RankingEvidence | None = None
    recommendation_reason: str = f"unranked"
    supports_audio: bool | None = None
    supports_tool_calling: bool | None = None
    billing_source: str = f"unknown"
    billing_checked_at: str | None = None
    input_token_limit: int | None = Field(default=None, ge=1)
    input_token_limit_source: str = f"unknown"
    billing: Literal["free", "paid", "unknown"] = f"unknown"
    auto_enabled: bool = False
    requires_paid_confirmation: bool = False
    remote_missing: bool = False
    capability_provenance: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
    )
    effective_max_input_length: int = DEFAULT_CONTEXT_WINDOW
    automatic_max_input_length: int = DEFAULT_CONTEXT_WINDOW
    context_length_source: str | None = None
    generate_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-model generation parameters that override "
        "provider-level generate_kwargs.",
    )
    relay_reasoning: bool = Field(
        default=True,
        description="Whether to relay reasoning_content (thinking traces) "
        "back in subsequent turns. When False the formatter omits "
        "reasoning_content from assistant wire messages.",
    )

    @model_validator(mode="before")
    @classmethod
    def _compat_preserve_thinking(cls, data: Any) -> Any:
        """Normalize legacy model fields and obsolete probe results."""
        if not isinstance(data, dict):
            return data
        if "max_tokens" in data:
            raise ValueError(
                "ModelInfo.max_tokens is no longer supported; use "
                "max_output_length for capability metadata or "
                "generate_kwargs.max_tokens for a request limit",
            )
        if "preserve_thinking" in data:
            data.setdefault("relay_reasoning", data.pop("preserve_thinking"))

        message = str(data.get("availability_message") or "").lower()
        obsolete_tool_probe = (
            data.get("supports_tool_calling") is False
            or "tool probe" in message
            or "tool calling check failed" in message
            or "tool_choice" in message
        )
        if (
            data.get("availability_status") == "incompatible_api"
            and obsolete_tool_probe
        ):
            data["availability_status"] = "unverified"
            data["availability_message"] = None
            data["availability_http_status"] = None
            data["availability_retryable"] = True
            data["availability_checked_at"] = None
            data["availability_verification"] = "unverified"
        return data

    thinking_control: ThinkingControl | None = None

    thinking_enabled: bool | None = Field(
        default=None,
        description="Tri-state thinking toggle: None=auto (don't send, "
        "use model default), True=enable, False=disable. "
        "Provider-specific mapping applies.",
    )

    thinking_budget: int | None = Field(
        default=None,
        ge=1,
        description="Token budget for thinking. Provider-specific: "
        "DashScope/Anthropic use thinking_budget, Gemini uses "
        "thinking_config.thinking_budget.",
    )
    reasoning_effort: str | None = Field(
        default=None,
        description="Reasoning effort level: 'low', 'medium', 'high'. "
        "Used by OpenAI-family providers.",
    )
    thinking_param_style: str | None = Field(
        default=None,
        description="Override provider-level thinking_param_style for this "
        "model. 'budget' shows Slider, 'effort' shows Select.",
    )
    reasoning_effort_options: List[str] | None = Field(
        default=None,
        description="Override provider-level reasoning_effort_options for "
        "this model.",
    )
    thinking_budget_range: List[int] | None = Field(
        default=None,
        description="Override provider-level thinking_budget_range [min, max] "
        "for this model.",
    )
    supports_agent_thinking: bool | None = Field(
        default=None,
        description=(
            "Whether the provider can apply an agent-level thinking override "
            "to this model. Derived in ProviderInfo responses."
        ),
    )


class ExtendedModelInfo(ModelInfo):
    """Extended model info with additional metadata for providers."""

    provider: str = Field(
        default="",
        description="Provider/series (e.g., 'openai', 'google')",
    )
    input_modalities: List[str] = Field(
        default_factory=list,
        description="Supported input modalities",
    )
    output_modalities: List[str] = Field(
        default_factory=list,
        description="Supported output modalities",
    )
    pricing: Dict[str, str] = Field(
        default_factory=dict,
        description="Pricing info (prompt/completion)",
    )
