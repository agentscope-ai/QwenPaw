# -*- coding: utf-8 -*-
"""Pydantic data models for providers and models."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")
    input_capabilities: List[str] = Field(
        default_factory=list,
        description="Optional supported input modalities (e.g. text, image)",
    )


class ProviderDefinition(BaseModel):
    """Static definition of a provider (built-in or custom)."""

    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Human-readable provider name")
    default_base_url: str = Field(
        default="",
        description="Default API base URL",
    )
    api_key_prefix: str = Field(
        default="",
        description="Expected prefix for the API key",
    )
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="Built-in LLM model list",
    )
    is_custom: bool = Field(default=False)
    is_local: bool = Field(default=False)
    chat_model: str = Field(
        default="OpenAIChatModel",
        description="Chat model class name (e.g., 'OpenAIChatModel')",
    )


class ProviderSettings(BaseModel):
    """Per-provider settings stored in providers.json (built-in only)."""

    base_url: str = Field(default="")
    api_key: str = Field(default="")
    extra_models: List[ModelInfo] = Field(default_factory=list)
    chat_model: str = Field(
        default="",
        description="Chat model class name (e.g., 'OpenAIChatModel'). "
        "If empty, uses ProviderDefinition default.",
    )


class CustomProviderData(BaseModel):
    """Persisted definition + runtime config of a user-created custom provider.

    All configuration lives here; custom providers do NOT have a
    corresponding entry in the ``providers`` dict.
    """

    id: str = Field(..., description="Provider identifier (unique)")
    name: str = Field(..., description="Human-readable provider name")
    default_base_url: str = Field(default="")
    api_key_prefix: str = Field(default="")
    models: List[ModelInfo] = Field(default_factory=list)
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    chat_model: str = Field(
        default="OpenAIChatModel",
        description="Chat model class name (e.g., 'OpenAIChatModel')",
    )


class ModelSlotConfig(BaseModel):
    provider_id: str = Field(default="")
    model: str = Field(default="")


class VisionImageSettings(BaseModel):
    enabled: bool = Field(
        default=True,
        description="Whether image prepass is enabled when routing conditions match.",
    )
    attachments_mode: str = Field(
        default="first",
        description="Image selection mode: 'first' or 'all'.",
    )
    max_images: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Maximum image blocks passed to VLM prepass in 'all' mode.",
    )
    prompt_override: str = Field(
        default="",
        description="Optional custom prompt override for image prepass.",
    )
    timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Timeout in seconds for each VLM prepass attempt.",
    )
    max_output_chars: int = Field(
        default=500,
        ge=100,
        le=20000,
        description="Maximum normalized prepass output size kept for LLM context.",
    )


class VisionAudioSettings(BaseModel):
    enabled: bool = Field(
        default=False,
        description="Whether audio prepass is enabled when routing conditions match.",
    )
    attachments_mode: str = Field(
        default="first",
        description="Audio selection mode: 'first' or 'all'.",
    )
    max_items: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Maximum audio blocks passed to prepass in 'all' mode.",
    )
    prompt_override: str = Field(
        default="",
        description="Optional custom prompt override for audio prepass.",
    )
    timeout_seconds: int = Field(
        default=90,
        ge=5,
        le=600,
        description="Timeout in seconds for each audio prepass attempt.",
    )
    max_output_chars: int = Field(
        default=6000,
        ge=200,
        le=30000,
        description="Maximum normalized audio prepass output kept for LLM context.",
    )


class VisionVideoSettings(BaseModel):
    enabled: bool = Field(
        default=False,
        description="Whether video prepass is enabled when routing conditions match.",
    )
    attachments_mode: str = Field(
        default="first",
        description="Video selection mode: 'first' or 'all'.",
    )
    max_items: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Maximum video blocks passed to prepass in 'all' mode.",
    )
    prompt_override: str = Field(
        default="",
        description="Optional custom prompt override for video prepass.",
    )
    timeout_seconds: int = Field(
        default=120,
        ge=5,
        le=600,
        description="Timeout in seconds for each video prepass attempt.",
    )
    max_output_chars: int = Field(
        default=6000,
        ge=200,
        le=30000,
        description="Maximum normalized video prepass output kept for LLM context.",
    )


class VisionSettings(BaseModel):
    image: VisionImageSettings = Field(default_factory=VisionImageSettings)
    audio: VisionAudioSettings = Field(default_factory=VisionAudioSettings)
    video: VisionVideoSettings = Field(default_factory=VisionVideoSettings)


class ProvidersData(BaseModel):
    """Top-level structure of providers.json."""

    providers: Dict[str, ProviderSettings] = Field(default_factory=dict)
    custom_providers: Dict[str, CustomProviderData] = Field(
        default_factory=dict,
    )
    active_llm: ModelSlotConfig = Field(default_factory=ModelSlotConfig)
    active_vlm: ModelSlotConfig = Field(default_factory=ModelSlotConfig)
    active_vlm_fallbacks: List[ModelSlotConfig] = Field(default_factory=list)
    vision: VisionSettings = Field(default_factory=VisionSettings)

    def get_credentials(self, provider_id: str) -> tuple[str, str]:
        """Return ``(base_url, api_key)`` for *provider_id*."""
        cpd = self.custom_providers.get(provider_id)
        if cpd is not None:
            return cpd.base_url or cpd.default_base_url, cpd.api_key
        s = self.providers.get(provider_id)
        return (s.base_url, s.api_key) if s else ("", "")

    def is_configured(self, defn: "ProviderDefinition") -> bool:
        """Custom providers need base_url; built-in providers need api_key.

        Local providers are always considered configured (no credentials).

        The special built-in provider ``ollama`` is also considered configured
        without an API key, since it typically runs on localhost and uses an
        unauthenticated OpenAI-compatible endpoint.
        """
        if defn.is_local or defn.id == "ollama":
            return True
        cpd = self.custom_providers.get(defn.id)
        if cpd is not None:
            return bool(cpd.base_url or cpd.default_base_url)
        s = self.providers.get(defn.id)
        if not s:
            return False
        return bool(s.base_url) if defn.is_custom else bool(s.api_key)


class ProviderInfo(BaseModel):
    """Provider info returned by API."""

    id: str
    name: str
    api_key_prefix: str
    models: List[ModelInfo] = Field(default_factory=list)
    extra_models: List[ModelInfo] = Field(default_factory=list)
    is_custom: bool = Field(default=False)
    is_local: bool = Field(default=False)
    has_api_key: bool = Field(default=False)
    current_api_key: str = Field(default="")
    current_base_url: str = Field(default="")


class ActiveModelsInfo(BaseModel):
    active_llm: ModelSlotConfig
    active_vlm: ModelSlotConfig = Field(default_factory=ModelSlotConfig)
    active_vlm_fallbacks: List[ModelSlotConfig] = Field(default_factory=list)
    vision: VisionSettings = Field(default_factory=VisionSettings)


class ResolvedModelConfig(BaseModel):
    provider_id: str = Field(default="")
    model: str = Field(default="")
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    is_local: bool = Field(default=False)
