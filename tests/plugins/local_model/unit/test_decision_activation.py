# -*- coding: utf-8 -*-
"""A downloaded decision model keeps the chat default independent."""
# pylint: disable=protected-access

import importlib
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.plugins.local_model_legacy import bundled_local_source
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.providers import ProviderManager
from llamacpp.app import StartServerRequest


@pytest.mark.asyncio
async def test_start_restore_and_stop_local_decision_preserves_chat(
    tmp_path,
    monkeypatch,
):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            bundled_local_source(),
            config={"data_dir": str(tmp_path / "models")},
        )
        binding = (
            PluginRegistry()
            .get_provider("qwenpaw-local")
            .provider_class._sdk_binding
        )
        runtime = binding.spec.connect.__self__
        manager = ProviderManager.get_instance()
        chat = ModelSlotConfig(provider_id="openai", model="chat-fixture")
        await manager.save_active_model_async(chat)
        model_id = "fixture/piccolo-gguf"
        package = type(runtime).__module__.rsplit(".", 1)[0]
        types = importlib.import_module(package + ".model_types")
        local_manager = await runtime.manager()
        setup = AsyncMock(
            return_value=types.LocalServerInfo(
                port=9001,
                model_info=types.LocalModelInfo(
                    id=model_id,
                    name="Piccolo fixture",
                    model_type="decision",
                ),
            ),
        )
        monkeypatch.setattr(local_manager, "ensure_server", setup)
        result = await host.request(
            "POST",
            "/api/local-models/server",
            json={"model_id": model_id},
        )
        slot = ModelSlotConfig(provider_id="qwenpaw-local", model=model_id)
        assert result.status == 200
        assert result.json()["model_info"]["model_type"] == "decision"
        assert manager.default_models["decision"] == slot
        assert manager.active_model == chat
        assert manager.load_active_model(model_type="decision") == slot
        assert binding.provider().base_url == "http://127.0.0.1:9001/v1"

        # Reconnecting retains the saved type, including user overrides.
        setup.return_value = replace(
            setup.return_value,
            model_info=replace(
                setup.return_value.model_info,
                model_type="chat",
            ),
        )
        await binding.restore_selected()
        assert setup.await_count == 2
        assert binding.provider().extra_models[0].model_type == "decision"
        assert manager.default_models["decision"] == slot
        assert manager.active_model == chat

        stopped = await host.request("DELETE", "/api/local-models/server")
        assert stopped.status == 200
        assert manager.default_models["decision"] is None
        assert manager.load_active_model(model_type="decision") is None
        assert manager.active_model == chat


def test_start_request_keeps_existing_shape():
    assert StartServerRequest(model_id="existing/model").model_dump() == {
        "model_id": "existing/model",
    }
