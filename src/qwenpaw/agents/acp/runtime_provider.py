# -*- coding: utf-8 -*-
"""Ephemeral model providers for headless ACP runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

from ...config.config import ModelSlotConfig
from ...providers.openai_provider import OpenAIProvider
from ...providers.provider import ModelInfo

RUNTIME_OPENAI_PROVIDER_ID = "runtime-openai"


@dataclass(frozen=True)
class OpenAIRuntimeProviderConfig:
    """One process-scoped OpenAI-compatible model connection."""

    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "OpenAIRuntimeProviderConfig":
        """Load and validate the runtime provider environment."""
        source = os.environ if environ is None else environ
        names = (
            "OPENAI_BASE_URL",
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
        )
        values = {name: str(source.get(name, "")).strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(
                f"Missing runtime provider environment: {missing_text}",
            )

        base_url = values["OPENAI_BASE_URL"].rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "OPENAI_BASE_URL must be an absolute HTTP(S) URL",
            )

        return cls(
            base_url=base_url,
            api_key=values["OPENAI_API_KEY"],
            model=values["OPENAI_MODEL"],
        )

    @property
    def model_slot(self) -> ModelSlotConfig:
        """Return the per-request model selection."""
        return ModelSlotConfig(
            provider_id=RUNTIME_OPENAI_PROVIDER_ID,
            model=self.model,
        )

    def build_provider(self) -> OpenAIProvider:
        """Create the in-memory provider without writing credentials."""
        return OpenAIProvider(
            id=RUNTIME_OPENAI_PROVIDER_ID,
            name="ACP Runtime OpenAI",
            base_url=self.base_url,
            api_key=self.api_key,
            models=[
                ModelInfo(
                    id=self.model,
                    name=self.model,
                ),
            ],
            require_api_key=True,
            support_connection_check=False,
            support_model_discovery=False,
            is_custom=True,
        )
