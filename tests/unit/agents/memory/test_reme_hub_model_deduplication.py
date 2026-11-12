# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Real Hub routing covers deduplication and saved-provider inheritance."""

from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.agents.memory import reme_light_memory_manager as memory_module
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers import hub_managed
from qwenpaw.providers.fallback_chat_model import get_model_identity
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


@pytest.mark.parametrize("model_id", ["memory", "memory:v1"])
@pytest.mark.parametrize("main_state", ["same", "stale"])
@pytest.mark.parametrize("scope", ["agent", "global"])
@pytest.mark.parametrize("memory_form", ["bare", "inherited", "explicit"])
@pytest.mark.parametrize(
    "operation",
    ["update", "update-image", "start", "image"],
)
async def test_real_hub_memory_routing(
    monkeypatch,
    tmp_path,
    make_memory_model_manager,
    model_id,
    main_state,
    scope,
    memory_form,
    operation,
):
    """Stub only catalog, configuration reads, SDK calls and ReMe injection."""
    monkeypatch.setenv("QWENPAW_HUB_MODEL_TOKEN", "test-token")
    monkeypatch.setenv("QWENPAW_HUB_MODEL_URL", "http://hub.test")
    directory = Mock(
        return_value={
            "models": [
                {
                    "id": model_id,
                    "name": "Memory",
                    "supports_image": True,
                    "input_token_limit": 32768,
                    "output_token_limit": 4096,
                    "supports_agent_thinking": False,
                },
            ],
        },
    )
    monkeypatch.setattr(hub_managed, "directory", directory)
    primary = ModelSlotConfig(
        provider_id="hub-managed",
        model=model_id if main_state == "same" else "removed-main",
    )
    providers = ProviderManager.__new__(ProviderManager)
    providers.default_models = {"chat": primary}
    providers.root_path = tmp_path
    monkeypatch.setattr(ProviderManager, "_instance", providers)
    memory_setting = (
        model_id
        if memory_form == "bare"
        else {
            "provider_id": "hub-managed" if memory_form == "explicit" else "",
            "model": model_id,
        }
    )
    profile = AgentProfileConfig.model_validate(
        {
            "id": "hub-memory",
            "name": "Hub Memory",
            "active_model": primary if scope == "agent" else None,
            "running": {
                "reme_light_memory_config": {
                    "memory_model": memory_setting,
                    "auto_memory_include_images": True,
                },
            },
        },
    )
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        AsyncMock(return_value=profile),
    )
    manager = make_memory_model_manager(profile.id)
    # Provider inheritance reads saved references; it does not validate the
    # selected main model or perform a catalog lookup.
    assert manager._memory_model_slot(profile) == ModelSlotConfig(
        provider_id="hub-managed",
        model=model_id,
    )
    directory.assert_not_called()
    if operation == "start":
        await manager.start()
        manager._reme.start.assert_awaited_once_with()
    elif operation == "image":
        monkeypatch.setattr(
            manager,
            "_load_memory_config",
            lambda: profile.running.reme_light_memory_config,
        )
        kwargs = {
            "messages": [
                {
                    "content": [
                        {
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "test",
                            },
                        },
                    ],
                },
            ],
        }
        await manager._prepare_auto_memory_job(kwargs)
        assert kwargs["include_images"] is True
    else:
        await manager._update_qwenpaw_model(
            require_image_support=operation == "update-image",
        )
    manager._reme.update_component.assert_awaited_once()
    actual = manager._reme.update_component.await_args.kwargs["model"]
    assert isinstance(actual, TokenRecordingModelWrapper)
    assert get_model_identity(actual) == ("hub-managed", model_id)
    assert actual.formatter.resize_images_to_max_bytes is True
    if main_state == "same" and scope == "agent" and operation != "image":
        # Deduplicating a primary slot also avoids redundant construction.
        directory.assert_called_once_with()

    fail_call = AsyncMock(side_effect=RuntimeError("Pre-output failure"))
    monkeypatch.setattr(type(actual._model), "__call__", fail_call)
    with pytest.raises(RuntimeError, match="Pre-output failure"):
        await actual([])
    fail_call.assert_awaited_once()
