# -*- coding: utf-8 -*-
"""Runtime-side model directory with no organization credentials."""

from __future__ import annotations

import os

import httpx

from ..config.config import ModelSlotConfig
from ..exceptions import ProviderError
from .openai_provider import OpenAIProvider
from .provider import ModelInfo, ProviderInfo

PROVIDER_ID = "hub-managed"


def managed_mode() -> bool:
    """Detect a control-plane-provisioned model capability."""
    return bool(os.environ.get("QWENPAW_HUB_MODEL_TOKEN"))


def directory() -> dict:
    """Refresh grants from Hub; never fall back to personal credentials."""
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
        if not result["enabled"]:
            raise ValueError("Organization models are unavailable")
        return result
    except Exception as exc:
        raise ProviderError(
            message="Organization model directory unavailable; contact admin",
        ) from exc


class ManagedProvider(OpenAIProvider):
    """Use the existing OpenAI adapter while exporting only safe metadata."""

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
            name="Organization models",
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
        name="Organization models",
        base_url=f"{endpoint}/api/hub/model-runtime/v1",
        api_key=os.environ["QWENPAW_HUB_MODEL_TOKEN"],
        models=[
            ModelInfo(
                id=m["id"],
                name=m["name"],
                supports_image=m["supports_image"],
                supports_multimodal=m["supports_image"],
                max_input_length=m["input_token_limit"],
                max_input_length_configured=True,
            )
            for m in catalog["models"]
        ],
    )


def managed_slot(selected=None, *, explicit=False):
    """Resolve defaults while rejecting explicit personal model overrides."""
    catalog = directory()
    if selected and selected.provider_id != PROVIDER_ID:
        if explicit:
            raise ProviderError(
                message="Only organization models are allowed",
            )
        selected = None
    model_id = selected.model if selected else catalog["default_model_id"]
    if model_id not in {m["id"] for m in catalog["models"]}:
        raise ProviderError(
            message="Organization model is no longer available",
        )
    return ModelSlotConfig(provider_id=PROVIDER_ID, model=model_id), catalog
