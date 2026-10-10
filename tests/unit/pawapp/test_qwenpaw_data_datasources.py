# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Datasource proxy interception and host-model helpers in the backend."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request, Response

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAIN_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "main.py"
)


def _load_backend():
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_main_datasources_under_test",
        MAIN_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Endpoint helpers under test call set_context_env_vars() for real;
    # stub it so a developer's live ~/.qwenpaw/.env cannot leak into
    # os.environ and pollute unrelated tests that run afterwards.
    module.set_context_env_vars = lambda: None
    return module


def _make_request(method: str, body: bytes = b"") -> Request:
    """Build a minimal ASGI request the proxy handlers can consume."""

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": [],
            "query_string": b"",
        },
        receive=receive,
    )


class _FakeModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


class _FakeInfo:
    def __init__(
        self,
        provider_id: str,
        name: str,
        base_url: str,
        api_key: str,
        models: list[str],
        chat_model: str = "OpenAIChatModel",
        require_api_key: bool = True,
    ) -> None:
        self.id = provider_id
        self.name = name
        self.base_url = base_url
        self.api_key = api_key
        self.chat_model = chat_model
        self.require_api_key = require_api_key
        self.models = [_FakeModel(m) for m in models]
        self.extra_models = []
        self.discovered_models = []


class _FakeSlot:
    def __init__(self, provider_id: str, model: str) -> None:
        self.provider_id = provider_id
        self.model = model


class _FakeManager:
    def __init__(self, infos, slot=None) -> None:
        self._infos = infos
        self._slot = slot

    async def list_provider_info(self):
        return self._infos

    def get_active_model(self):
        return self._slot

    def get_provider(self, provider_id: str):
        for info in self._infos:
            if info.id == provider_id:
                return info
        return None


def _patch_manager(monkeypatch, manager) -> None:
    import qwenpaw.providers.provider_manager as provider_manager_module

    monkeypatch.setattr(
        provider_manager_module.ProviderManager,
        "get_instance",
        classmethod(lambda cls: manager),
    )


@pytest.mark.asyncio
async def test_reuse_host_model_copies_llm_from_active(monkeypatch) -> None:
    module = _load_backend()
    manager = _FakeManager(
        [
            _FakeInfo(
                "dashscope",
                "DashScope",
                "https://dashscope.example.com/v1",
                "sk-host",
                ["qwen3-max"],
                chat_model="DashScopeChatModel",
            ),
        ],
        slot=_FakeSlot("dashscope", "qwen3-max"),
    )
    _patch_manager(monkeypatch, manager)

    config = module.DataAppConfig()
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    push = AsyncMock()
    monkeypatch.setattr(module, "_push_model_config", push)

    result = await module.reuse_host_model({"target": "llm", "reuse": True})

    # DashScope's compatible-mode endpoint stays reusable even though the
    # host wraps it with its own chat model implementation.
    assert result["llm"]["reuse_host"] is True
    assert result["llm"]["provider"] == "openai"
    assert result["llm"]["base_url"] == "https://dashscope.example.com/v1"
    assert result["llm"]["model"] == "qwen3-max"
    assert result["llm"]["api_key"] == "sk-host"
    assert result["llm"]["host_provider_name"] == "DashScope"
    push.assert_awaited_once()


@pytest.mark.asyncio
async def test_reuse_host_model_embedding_keeps_local_model(
    monkeypatch,
) -> None:
    module = _load_backend()
    manager = _FakeManager(
        [
            _FakeInfo(
                "dashscope",
                "DashScope",
                "https://dashscope.example.com/v1",
                "sk-host",
                ["qwen3-max"],
            ),
        ],
        slot=_FakeSlot("dashscope", "qwen3-max"),
    )
    _patch_manager(monkeypatch, manager)

    config = module.DataAppConfig()
    config.embedding.model = "text-embedding-v3"
    config.embedding.dim = 768
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    monkeypatch.setattr(module, "_push_model_config", AsyncMock())

    result = await module.reuse_host_model(
        {"target": "embedding", "reuse": True},
    )

    # The host has no "active embedding model" concept: only the provider's
    # endpoint and key are shared, the model/dim stay locally configured.
    assert result["embedding"]["reuse_host"] is True
    assert (
        result["embedding"]["base_url"] == "https://dashscope.example.com/v1"
    )
    assert result["embedding"]["api_key"] == "sk-host"
    assert result["embedding"]["host_provider_name"] == "DashScope"
    assert result["embedding"]["model"] == "text-embedding-v3"
    assert result["embedding"]["dim"] == 768


@pytest.mark.asyncio
async def test_reuse_host_model_disable_keeps_snapshot(monkeypatch) -> None:
    module = _load_backend()
    # No host manager is patched: disabling must not need the host at all.
    config = module.DataAppConfig()
    config.llm.reuse_host = True
    config.llm.base_url = "https://old.example.com/v1"
    config.llm.model = "old-model"
    config.llm.api_key = "sk-old"
    config.llm.host_provider_name = "Old"
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    monkeypatch.setattr(module, "_push_model_config", AsyncMock())

    result = await module.reuse_host_model({"target": "llm", "reuse": False})

    # Switching back to manual entry keeps the last values so nothing is lost.
    assert result["llm"]["reuse_host"] is False
    assert result["llm"]["base_url"] == "https://old.example.com/v1"
    assert result["llm"]["model"] == "old-model"
    assert result["llm"]["api_key"] == "sk-old"


@pytest.mark.asyncio
async def test_reuse_host_model_rejects_when_no_active_model(
    monkeypatch,
) -> None:
    module = _load_backend()
    manager = _FakeManager(
        [
            _FakeInfo(
                "dashscope",
                "DashScope",
                "https://dashscope.example.com/v1",
                "sk-host",
                ["qwen3-max"],
            ),
        ],
    )
    _patch_manager(monkeypatch, manager)

    config = module.DataAppConfig()
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)

    with pytest.raises(HTTPException) as excinfo:
        await module.reuse_host_model({"target": "llm", "reuse": True})
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_reuse_host_model_rejects_native_protocol_active(
    monkeypatch,
) -> None:
    module = _load_backend()
    manager = _FakeManager(
        [
            _FakeInfo(
                "anthropic",
                "Anthropic",
                "https://api.anthropic.com",
                "sk-ant",
                ["claude-x"],
                chat_model="AnthropicChatModel",
            ),
        ],
        slot=_FakeSlot("anthropic", "claude-x"),
    )
    _patch_manager(monkeypatch, manager)

    config = module.DataAppConfig()
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)

    with pytest.raises(HTTPException) as excinfo:
        await module.reuse_host_model({"target": "llm", "reuse": True})
    # Native protocols cannot serve the OpenAI chat-completions client.
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_reuse_host_model_rejects_unknown_target() -> None:
    module = _load_backend()

    with pytest.raises(HTTPException) as excinfo:
        await module.reuse_host_model({"target": "neo4j", "reuse": True})
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_set_config_resyncs_reused_models_from_host(monkeypatch) -> None:
    module = _load_backend()
    manager = _FakeManager(
        [
            _FakeInfo(
                "dashscope",
                "DashScope",
                "https://dashscope.example.com/v1",
                "sk-host",
                ["qwen3-max"],
            ),
        ],
        slot=_FakeSlot("dashscope", "qwen3-max"),
    )
    _patch_manager(monkeypatch, manager)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    monkeypatch.setattr(module, "_push_model_config", AsyncMock())

    payload = module.DataAppConfig().to_dict()
    payload["llm"] = {
        "provider": "openai",
        "base_url": "https://stale.example.com/v1",
        "model": "stale-model",
        "api_key": "sk-stale",
        "reuse_host": True,
        "host_provider_name": "Stale",
    }

    result = await module.set_config(payload)

    # Saving while reuse is enabled follows the host's current active model
    # instead of persisting the stale snapshot the page was loaded with.
    assert result["llm"]["base_url"] == "https://dashscope.example.com/v1"
    assert result["llm"]["model"] == "qwen3-max"
    assert result["llm"]["api_key"] == "sk-host"
    assert result["llm"]["host_provider_name"] == "DashScope"


@pytest.mark.asyncio
async def test_set_config_keeps_manual_values_without_reuse(
    monkeypatch,
) -> None:
    module = _load_backend()
    manager = _FakeManager(
        [
            _FakeInfo(
                "dashscope",
                "DashScope",
                "https://dashscope.example.com/v1",
                "sk-host",
                ["qwen3-max"],
            ),
        ],
        slot=_FakeSlot("dashscope", "qwen3-max"),
    )
    _patch_manager(monkeypatch, manager)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    monkeypatch.setattr(module, "_push_model_config", AsyncMock())

    payload = module.DataAppConfig().to_dict()
    payload["llm"] = {
        "provider": "openai",
        "base_url": "https://manual.example.com/v1",
        "model": "manual-model",
        "api_key": "sk-manual",
        "reuse_host": False,
        "host_provider_name": "",
    }

    result = await module.set_config(payload)

    # Manual entries are never overwritten by the host's active model.
    assert result["llm"]["base_url"] == "https://manual.example.com/v1"
    assert result["llm"]["model"] == "manual-model"
    assert result["llm"]["api_key"] == "sk-manual"


@pytest.mark.asyncio
async def test_restore_active_datasource_applies_once(monkeypatch) -> None:
    module = _load_backend()
    gateway = AsyncMock(return_value={"success": True})
    module._gateway.json = gateway

    config = module.DataAppConfig()
    config.datasources.active_id = "pg-demo"
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    monkeypatch.setattr(
        type(module._context_service),
        "is_ready",
        property(lambda self: True),
    )
    module._active_restore_done = False

    await module._restore_active_datasource()
    # Subsequent triggers must not repeat the restore round-trip.
    await module._restore_active_datasource()

    restore_calls = [
        call
        for call in gateway.await_args_list
        if call.args[:2] == ("PUT", "/api/datasources/active")
    ]
    assert len(restore_calls) == 1


@pytest.mark.asyncio
async def test_restore_active_datasource_retries_after_failure(
    monkeypatch,
) -> None:
    module = _load_backend()
    gateway = AsyncMock(
        side_effect=[
            HTTPException(status_code=503),
            {"success": True},
        ],
    )
    module._gateway.json = gateway

    config = module.DataAppConfig()
    config.datasources.active_id = "pg-demo"
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    monkeypatch.setattr(
        type(module._context_service),
        "is_ready",
        property(lambda self: True),
    )
    module._active_restore_done = False

    # A restore racing the service's startup window must not latch.
    await module._restore_active_datasource()
    await module._restore_active_datasource()
    # Success latches; further triggers are no-ops.
    await module._restore_active_datasource()

    assert gateway.await_count == 2


@pytest.mark.asyncio
async def test_on_before_start_resets_restore_flag(monkeypatch) -> None:
    module = _load_backend()
    hook = AsyncMock()
    monkeypatch.setattr(module, "on_before_start", hook)
    # The reuse sync reads config; keep the test independent of the
    # developer's real ~/.qwenpaw/apps/qwenpaw-data/config.json.
    monkeypatch.setattr(module, "load_config", module.DataAppConfig)
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    module._active_restore_done = True

    await module._on_before_start()

    assert module._active_restore_done is False
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_proxy_set_active_persists_selection(monkeypatch) -> None:
    module = _load_backend()
    proxy = AsyncMock(
        return_value=Response(status_code=200, content=b'{"success": true}'),
    )
    module._gateway.proxy = proxy

    config = module.DataAppConfig()
    saved = []
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", saved.append)

    request = _make_request(
        "PUT",
        body=b'{"datasource_id": "pg-demo"}',
    )
    response = await module._proxy_set_active_datasource(
        "datasources/active",
        request,
    )

    assert response.status_code == 200
    assert saved and saved[-1].datasources.active_id == "pg-demo"
    proxy.assert_awaited_once_with("datasources/active", request)


@pytest.mark.asyncio
async def test_proxy_set_active_skips_persist_on_upstream_error(
    monkeypatch,
) -> None:
    module = _load_backend()
    module._gateway.proxy = AsyncMock(return_value=Response(status_code=404))

    config = module.DataAppConfig()
    saved = []
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", saved.append)

    request = _make_request(
        "PUT",
        body=b'{"datasource_id": "pg-demo"}',
    )
    response = await module._proxy_set_active_datasource(
        "datasources/active",
        request,
    )

    # A rejected switch keeps the previous persisted selection.
    assert response.status_code == 404
    assert not saved


@pytest.mark.asyncio
async def test_proxy_delete_clears_matching_active_selection(
    monkeypatch,
) -> None:
    module = _load_backend()
    module._gateway.proxy = AsyncMock(return_value=Response(status_code=200))

    config = module.DataAppConfig()
    config.datasources.active_id = "pg-demo"
    saved = []
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "save_config", saved.append)

    await module._proxy_delete_datasource(
        "semantic-config/datasource/pg-demo",
        _make_request("DELETE"),
    )
    assert saved and saved[-1].datasources.active_id == ""

    # Deleting an unrelated source leaves the selection alone.
    saved.clear()
    await module._proxy_delete_datasource(
        "semantic-config/datasource/other",
        _make_request("DELETE"),
    )
    assert not saved


@pytest.mark.asyncio
async def test_config_test_forwards_to_context_service() -> None:
    module = _load_backend()
    gateway = AsyncMock(
        return_value={
            "success": True,
            "message": "Connected. Model: qwen3-max",
            "detected_dim": None,
        },
    )
    module._gateway.json = gateway

    result = await module.test_config_target(
        "llm",
        {
            "llm": {
                "base_url": "https://example.com/v1",
                "api_key": "sk-test",
                "model": "qwen3-max",
            },
        },
    )

    assert result["ok"] is True
    assert result["error"] is None
    gateway.assert_awaited_once_with(
        "POST",
        "/api/system/model-config/llm/test",
        body={
            "base_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "qwen3-max",
        },
    )


@pytest.mark.asyncio
async def test_config_test_maps_sidecar_failure() -> None:
    module = _load_backend()
    module._gateway.json = AsyncMock(
        return_value={"success": False, "message": "bad endpoint"},
    )

    result = await module.test_config_target(
        "embedding",
        {"embedding": {"model": "text-embedding-v3"}},
    )

    assert result["ok"] is False
    assert result["error"] == "bad endpoint"
    assert result["detected_dim"] is None


@pytest.mark.asyncio
async def test_config_test_reports_unready_gateway() -> None:
    module = _load_backend()
    module._gateway.json = AsyncMock(
        side_effect=HTTPException(
            status_code=503,
            detail="Context gateway is not ready",
        ),
    )

    result = await module.test_config_target("llm", {"llm": {}})

    assert result["ok"] is False
    assert "not ready" in result["error"]
