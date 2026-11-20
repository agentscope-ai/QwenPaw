# -*- coding: utf-8 -*-
"""A downloaded decision model keeps the chat default independent."""
# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.routers.local_models import (
    StartServerRequest,
    start_llamacpp_server,
    _clear_local_runtime_provider_state,
)
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.local_models.llamacpp import LlamaCppServerSetupResult
from qwenpaw.providers import ProviderManager
from qwenpaw.providers.provider import ModelInfo


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_secret_dir")
async def test_start_restore_and_stop_local_decision_preserves_chat():
    manager = ProviderManager()
    chat = ModelSlotConfig(provider_id="openai", model="chat-fixture")
    manager.active_model = chat
    manager.save_active_model(chat)
    model_id = "fixture/piccolo-gguf"

    async def setup(*_args, **_kwargs):
        return LlamaCppServerSetupResult(
            port=9001,
            model_info=ModelInfo(
                id=model_id,
                name="Piccolo fixture",
                model_type="decision",
            ),
        )

    local_manager = SimpleNamespace(
        setup_server=AsyncMock(side_effect=setup),
        check_llamacpp_installation=lambda: (True, ""),
        is_model_downloaded=lambda _: True,
    )
    result = await start_llamacpp_server(
        StartServerRequest(model_id=model_id),
        local_manager,
        manager,
    )
    slot = ModelSlotConfig(provider_id="qwenpaw-local", model=model_id)
    assert result.model_info.model_type == "decision"
    assert manager.default_models["decision"] == slot
    assert manager.active_model == chat
    assert manager.load_active_model(model_type="decision") == slot
    assert (
        manager.get_provider("qwenpaw-local").base_url
        == "http://127.0.0.1:9001/v1"
    )

    await manager._resume_local_model(local_manager)
    assert (
        manager.get_provider("qwenpaw-local").extra_models[0].model_type
        == "decision"
    )
    assert manager.default_models["decision"] == slot
    assert manager.active_model == chat

    await _clear_local_runtime_provider_state(manager)
    assert manager.default_models["decision"] is None
    assert manager.load_active_model(model_type="decision") is None
    assert manager.active_model == chat


def test_start_request_keeps_existing_shape():
    assert StartServerRequest(model_id="existing/model").model_dump() == {
        "model_id": "existing/model",
    }
