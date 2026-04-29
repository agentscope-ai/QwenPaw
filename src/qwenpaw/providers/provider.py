# -*- coding: utf-8 -*-
"""Definition of Provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Type
from pydantic import BaseModel, Field
from pydantic import ConfigDict

from agentscope.model import ChatModelBase
from qwenpaw.exceptions import ProviderError

if TYPE_CHECKING:
    from .multimodal_prober import ProbeResult


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
    generate_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-model generation parameters that override "
        "provider-level generate_kwargs.",
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
        description="List of user-added models (not fetched from provider)",
    )

    api_key_prefix: str = Field(
        default="",
        description="Expected prefix for the API key (e.g., 'sk-')",
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
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the provider "
        "(e.g., api_key_url, api_key_hint).",
    )
    auth_type: str = Field(
        default="api_key",
        description=(
            "Authentication method: 'api_key' (default) or "
            "'oauth_device_code' for providers that authenticate via "
            "an interactive OAuth device-code flow."
        ),
    )
    is_authenticated: bool = Field(
        default=False,
        description=(
            "Whether the provider currently has valid authentication. "
            "Computed at info-emit time; not persisted."
        ),
    )
    oauth_user_login: str = Field(
        default="",
        description=(
            "Display name (e.g., GitHub login) of the authenticated user, "
            "for OAuth-based providers. Empty when not authenticated."
        ),
    )


class Provider(ProviderInfo, ABC):
    """Represents a provider instance with its configuration."""

    oauth_access_token: str = Field(
        default="",
        description=(
            "Long-lived OAuth access token for providers that use the "
            "device-code flow (e.g., GitHub Copilot). Encrypted on disk via "
            "PROVIDER_SECRET_FIELDS. Empty string when not authenticated."
        ),
    )

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
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable."""

    async def add_model(
        self,
        model_info: ModelInfo,
        target: str = "extra_models",
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Add a model to the provider's model list."""
        model_info.id = model_info.id.strip()
        if any(
            model.id.strip() == model_info.id
            for model in self.models + self.extra_models
        ):
            return False, f"Model '{model_info.id}' already exists"
        if target == "extra_models":
            self.extra_models.append(model_info)
        elif target == "models":
            self.models.append(model_info)
        else:
            return False, f"Invalid target '{target}' for adding model"
        return True, ""

    async def delete_model(
        self,
        model_id: str,
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Delete a model from the provider's model list.

        Removes the model from ``extra_models``. For custom providers it
        is also removed from ``models`` so that user-managed entries can
        be deleted from the UI.
        """
        model_id = model_id.strip()
        self.extra_models = [
            model
            for model in self.extra_models
            if model.id.strip() != model_id
        ]
        if self.is_custom:
            self.models = [
                model for model in self.models if model.id.strip() != model_id
            ]
        return True, ""

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
            "generate_kwargs" in config
            and config["generate_kwargs"] is not None
            and isinstance(config["generate_kwargs"], dict)
        ):
            self.generate_kwargs = config["generate_kwargs"]
        if "extra_models" in config and config["extra_models"] is not None:
            # Always go through model_validate with dict data to
            # avoid class-identity issues from dual module loading.
            builtin_ids = {m.id.strip() for m in self.models}
            self.extra_models = [
                ModelInfo.model_validate(
                    model.model_dump()
                    if isinstance(model, BaseModel)
                    else model,
                )
                for model in config["extra_models"]
            ]
            # Drop any extras that duplicate a built-in entry.
            self.extra_models = [
                m for m in self.extra_models if m.id.strip() not in builtin_ids
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
        for model in self.models + self.extra_models:
            if model.id == model_id:
                if model.generate_kwargs:
                    return self._deep_merge(
                        self.generate_kwargs,
                        model.generate_kwargs,
                    )
                break
        return dict(self.generate_kwargs)

    def update_model_config(
        self,
        model_id: str,
        config: Dict,
    ) -> bool:
        """Update per-model configuration (e.g. generate_kwargs)."""
        for model in self.models + self.extra_models:
            if model.id == model_id:
                if (
                    "generate_kwargs" in config
                    and config["generate_kwargs"] is not None
                    and isinstance(config["generate_kwargs"], dict)
                ):
                    model.generate_kwargs = config["generate_kwargs"]
                return True
        return False

    def has_model(self, model_id: str) -> bool:
        """Check if the provider has a model with the given ID."""
        return any(
            model.id == model_id for model in self.models + self.extra_models
        )

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
        api_key = (
            self.api_key_prefix + "*" * 6
            if mock_secret and self.api_key
            else self.api_key
        )
        # Drop any extras that duplicate a built-in entry so the UI
        # never sees the same model twice (defensive against legacy
        # configs persisted before dedup was enforced at write time).
        builtin_ids = {m.id.strip() for m in self.models}
        seen_extra_ids: set[str] = set()
        deduped_extras = []
        for m in self.extra_models:
            mid = m.id.strip()
            if mid in builtin_ids or mid in seen_extra_ids:
                continue
            seen_extra_ids.add(mid)
            deduped_extras.append(m)
        # Serialize models/extra_models to plain dicts so that
        # ProviderInfo constructs fresh ModelInfo instances using
        # the class in its own module scope.  This avoids pydantic
        # class-identity mismatches when the same module is loaded
        # via two different import paths (e.g. PYTHONPATH + pip install).
        return ProviderInfo(
            id=self.id,
            name=self.name,
            base_url=self.base_url,
            api_key=api_key,
            chat_model=self.chat_model,
            models=[m.model_dump() for m in self.models],
            extra_models=[m.model_dump() for m in deduped_extras],
            api_key_prefix=self.api_key_prefix,
            is_local=self.is_local,
            is_custom=self.is_custom,
            support_model_discovery=self.support_model_discovery,
            # custom providers are assumed to not support connection check
            support_connection_check=self.support_connection_check
            and not self.is_custom,
            freeze_url=self.freeze_url,
            require_api_key=self.require_api_key,
            generate_kwargs=self.generate_kwargs,
            meta=dict(self.meta),
            auth_type=self.auth_type,
            is_authenticated=await self._compute_is_authenticated(),
            oauth_user_login=self.oauth_user_login,
        )

    async def _compute_is_authenticated(self) -> bool:
        """Whether the provider currently has valid credentials.

        Default implementation returns True if the provider has an
        ``api_key`` (or doesn't require one).  OAuth-based providers
        should override this to inspect their token state.
        """
        if not self.require_api_key:
            return True
        return bool(self.api_key)
