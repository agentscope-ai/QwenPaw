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

    def thinking_control(self, model_id: str):
        """Hub cards describe the upstream, independent of our chat bridge."""
        info = self.get_model_info(model_id)
        if info and info.thinking_control:
            return info.thinking_control.model_copy(deep=True)
        return super().thinking_control(model_id)

    def supports_agent_thinking(self, model_id: str) -> bool:
        """Use the Hub's capability instead of guessing from opaque aliases."""
        info = self.get_model_info(model_id)
        return bool(info and info.supports_agent_thinking)

    def get_agent_thinking_kwargs(
        self,
        model_id: str,
        level: str,
        budget: int | None = None,
    ) -> dict:
        """Forward neutral intent for translation by the trusted Hub."""
        return {
            f"extra_body": {
                f"hub_thinking_level": level,
                f"hub_thinking_budget": budget,
            },
        }

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

    def automatically_listed(self, model: ModelInfo) -> bool:
        """Organization grants are candidates until selected locally."""
        return model.source == f"user"

    async def get_info(self, mock_secret=True, *, include_candidates=True):
        """Expose safe catalog metadata without the runtime credential."""
        return ProviderInfo(
            model_count=len({m.id for m in self.discovery_candidates()}),
            id=PROVIDER_ID,
            name=f"Hub",
            models=self.configured_models(),
            discovered_models=(
                self.discovery_candidates() if include_candidates else []
            ),
            seen_model_ids=self.seen_model_ids,
            hidden_model_ids=self.hidden_model_ids,
            api_key=f"",
            base_url=f"",
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
                max_output_length_source=(
                    "adapter"
                    if m["output_token_limit"] is not None
                    else "unknown"
                ),
                supports_agent_thinking=m["supports_agent_thinking"],
                thinking_control=m.get(f"thinking_control"),
            )
            for m in catalog["models"]
        ],
    )


def managed_slot(selected=None, *, explicit=False, catalog=None):
    """Resolve and validate a selection within the organization catalog."""
    if selected is None:
        if explicit:
            raise ProviderError(message=f"No organization model selected")
        return None, catalog
    if selected.provider_id != PROVIDER_ID:
        raise ProviderError(message=f"Not an organization model selection")
    catalog = catalog if catalog is not None else directory()
    model_id = selected.model
    if model_id not in {m["id"] for m in catalog["models"]}:
        raise ProviderError(
            message="Organization model is no longer available",
        )
    return ModelSlotConfig(provider_id=PROVIDER_ID, model=model_id), catalog
