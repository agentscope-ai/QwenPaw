# -*- coding: utf-8 -*-
"""Configuration owned by the OpenViking memory plugin."""

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OpenVikingAutoMemorySearchConfig(BaseModel):
    """Controls automatic recall before a model call."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    max_results: int = Field(default=3, ge=1, le=20)


class OpenVikingMemoryConfig(BaseModel):
    """REST connection and recall settings for OpenViking."""

    model_config = ConfigDict(extra="ignore")

    base_url: str = "http://127.0.0.1:1933"
    api_key: str = ""
    request_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=300.0,
        allow_inf_nan=False,
    )
    retrieval_token_budget: int = Field(default=2048, ge=64, le=32000)
    auto_memory_search_config: OpenVikingAutoMemorySearchConfig = Field(
        default_factory=OpenVikingAutoMemorySearchConfig,
    )
    commit_policy: Literal["auto", "every_turn"] = "auto"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OpenViking base_url must be an http(s) URL")
        return normalized.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        return value.strip()
