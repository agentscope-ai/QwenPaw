# -*- coding: utf-8 -*-
"""Pydantic data models for providers and models."""

from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")


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
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers to attach to model requests.",
    )
    wire_api: Literal["chat_completions", "responses"] = Field(
        default="chat_completions",
        description="Wire API style for OpenAI-compatible providers.",
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
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers to attach to model requests.",
    )
    wire_api: Literal["chat_completions", "responses"] = Field(
        default="chat_completions",
        description="Wire API style for OpenAI-compatible providers.",
    )


class ModelSlotConfig(BaseModel):
    provider_id: str = Field(default="")
    model: str = Field(default="")


class ProvidersData(BaseModel):
    """Top-level structure of providers.json."""

    providers: Dict[str, ProviderSettings] = Field(default_factory=dict)
    custom_providers: Dict[str, CustomProviderData] = Field(
        default_factory=dict,
    )
    active_llm: ModelSlotConfig = Field(default_factory=ModelSlotConfig)

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
    current_headers: Dict[str, str] = Field(default_factory=dict)
    wire_api: str = Field(default="chat_completions")


class ActiveModelsInfo(BaseModel):
    active_llm: ModelSlotConfig


class ResolvedModelConfig(BaseModel):
    model: str = Field(default="")
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    headers: Dict[str, str] = Field(default_factory=dict)
    wire_api: str = Field(default="chat_completions")
    is_local: bool = Field(default=False)
