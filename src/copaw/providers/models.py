# -*- coding: utf-8 -*-
"""Pydantic data models for providers and models."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


# Re-export ModelInfo from the canonical definition in provider.py to avoid
# duplicate class definitions.  All runtime code should use this single class.
from copaw.providers.provider import ModelInfo  # noqa: F401


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


class ActiveModelsInfo(BaseModel):
    active_llm: ModelSlotConfig | None
