# -*- coding: utf-8 -*-
"""Strict inputs for organization model administration."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ...providers.context_windows import DEFAULT_CONTEXT_WINDOW
from .provider_setup import supported_presets


class StrictBody(BaseModel):
    """Reject unknown fields instead of forwarding connection overrides."""

    model_config = ConfigDict(extra="forbid")


class PolicyBody(StrictBody):
    """Revision-checked organization defaults."""

    revision: int = Field(ge=1)
    default_model_id: str | None = None
    member_token_limit: int | None = Field(default=None, ge=0)
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        """Validate a portable IANA timezone name."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone") from exc
        return value


class ConnectionBody(StrictBody):
    """Server-owned provider connection with isolated credentials."""

    revision: int | None = Field(default=None, ge=1)
    protocol: Literal["chat", "responses", "anthropic"] = f"chat"
    name: str = Field(min_length=1, max_length=120)
    provider_id: str | None = None
    base_url: str = Field(max_length=2048)
    api_key: str | None = Field(default=None, min_length=1, max_length=8192)
    enabled: bool = True
    quota_scope: str = Field(min_length=1, max_length=120)
    requests_per_minute: int = Field(default=0, ge=0, le=100000)
    concurrency: int = Field(default=0, ge=0, le=1000)

    @model_validator(mode=f"after")
    def preset_protocol(self):
        """A built-in provider owns its protocol; custom connections choose."""
        if self.provider_id:
            self.protocol = supported_presets()[self.provider_id].wire_protocol
        return self

    @field_validator("provider_id")
    @classmethod
    def valid_provider(cls, value: str | None) -> str | None:
        """Only accept presets supported by the gateway protocol."""
        if value is not None and value not in supported_presets():
            raise ValueError(f"Unsupported Hub provider: {value}")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        """Allow administrator-selected HTTP endpoints without URL secrets."""
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or any(
                (
                    parsed.username,
                    parsed.password,
                    parsed.query,
                    parsed.fragment,
                ),
            )
        ):
            raise ValueError("Expected an HTTP base URL without credentials")
        return value.rstrip("/")


class ModelBody(StrictBody):
    """Published model alias and verified budget bounds."""

    revision: int | None = Field(default=None, ge=1)
    connection_id: str
    upstream_model: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    all_members: bool = True
    user_ids: list[str] = Field(default_factory=list, max_length=10000)
    input_token_limit: int = Field(
        default=DEFAULT_CONTEXT_WINDOW,
        ge=1000,
        le=10000000,
    )
    output_token_limit: int | None = Field(
        default=None,
        ge=1,
        le=1000000,
    )
    output_limit_field: Literal[
        "max_tokens",
        "max_completion_tokens",
    ] = "max_tokens"
    budget_verified: bool = False
    supports_image: bool | None = None
    supports_audio: bool | None = None
    supports_video: bool | None = None
    supports_tool_calling: bool | None = None
    template_id: str | None = None
    cache_settings: dict = Field(default_factory=dict)

    @field_validator(f"cache_settings")
    @classmethod
    def validate_cache_settings(cls, value: dict) -> dict:
        """Cache policy cannot override routing, credentials or budgets."""
        if set(value) - {
            f"prompt_cache_key",
            f"prompt_cache_options",
            f"prompt_cache_retention",
            f"enable_prompt_cache_breakpoint",
            f"cache_control",
        }:
            raise ValueError(f"Unsupported cache setting")
        return value

    requests_per_minute: int = Field(default=0, ge=0, le=100000)
    concurrency: int = Field(default=0, ge=0, le=1000)


class InviteBatchBody(StrictBody):
    """Finite, idempotently created invitation batch."""

    request_id: str = Field(min_length=8, max_length=128)
    count: int = Field(default=1, ge=1, le=100)
    valid_days: int = Field(default=7, ge=1, le=90)
    note: str = Field(default="", max_length=256)
    model_ids: list[str] = Field(default_factory=list, max_length=100)
    inherit_budget: bool = True
    token_limit: int | None = Field(default=None, ge=0)


class BudgetBody(StrictBody):
    """Explicit limit or inherited member default."""

    token_limit: int | None = Field(default=None, ge=0)
    inherit: bool = False


class ModelPreferenceBody(StrictBody):
    """Select only a managed alias, never an upstream connection."""

    model_id: str | None = None
