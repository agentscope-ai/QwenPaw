# -*- coding: utf-8 -*-
"""Runtime-side model directory with no organization credentials."""

from __future__ import annotations

import os
from typing import ClassVar

import httpx

from ..config.config import ModelSlotConfig
from ..exceptions import ProviderError
from .openai_provider import OpenAIProvider
from .provider import ModelInfo, ProviderInfo

PROVIDER_ID = "hub-managed"


def hub_mode() -> bool:
    """Detect the model capability provisioned for every Hub runtime."""
    return bool(os.environ.get("QWENPAW_HUB_MODEL_TOKEN"))


def directory() -> dict:
    """Refresh organization grants without exposing upstream credentials."""
    endpoint = os.environ.get("QWENPAW_HUB_MODEL_URL", "")
    token = os.environ.get("QWENPAW_HUB_MODEL_TOKEN", "")
    try:
        with httpx.Client(timeout=10, trust_env=False) as client:
            response = client.get(
                f"{endpoint}/api/hub/model-runtime/catalog",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            result = response.json()
        return result
    except Exception as exc:
        raise ProviderError(
            message="Organization model directory unavailable; contact admin",
        ) from exc


class ManagedProvider(OpenAIProvider):
    """Use the existing OpenAI adapter while exporting only safe metadata."""

    session_header_name: ClassVar[str] = f"x-qwenpaw-session"

    def supports_agent_thinking(self, model_id: str) -> bool:
        """Use the Hub's capability instead of guessing from opaque aliases."""
        info = self.get_model_info(model_id)
        return bool(info and info.supports_agent_thinking)

    def _map_agent_thinking_level(
        self,
        effective: dict,
        model_id: str,
        level: str,
        budget: int,
    ) -> None:
        """Let the Hub translate the level using trusted upstream metadata."""
        effective.setdefault("extra_body", {})["hub_thinking_level"] = level

    def get_chat_model_instance(self, model_id):
        """Disable SDK retries so each admission is one upstream attempt."""
        if not self.has_model(model_id):
            raise ProviderError(message="Organization model unavailable")
        model = super().get_chat_model_instance(model_id)
        model.max_retries = 0
        model.client.max_retries = 0
        return model

    async def get_info(self, mock_secret=True) -> ProviderInfo:
        """Never expose even the runtime capability through model APIs."""
        return ProviderInfo(
            id=PROVIDER_ID,
            name="Hub",
            models=self.models,
            api_key="",
            base_url="",
            require_api_key=False,
        )


def managed_provider(catalog=None) -> ManagedProvider:
    """Construct an in-memory provider from safe model metadata."""
    catalog = catalog or directory()
    endpoint = os.environ["QWENPAW_HUB_MODEL_URL"]
    return ManagedProvider(
        id=PROVIDER_ID,
        name="Hub",
        base_url=f"{endpoint}/api/hub/model-runtime/v1",
        api_key=os.environ["QWENPAW_HUB_MODEL_TOKEN"],
        models=[
            ModelInfo(
                id=m["id"],
                name=m["name"],
                supports_image=m["supports_image"],
                supports_multimodal=m["supports_image"],
                supports_audio=m.get(f"supports_audio"),
                supports_video=m.get(f"supports_video"),
                supports_tool_calling=m.get(f"supports_tool_calling"),
                max_input_length=m["input_token_limit"],
                max_input_length_configured=True,
                max_output_length=m["output_token_limit"],
                max_output_length_source="adapter",
                supports_agent_thinking=m["supports_agent_thinking"],
            )
            for m in catalog["models"]
        ],
    )


def managed_slot(selected=None, *, explicit=False, catalog=None):
    """Resolve and validate a selection within the organization catalog."""
    catalog = catalog if catalog is not None else directory()
    if selected and selected.provider_id != PROVIDER_ID:
        if explicit:
            raise ProviderError(
                message="Only organization models are allowed",
            )
        selected = None
    if not catalog["models"] and not explicit:
        return None, catalog
    model_id = selected.model if selected else catalog["default_model_id"]
    if model_id not in {m["id"] for m in catalog["models"]}:
        raise ProviderError(
            message="Organization model is no longer available",
        )
    return ModelSlotConfig(provider_id=PROVIDER_ID, model=model_id), catalog
