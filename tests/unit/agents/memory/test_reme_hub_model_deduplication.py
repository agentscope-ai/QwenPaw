# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Memory slot deduplication uses the Hub factory's actual wrapper."""

from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.agents.memory import reme_light_memory_manager as memory_module
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers import hub_managed
from qwenpaw.providers.fallback_chat_model import (
    FallbackChatModel,
    get_model_identity,
)
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


@pytest.mark.parametrize("model_id", ["same-model", "same-model:v1"])
@pytest.mark.parametrize("require_images", [False, True])
async def test_real_hub_wrapper_deduplicates_memory_slot(
    monkeypatch,
    make_memory_model_manager,
    model_id,
    require_images,
):
    """Construct real models; stub only catalog responses and the LLM call."""
    monkeypatch.setenv("QWENPAW_HUB_MODEL_TOKEN", "test-token")
    monkeypatch.setenv("QWENPAW_HUB_MODEL_URL", "http://hub.test")
    directory = Mock(
        return_value={
            "models": [
                {
                    "id": model_id,
                    "name": "Test Hub Model",
                    "supports_image": True,
                    "input_token_limit": 32768,
                    "output_token_limit": 4096,
                    "supports_agent_thinking": False,
                },
            ],
        },
    )
    monkeypatch.setattr(hub_managed, "directory", directory)
    slot = ModelSlotConfig(provider_id="hub-managed", model=model_id)
    profile = AgentProfileConfig(
        id="hub-memory",
        name="Hub Memory",
        active_model=slot,
    )
    profile.running.reme_light_memory_config.memory_model = slot
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        AsyncMock(return_value=profile),
    )
    manager = make_memory_model_manager(profile.id)

    actual = await manager._update_qwenpaw_model(
        require_image_support=require_images,
    )

    assert isinstance(actual, TokenRecordingModelWrapper)
    assert not isinstance(actual, FallbackChatModel)
    assert not hasattr(actual, "model_key")
    assert get_model_identity(actual) == ("hub-managed", model_id)
    assert actual.formatter.resize_images_to_max_bytes is True
    directory.assert_called_once_with()
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=actual,
    )

    fail_call = AsyncMock(
        side_effect=RuntimeError("Simulated pre-output failure"),
    )
    monkeypatch.setattr(type(actual._model), "__call__", fail_call)
    with pytest.raises(RuntimeError, match="Simulated pre-output failure"):
        await actual([])
    fail_call.assert_awaited_once()
