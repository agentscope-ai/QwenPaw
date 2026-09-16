# -*- coding: utf-8 -*-
"""Strict inputs for organization model administration."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    """Server-owned Chat Completions connection."""

    revision: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=120)
    provider_id: str | None = None
    base_url: str = Field(max_length=2048)
    api_key: str | None = Field(default=None, min_length=1, max_length=8192)
    enabled: bool = True
    quota_scope: str = Field(min_length=1, max_length=120)
    requests_per_minute: int = Field(default=60, ge=1, le=100000)
    concurrency: int = Field(default=4, ge=1, le=1000)

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
    input_token_limit: int = Field(ge=1000, le=10000000)
    output_token_limit: int = Field(default=4096, ge=1, le=1000000)
    output_limit_field: Literal[
        "max_tokens",
        "max_completion_tokens",
    ] = "max_tokens"
    budget_verified: bool = False
    supports_image: bool = False
    requests_per_minute: int = Field(default=60, ge=1, le=100000)
    concurrency: int = Field(default=4, ge=1, le=1000)


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
