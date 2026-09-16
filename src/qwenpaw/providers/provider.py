# -*- coding: utf-8 -*-
"""Definition of Provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Type

from agentscope.model import ChatModelBase
from pydantic import BaseModel, ConfigDict, Field, model_validator

from qwenpaw.exceptions import ProviderError

from .context_windows import DEFAULT_CONTEXT_WINDOW, resolve_context_window

if TYPE_CHECKING:
    from .multimodal_prober import ProbeResult


_AGENT_THINKING_LEVEL: ContextVar[str] = ContextVar(
    "qwenpaw_agent_thinking_level",
    default="inherit",
)
AGENT_THINKING_BUDGETS = {
    "low": 2_048,
    "medium": 8_192,
    "high": 32_768,
}
_CUSTOM_PROVIDER_ID_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*",
)
_WINDOWS_RESERVED_PROVIDER_IDS = (
    {
        "AUX",
        "CON",
        "NUL",
        "PRN",
    }
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def provider_identity_key(provider_id: str) -> str:
    """Return the portable, case-insensitive identity for a provider ID."""
    return provider_id.casefold()


def validate_custom_provider_id(provider_id: str) -> str:
    """Validate a custom provider ID as a portable file name stem."""
    if not isinstance(provider_id, str) or not provider_id:
        raise ValueError("Provider ID must be a non-empty string.")
    if not _CUSTOM_PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise ValueError(
            "Provider ID must start with an ASCII letter or digit and only "
            "contain ASCII letters, digits, dots, underscores, or hyphens.",
        )
    if provider_id in {".", ".."} or provider_id.endswith((".", " ")):
        raise ValueError("Provider ID cannot end with a dot or space.")
    device_name = provider_id.split(".", maxsplit=1)[0].upper()
    if device_name in _WINDOWS_RESERVED_PROVIDER_IDS:
        raise ValueError(
            f"Provider ID '{provider_id}' is reserved on Windows.",
        )
    return provider_id


@contextmanager
def agent_thinking_level(level: str) -> Iterator[None]:
    """Apply an agent-level thinking override while constructing a model."""
    token = _AGENT_THINKING_LEVEL.set(level)
    try:
        yield
    finally:
        _AGENT_THINKING_LEVEL.reset(token)


class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")
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


class ModelConnectionResult(BaseModel):
    """Structured evidence from a basic model connection check."""

    success: bool
    message: str = ""
    http_status: int | None = None
    error_kind: str | None = None
    verification: Literal[
        "live",
        "provider_only",
        "catalog",
        "unverified",
    ] = "live"

    def __iter__(self):
        """Keep compatibility with providers/tests that unpack two values."""
        yield self.success
        yield self.message


class ProviderInfo(BaseModel):
    """Provider configuration and metadata."""

    # Allow flexible typing for test environments where ModelInfo
    # may be reloaded (different object identity)
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_default=False,
    )

    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Human-readable provider name")
    base_url: str = Field(default="", description="API base URL")
    api_key: str = Field(default="", description="API key for authentication")
    chat_model: str = Field(
        default="OpenAIChatModel",
        description="AgentScope ChatModel name (e.g., 'OpenAIChatModel')",
    )
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="List of pre-defined models",
    )
    extra_models: List[ModelInfo] = Field(
        default_factory=list,
        description="List of models explicitly added by the user",
    )
    discovered_models: List[ModelInfo] = Field(
        default_factory=list,
        description="Last model list fetched from the provider API",
    )
    models_last_synced_at: str | None = Field(
        default=None,
        description="UTC timestamp of the latest successful model sync",
    )
    models_last_sync_error: str | None = Field(
        default=None,
        description="Most recent model discovery error, if any",
    )
    models_syncing: bool = Field(
        default=False,
        description="Whether an in-process model discovery task is running.",
    )
    hidden_model_ids: List[str] = Field(
        default_factory=list,
        description="Remote model IDs hidden by the user.",
    )
    removed_model_ids: List[str] = Field(
        default_factory=list,
        description="Model IDs explicitly removed by the user.",
    )
    discovery_strategy: Literal[
        "openai_models",
        "anthropic_models",
        "gemini_models",
        "provider_specific",
        "catalog_only",
        "unsupported",
    ] = Field(
        default="unsupported",
        description="How this provider obtains its model catalog.",
    )
    discovery_support_reason: str = Field(
        default="",
        description="Why dynamic discovery is unavailable or specialized.",
    )
    discovery_requires_auth: bool = Field(
        default=True,
        description="Whether discovery requires configured credentials.",
    )
    model_sync_mode: Literal["startup", "manual", "disabled"] = Field(
        default="manual",
        description="When model discovery runs automatically.",
    )

    api_key_prefix: str = Field(
        default="",
        description="Expected prefix for the API key (e.g., 'sk-')",
    )
    api_key_prefixes: List[str] = Field(
        default_factory=list,
        description=(
            "List of accepted API key prefixes. "
            "When non-empty, validation accepts any prefix in this list; "
            "otherwise it falls back to api_key_prefix."
        ),
    )
    is_local: bool = Field(
        default=False,
        description="Whether this provider is for a local hosting platform",
    )
    freeze_url: bool = Field(
        default=False,
        description="Whether the base_url should be frozen (not editable)",
    )
    require_api_key: bool = Field(
        default=True,
        description="Whether this provider requires an API key",
    )
    is_custom: bool = Field(
        default=False,
        description=("Whether this provider is user-created (not built-in)."),
    )
    support_model_discovery: bool = Field(
        default=False,
        description=(
            "Whether this provider supports fetching available models"
            " from the provider's API"
        ),
    )
    merge_with_catalog: bool = Field(
        default=False,
        description=(
            "Whether to merge the maintained catalog with API discovery "
            "results, for providers whose /models returns only a subset"
        ),
    )
    support_connection_check: bool = Field(
        default=True,
        description=(
            "Whether this provider supports checking connection to the API "
            "without model configuration"
        ),
    )
    generate_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Generation parameters for agentscope chat models.",
    )
    custom_headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Custom HTTP headers to include in every API request.",
    )
    auth_mode: Literal["api_key", "auth_token"] = Field(
        default="api_key",
        description=(
            "Authentication mode: 'api_key' sends x-api-key header, "
            "'auth_token' sends Authorization: Bearer header. "
            "Only applies to Anthropic-compatible providers."
        ),
    )
    supports_oauth: bool = Field(
        default=False,
        description="Whether this provider supports OAuth login",
    )
    oauth_connected: bool = Field(
        default=False,
        description="Whether OAuth is currently connected",
    )
    is_free_tier: bool = Field(
        default=False,
        description="Whether this provider offers a free tier",
    )
    provider_group: str = Field(
        default="",
        description="Group key for same-brand providers",
    )
    provider_group_name: str = Field(
        default="",
        description="Display name for the provider group",
    )
    provider_variant: str = Field(
        default="",
        description="Variant identifier within a group",
    )
    thinking_param_style: str | None = Field(
        default=None,
        description="Which thinking-parameter UI to show: "
        "'budget' (Slider) or 'effort' (Select). "
        "None means the provider does not support thinking config.",
    )
    reasoning_effort_options: List[str] = Field(
        default_factory=lambda: [
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        ],
        description="Valid reasoning_effort values for this provider.",
    )
    thinking_budget_range: List[int] = Field(
        default_factory=lambda: [1, 81920],
        description="[min, max] range for thinking_budget Slider.",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the provider "
        "(e.g., api_key_url, api_key_hint).",
    )

    @model_validator(mode="after")
    def _normalize_model_sources(self) -> "ProviderInfo":
        """Assign sources to legacy entries that predate source tracking."""
        for model in self.models:
            if "source" not in model.model_fields_set:
                model.source = "builtin"
        for model in self.discovered_models:
            model.source = "discovered"
        for model in self.extra_models:
            if "source" not in model.model_fields_set:
                model.source = "user"
        return self


class Provider(ProviderInfo, ABC):  # pylint: disable=too-many-public-methods
    """Represents a provider instance with its configuration."""

    @abstractmethod
    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if the provider is reachable with the current config."""

    @abstractmethod
    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch the list of available models from the provider."""

    @abstractmethod
    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,  # pylint: disable=unused-argument
    ) -> ModelConnectionResult | tuple[bool, str]:
        """Check if a specific model is reachable/usable."""

    @staticmethod
    def sanitize_connection_message(message: str) -> str:
        """Remove likely credential values from provider error text."""
        credential_patterns = (
            r"(?i)(api[_ -]?key|x-api-key|access[_ -]?token|token)"
            r"(\s*[=:]\s*)[^,;\s]+",
            r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^,;\s]+",
        )
        message = re.sub(
            credential_patterns[0],
            r"\1\2[redacted]",
            message,
        )
        message = re.sub(
            credential_patterns[1],
            r"\1[redacted]",
            message,
        )
        return message

    @classmethod
    def connection_error_message(cls, exc: Exception) -> str:
        """Format an SDK exception while preserving its HTTP status."""
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        detail = cls.sanitize_connection_message(
            str(exc) or exc.__class__.__name__,
        )
        return f"status={status}: {detail}" if status is not None else detail

    async def add_model(
        self,
        model_info: ModelInfo,
        target: str = "extra_models",
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Add a model to the provider's model list."""
        model_info.id = model_info.id.strip()
        was_removed = model_info.id in self.removed_model_ids
        self.removed_model_ids = [
            model_id
            for model_id in self.removed_model_ids
            if model_id != model_info.id
        ]
        # A discovered entry is a catalog candidate, not a configured model.
        # It may therefore be copied into extra_models when the user adds it.
        if any(
            model.id.strip() == model_info.id
            for model in (*self.models, *self.extra_models)
        ):
            if was_removed:
                return True, ""
            return False, f"Model '{model_info.id}' already exists"
        if target == "extra_models":
            model_info.source = "user"
            self.extra_models.append(model_info)  # pylint: disable=no-member
        elif target == "models":
            self.models.append(model_info)  # pylint: disable=no-member
        else:
            return False, f"Invalid target '{target}' for adding model"
        return True, ""

    async def delete_model(
        self,
        model_id: str,
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Delete a model from the provider's model list."""
        model_id = model_id.strip()
        if not model_id:
            return False, "Model ID cannot be empty"
        removed_ids = set(self.removed_model_ids)
        removed_ids.add(model_id)
        self.removed_model_ids = sorted(removed_ids)
        self.extra_models = [
            model
            for model in self.extra_models
            if model.id.strip() != model_id
        ]
        self.discovered_models = [
            model
            for model in self.discovered_models
            if model.id.strip() != model_id
        ]
        return True, ""

    @staticmethod
    def _normalize_model_id_list(value: Any, current: List[str]) -> List[str]:
        """Normalize an optional persisted model ID list."""
        if value is None:
            return current
        return list(
            dict.fromkeys(
                str(model_id).strip()
                for model_id in value
                if str(model_id).strip()
            ),
        )

    def update_config(self, config: Dict) -> None:
        """Update provider configuration with the given dictionary."""
        if "name" in config and config["name"] is not None:
            self.name = str(config["name"]).strip()
        if (
            not self.freeze_url
            and "base_url" in config
            and config["base_url"] is not None
        ):
            self.base_url = str(config["base_url"]).strip()
        if "api_key" in config and config["api_key"] is not None:
            self.api_key = str(config["api_key"]).strip()
        if (
            self.is_custom
            and "chat_model" in config
            and config["chat_model"] is not None
        ):
            self.chat_model = str(config["chat_model"])
        if "api_key_prefix" in config and config["api_key_prefix"] is not None:
            self.api_key_prefix = str(config["api_key_prefix"])
        if (
            "api_key_prefixes" in config
            and config["api_key_prefixes"] is not None
        ):
            self.api_key_prefixes = [
                str(p) for p in config["api_key_prefixes"] if p is not None
            ]
        if (
            "generate_kwargs" in config
            and config["generate_kwargs"] is not None
            and isinstance(config["generate_kwargs"], dict)
        ):
            self.generate_kwargs = config["generate_kwargs"]
        if (
            "custom_headers" in config
            and config["custom_headers"] is not None
            and isinstance(config["custom_headers"], dict)
        ):
            self.custom_headers = {
                str(k): str(v) for k, v in config["custom_headers"].items()
            }
        if "auth_mode" in config and config["auth_mode"] in (
            "api_key",
            "auth_token",
        ):
            self.auth_mode = config["auth_mode"]
        if "extra_models" in config and config["extra_models"] is not None:
            # Always go through model_validate with dict data to
            # avoid class-identity issues from dual module loading.
            self.extra_models = [
                ModelInfo.model_validate(
                    (
                        model.model_dump()
                        if isinstance(model, BaseModel)
                        else model
                    ),
                )
                for model in config["extra_models"]
            ]
            for model in self.extra_models:
                model.source = "user"
        self.hidden_model_ids = self._normalize_model_id_list(
            config.get("hidden_model_ids"),
            self.hidden_model_ids,
        )
        self.removed_model_ids = self._normalize_model_id_list(
            config.get("removed_model_ids"),
            self.removed_model_ids,
        )

    def all_models(self) -> List[ModelInfo]:
        """Return configured models only."""
        return Provider.configured_models(self)

    def configured_models(self) -> List[ModelInfo]:
        """Return the effective configured model list."""
        removed = set(getattr(self, "removed_model_ids", []))
        ordered_ids: list[str] = []
        by_id: dict[str, ModelInfo] = {}
        for collection in (
            getattr(self, "models", []),
            getattr(self, "extra_models", []),
        ):
            for model in collection:
                if model.id not in by_id:
                    ordered_ids.append(model.id)
                by_id[model.id] = model
        return [
            by_id[model_id]
            for model_id in ordered_ids
            if model_id not in removed
        ]

    def discovery_candidates(self) -> List[ModelInfo]:
        """Return models visible to the add-model discovery flow."""
        ordered_ids: list[str] = []
        by_id: dict[str, ModelInfo] = {}
        for collection in (
            getattr(self, "models", []),
            getattr(self, "discovered_models", []),
        ):
            for model in collection:
                if model.id not in by_id:
                    ordered_ids.append(model.id)
                by_id[model.id] = model
        hidden = set(getattr(self, "hidden_model_ids", []))
        removed = set(getattr(self, "removed_model_ids", []))
        return [
            by_id[model_id]
            for model_id in ordered_ids
            if model_id not in hidden and model_id not in removed
        ]

    def get_chat_model_cls(self) -> Type[ChatModelBase]:
        """Return the chat model class associated with this provider."""
        import agentscope.model

        chat_model_cls = getattr(
            agentscope.model,
            self.chat_model,
            None,
        )
        if chat_model_cls is None:
            raise ProviderError(
                message=(
                    f"Chat model class '{self.chat_model}' "
                    f"not found for provider '{self.name}'."
                ),
            )
        return chat_model_cls

    @staticmethod
    def _deep_merge(
        base: Dict[str, Any],
        override: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Recursively merge *override* into *base* (returns a new dict)."""
        result = dict(base)
        for key, val in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(val, dict)
            ):
                result[key] = Provider._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    def get_effective_generate_kwargs(self, model_id: str) -> Dict[str, Any]:
        """Return merged generate_kwargs: provider-level as base, model-level
        overrides on top (deep merge for nested dicts).

        Always returns a new dict so callers never mutate provider state.
        """
        for model in Provider.all_models(self):
            if model.id == model_id:
                result = (
                    self._deep_merge(
                        self.generate_kwargs,
                        model.generate_kwargs,
                    )
                    if model.generate_kwargs
                    else dict(self.generate_kwargs)
                )
                self._apply_agent_thinking_level(result, model_id)
                return result
        result = dict(self.generate_kwargs)
        self._apply_agent_thinking_level(result, model_id)
        return result

    def supports_agent_thinking(self, model_id: str) -> bool:
        """Return whether agent-level thinking maps to this model."""
        if self.chat_model == "DashScopeChatModel":
            return True
        info = self.get_model_info(model_id)
        if info is None:
            return False
        if (
            getattr(info, "thinking_enabled", None) is not None
            or getattr(info, "thinking_param_style", None) is not None
        ):
            return True
        if self.chat_model in {"AnthropicChatModel", "GeminiChatModel"}:
            return True
        normalized = model_id.strip().lower().rsplit("/", maxsplit=1)[-1]
        return self.chat_model in {
            "OpenAIChatModel",
            "OpenAIResponseModel",
        } and (
            normalized.startswith("gpt-5")
            or (
                len(normalized) > 1
                and normalized[0] == "o"
                and normalized[1].isdigit()
            )
        )

    def _apply_agent_thinking_level(
        self,
        effective: Dict[str, Any],
        model_id: str,
    ) -> None:
        """Map the current agent thinking level to provider parameters."""
        level = _AGENT_THINKING_LEVEL.get()
        if level == "inherit" or not self.supports_agent_thinking(model_id):
            return
        for key in (
            "thinking_enable",
            "thinking_budget",
            "reasoning_effort",
            "thinking_config",
            "reasoning",
            "disable_thinking",
        ):
            effective.pop(key, None)
        extra_body = effective.get("extra_body")
        if isinstance(extra_body, dict):
            for key in (
                "enable_thinking",
                "thinking_budget",
                "reasoning_effort",
                "thinking",
            ):
                extra_body.pop(key, None)
        self._map_agent_thinking_level(
            effective,
            model_id,
            level,
            AGENT_THINKING_BUDGETS.get(level, 0),
        )

    def _uses_compat_thinking_controls(self, model_id: str) -> bool:
        """Whether the model declares OpenAI-compatible thinking flags.

        Custom providers and domestic compatibility endpoints (Qwen,
        DeepSeek, ...) reuse ``OpenAIChatModel``; their thinking
        controls are declared through model metadata rather than the
        official OpenAI reasoning parameter set.
        """
        info = self.get_model_info(model_id)
        return info is not None and (
            getattr(info, "thinking_enabled", None) is not None
            or getattr(info, "thinking_param_style", None) is not None
        )

    @staticmethod
    def _openai_chat_off_effort(model_id: str) -> str:
        """Lowest documented Chat Completions effort that turns Off.

        Only the newest documented models accept
        ``reasoning_effort="none"``; earlier gpt-5 families degrade to
        ``minimal`` and o-series to ``low`` so an Off request means
        "least reasoning the model accepts" instead of a 400.
        """
        # Lazy import: the response module imports this base module.
        from .openai_response_provider import (
            _supports_none_reasoning_effort,
        )

        if _supports_none_reasoning_effort(model_id):
            return "none"
        normalized = model_id.strip().lower().rsplit("/", maxsplit=1)[-1]
        if normalized.startswith("gpt-5"):
            return "minimal"
        return "low"

    def _map_agent_thinking_level(
        self,
        effective: Dict[str, Any],
        model_id: str,
        level: str,
        budget: int,
    ) -> None:
        """Map an agent level to the provider's wire parameters."""
        if self.chat_model == "AnthropicChatModel":
            if level == "off":
                effective["thinking_enable"] = False
            else:
                effective["thinking_enable"] = True
                effective["thinking_budget"] = budget
            return
        if self.chat_model == "GeminiChatModel":
            effective["thinking_config"] = {
                "thinking_budget": 0 if level == "off" else budget,
            }
            return
        if self.chat_model == "OpenAIResponseModel":
            if level == "off":
                # The Responses call layer translates this neutral flag:
                # it strips ``reasoning`` and applies
                # ``reasoning.effort=none`` only where documented
                # (_supports_none_reasoning_effort).
                effective["disable_thinking"] = True
            else:
                # Responses takes ``reasoning.effort``; the Chat
                # Completions top-level ``reasoning_effort`` is not a
                # Responses parameter.
                effective["reasoning"] = {"effort": level}
            return
        if self.chat_model == "OpenAIChatModel" and level == "off":
            if self._uses_compat_thinking_controls(model_id):
                # Compatibility endpoints: the chat compat layer turns
                # this into extra_body flags (enable_thinking /
                # thinking.type), not the official ``none`` value.
                effective["disable_thinking"] = True
            else:
                effective["reasoning_effort"] = self._openai_chat_off_effort(
                    model_id,
                )
            return
        if level != "off":
            effective["reasoning_effort"] = level

    def update_model_config(  # pylint: disable=too-many-branches
        self,
        model_id: str,
        config: Dict,
    ) -> bool:
        """Update per-model configuration (e.g. generate_kwargs)."""
        for model in Provider.all_models(self):
            if model.id == model_id:
                changed_fields: list[str] = []
                if (
                    "generate_kwargs" in config
                    and config["generate_kwargs"] is not None
                    and isinstance(config["generate_kwargs"], dict)
                ):
                    generate_kwargs = dict(config["generate_kwargs"])
                    if model.generate_kwargs != generate_kwargs:
                        model.generate_kwargs = generate_kwargs
                        changed_fields.append("generate_kwargs")
                if (
                    "max_input_length" in config
                    and config["max_input_length"] is not None
                ):
                    max_input_length = int(config["max_input_length"])
                    if (
                        model.max_input_length != max_input_length
                        or not model.max_input_length_configured
                    ):
                        model.max_input_length = max_input_length
                        model.max_input_length_configured = True
                        changed_fields.extend(
                            [
                                "max_input_length",
                                "max_input_length_configured",
                            ],
                        )
                if (
                    "relay_reasoning" in config
                    and config["relay_reasoning"] is not None
                ):
                    relay_reasoning = bool(config["relay_reasoning"])
                    if model.relay_reasoning != relay_reasoning:
                        model.relay_reasoning = relay_reasoning
                        changed_fields.append("relay_reasoning")
                if "thinking_enabled" in config:
                    thinking_enabled = (
                        bool(config["thinking_enabled"])
                        if config["thinking_enabled"] is not None
                        else None
                    )
                    if model.thinking_enabled != thinking_enabled:
                        model.thinking_enabled = thinking_enabled
                        changed_fields.append("thinking_enabled")
                if "thinking_budget" in config:
                    thinking_budget = (
                        int(config["thinking_budget"])
                        if config["thinking_budget"] is not None
                        else None
                    )
                    if model.thinking_budget != thinking_budget:
                        model.thinking_budget = thinking_budget
                        changed_fields.append("thinking_budget")
                if "reasoning_effort" in config:
                    val = config["reasoning_effort"]
                    reasoning_effort = str(val) if val is not None else None
                    if model.reasoning_effort != reasoning_effort:
                        model.reasoning_effort = reasoning_effort
                        changed_fields.append("reasoning_effort")
                model.config_overrides = list(
                    dict.fromkeys(model.config_overrides + changed_fields),
                )
                return True
        return False

    def has_model(self, model_id: str) -> bool:
        """Check if the provider has a model with the given ID."""
        return self.get_model_info(model_id) is not None

    def get_model_info(self, model_id: str) -> ModelInfo | None:
        """Return the ModelInfo for *model_id*, or None."""
        if model_id in set(getattr(self, "removed_model_ids", [])):
            return None
        for collection in (
            getattr(self, "extra_models", []),
            getattr(self, "models", []),
        ):
            for model in collection:
                if model.id == model_id:
                    return model
        return None

    def get_discovered_model_info(self, model_id: str) -> ModelInfo | None:
        """Return a discovery candidate without treating it as configured."""
        if model_id in set(getattr(self, "removed_model_ids", [])):
            return None
        for model in getattr(self, "discovered_models", []):
            if model.id == model_id:
                return model
        return None

    def _get_relay_reasoning(self, model_id: str) -> bool:
        """Return the ``relay_reasoning`` flag for *model_id* (default
        True)."""
        model_info = self.get_model_info(model_id)
        if model_info is not None:
            return model_info.relay_reasoning
        return True

    def _get_thinking_config(
        self,
        model_id: str,
    ) -> tuple[bool | None, int | None, str | None]:
        """Return ``(thinking_enabled, thinking_budget, reasoning_effort)``."""
        info = self.get_model_info(model_id)
        if info is None:
            return None, None, None
        return (
            info.thinking_enabled,
            info.thinking_budget,
            info.reasoning_effort,
        )

    def _apply_thinking_config(
        self,
        model_id: str,
        effective: dict,
    ) -> None:
        """Inject per-model thinking fields into *effective* kwargs.

        Subclasses override to implement provider-specific mapping.
        The base implementation is a no-op so providers that don't
        support thinking are unaffected.
        """

    def _context_catalog_enabled(self) -> bool:
        """Whether the static context-window catalog applies here.

        Local-serving providers (Ollama) override this to ``False``: a model
        family's cloud window says nothing about a local serve that
        truncates at ``num_ctx`` -- assuming 262k for a local
        ``qwen3-coder:30b`` would disable compression while the server
        silently drops the prompt head.
        """
        return True

    def get_context_size(self, model_id: str) -> int:
        """Resolve the context window for *model_id*.

        Feeds ``model.context_size`` (which drives automatic context
        compression) AND the display/usage path
        (``config.get_model_max_input_length``) -- both MUST go through this
        method so the reported usage%% and the compaction trigger never
        diverge. Resolution lives in
        :func:`.context_windows.resolve_context_window`:
        explicitly configured ``max_input_length`` > API auto-detected value
        > non-default provider/catalog value > static pattern catalog
        (unless :meth:`_context_catalog_enabled` opts out) > 128k default.
        """
        model_info = self.get_model_info(model_id)
        discovered_info = self.get_discovered_model_info(model_id)
        configured_info = model_info or discovered_info
        auto_detected = (
            getattr(model_info, "max_input_length_auto_detected", None)
            if model_info is not None
            else None
        )
        if auto_detected is None and discovered_info is not None:
            auto_detected = getattr(
                discovered_info,
                "max_input_length_auto_detected",
                None,
            )
        return resolve_context_window(
            model_id,
            configured=(
                configured_info.max_input_length
                if configured_info is not None
                else None
            ),
            configured_is_explicit=(
                getattr(
                    configured_info,
                    "max_input_length_configured",
                    False,
                )
                if configured_info is not None
                else False
            ),
            use_catalog=self._context_catalog_enabled(),
            auto_detected=auto_detected,
        )

    def _get_context_size(self, model_id: str) -> int:
        """Alias of :meth:`get_context_size` kept for provider internals."""
        return self.get_context_size(model_id)

    @abstractmethod
    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        """Return an instance of the chat model associated with this
        provider and model_id."""

    async def probe_model_multimodal(
        self,
        model_id: str,  # pylint: disable=unused-argument
        timeout: float = 10,  # pylint: disable=unused-argument
        image_only: bool = False,  # pylint: disable=unused-argument
    ) -> ProbeResult:
        """Probe if a model supports multimodal input.

        Args:
            model_id: Model identifier.
            timeout: Per-probe timeout in seconds.
            image_only: When True, skip the video probe and return after
                the image probe only.  Use this for fast checks (e.g.
                from ``view_image``) to avoid blocking on the slower
                video probe.

        Default implementation returns ProbeResult() (all False).
        Subclasses with API access should override.
        """
        from .multimodal_prober import ProbeResult

        return ProbeResult()

    async def get_info(self, mock_secret: bool = True) -> ProviderInfo:
        """Return a ProviderInfo instance with the provider's details."""
        if mock_secret and self.api_key:
            # Determine which prefix to show in the masked key.
            # If api_key_prefixes is set, pick the one matching the
            # actual key; otherwise fall back to api_key_prefix.
            prefix_for_mask = self.api_key_prefix
            if self.api_key_prefixes:
                prefix_for_mask = next(
                    (
                        p
                        for p in self.api_key_prefixes
                        if self.api_key.startswith(p)
                    ),
                    self.api_key_prefix,
                )
            api_key = prefix_for_mask + "*" * 6
        else:
            api_key = self.api_key
        removed = set(self.removed_model_ids)

        def serialize_model(model: ModelInfo) -> dict[str, Any]:
            payload = model.model_dump()
            payload["supports_agent_thinking"] = self.supports_agent_thinking(
                model.id,
            )
            return payload

        # Serialize models/extra_models to plain dicts so that
        # ProviderInfo constructs fresh ModelInfo instances using
        # the class in its own module scope.  This avoids pydantic
        # class-identity mismatches when the same module is loaded
        # via two different import paths (e.g. PYTHONPATH + pip install).
        meta = self.meta or {}
        return ProviderInfo(
            id=self.id,
            name=self.name,
            base_url=self.base_url,
            api_key=api_key,
            chat_model=self.chat_model,
            # Discovery is a separate catalog used by the add-model form.
            # Do not expose it as configured models to selectors or lists.
            models=[
                serialize_model(model)
                for model in self.models
                if model.id not in removed
            ],
            extra_models=[
                serialize_model(model)
                for model in self.extra_models
                if model.id not in removed
            ],
            discovered_models=[
                serialize_model(model)
                for model in self.discovered_models
                if model.id not in removed
            ],
            models_last_synced_at=self.models_last_synced_at,
            models_last_sync_error=self.models_last_sync_error,
            models_syncing=self.models_syncing,
            hidden_model_ids=list(self.hidden_model_ids),
            removed_model_ids=list(self.removed_model_ids),
            discovery_strategy=self.discovery_strategy,
            discovery_support_reason=self.discovery_support_reason,
            discovery_requires_auth=self.discovery_requires_auth,
            model_sync_mode=self.model_sync_mode,
            api_key_prefix=self.api_key_prefix,
            api_key_prefixes=self.api_key_prefixes,
            is_local=self.is_local,
            is_custom=self.is_custom,
            support_model_discovery=self.support_model_discovery,
            merge_with_catalog=self.merge_with_catalog,
            support_connection_check=self.support_connection_check
            and not self.is_custom,
            freeze_url=self.freeze_url,
            require_api_key=self.require_api_key,
            generate_kwargs=self.generate_kwargs,
            custom_headers=self.custom_headers,
            auth_mode=self.auth_mode,
            supports_oauth=meta.get("supports_oauth", False),
            oauth_connected=bool(
                meta.get("supports_oauth") and self.api_key,
            ),
            is_free_tier=meta.get("is_free_tier", False),
            provider_group=self.provider_group,
            provider_group_name=self.provider_group_name,
            provider_variant=self.provider_variant,
            thinking_param_style=self.thinking_param_style,
            reasoning_effort_options=self.reasoning_effort_options,
            thinking_budget_range=self.thinking_budget_range,
            meta=meta,
        )
