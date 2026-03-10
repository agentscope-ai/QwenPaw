# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import copaw.providers.ollama_provider as ollama_provider_module
from copaw.providers.ollama_provider import OllamaProvider
from copaw.providers.provider import ModelInfo


def _make_provider() -> OllamaProvider:
    return OllamaProvider(
        id="ollama",
        name="Ollama",
        base_url="http://localhost:11434",
        api_key="EMPTY",
        chat_model="OllamaChatModel",
    )


async def test_auto_load_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://env-ollama.local:11434")

    provider = OllamaProvider(
        id="ollama",
        name="Ollama",
        chat_model="OllamaChatModel",
    )

    assert provider.base_url == "http://env-ollama.local:11434"


async def test_check_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    called = {"count": 0}

    class FakeClient:
        async def list(self):
            called["count"] += 1
            return {"models": []}

    monkeypatch.setattr(provider, "_client", lambda timeout=5: FakeClient())

    ok, msg = await provider.check_connection(timeout=2.0)

    assert ok is True
    assert msg == ""
    assert called["count"] == 1


async def test_import_error_on_missing_ollama(monkeypatch) -> None:
    provider = OllamaProvider(
        id="ollama",
        name="Ollama",
        chat_model="OllamaChatModel",
    )
    monkeypatch.setattr(ollama_provider_module, "ollama", None)

    ok, msg = await provider.check_connection(timeout=1.0)

    assert ok is False
    assert msg == "Ollama Python SDK is not installed"


async def test_check_connection_error_returns_false(monkeypatch) -> None:
    provider = _make_provider()

    class FakeClient:
        async def list(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(provider, "_client", lambda timeout=5: FakeClient())
    monkeypatch.setattr(
        ollama_provider_module.ollama,
        "ResponseError",
        Exception,
    )

    ok, msg = await provider.check_connection(timeout=1.0)

    assert ok is False
    assert msg == f"Unknown exception when connecting to `{provider.base_url}`"


async def test_fetch_models_normalizes_and_deduplicates(monkeypatch) -> None:
    provider = _make_provider()

    class FakeClient:
        async def list(self):
            return {
                "models": [
                    SimpleNamespace(model="qwen2:7b"),
                    SimpleNamespace(model="qwen2:7b"),
                    SimpleNamespace(model="llama3:8b"),
                    SimpleNamespace(model="   "),
                ],
            }

    monkeypatch.setattr(provider, "_client", lambda timeout=5: FakeClient())

    models = await provider.fetch_models(timeout=3.0)

    assert [model.id for model in models] == ["qwen2:7b", "llama3:8b"]
    assert [model.name for model in models] == ["qwen2:7b", "llama3:8b"]
    assert provider.models == models


async def test_fetch_models_error_returns_empty(monkeypatch) -> None:
    provider = _make_provider()

    class FakeClient:
        async def list(self):
            raise RuntimeError("failed")

    monkeypatch.setattr(provider, "_client", lambda timeout=5: FakeClient())
    monkeypatch.setattr(
        ollama_provider_module.ollama,
        "ResponseError",
        Exception,
    )

    models = await provider.fetch_models(timeout=3.0)

    assert models == []


async def test_check_model_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    captured: list[dict] = []

    class FakeClient:
        async def chat(self, **kwargs):
            captured.append(kwargs)
            return {"message": {"content": "pong"}}

    monkeypatch.setattr(provider, "_client", lambda timeout=5: FakeClient())

    ok, msg = await provider.check_model_connection("qwen2:7b", timeout=4.0)

    assert ok is True
    assert msg == ""
    assert len(captured) == 1
    assert captured[0]["model"] == "qwen2:7b"
    assert captured[0]["messages"] == [{"role": "user", "content": "ping"}]
    assert captured[0]["options"] == {"num_predict": 1}


async def test_check_model_connection_empty_model_id_returns_false() -> None:
    provider = _make_provider()

    ok, msg = await provider.check_model_connection("   ", timeout=4.0)

    assert ok is False
    assert msg == "Empty model ID"


async def test_check_model_connection_error_returns_false(monkeypatch) -> None:
    provider = _make_provider()

    class FakeClient:
        async def chat(self, **kwargs):
            _ = kwargs
            raise RuntimeError("failed")

    monkeypatch.setattr(provider, "_client", lambda timeout=5: FakeClient())
    monkeypatch.setattr(
        ollama_provider_module.ollama,
        "ResponseError",
        Exception,
    )

    ok, msg = await provider.check_model_connection("qwen2:7b", timeout=4.0)

    assert ok is False
    assert msg == "Unknown exception when connecting to `qwen2:7b`"


async def test_update_config_updates_only_non_none_values() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "name": "Ollama Local",
            "base_url": "http://127.0.0.1:11434",
            "api_key": "EMPTY-NEW",
            "chat_model": "OllamaChatModel",
            "api_key_prefix": "",
        },
    )

    assert provider.name == "Ollama Local"
    assert provider.base_url == "http://127.0.0.1:11434"
    assert provider.api_key == "EMPTY-NEW"
    assert provider.chat_model == "OllamaChatModel"
    assert provider.api_key_prefix == ""


async def test_add_model_calls_pull(monkeypatch) -> None:
    provider = _make_provider()
    called = {"timeout": [], "model": None, "list_count": 0}

    class FakeClient:
        async def pull(self, model: str):
            called["model"] = model

        async def list(self):
            called["list_count"] += 1
            return {"models": []}

    def _fake_client(timeout=5):
        called["timeout"].append(timeout)
        return FakeClient()

    monkeypatch.setattr(provider, "_client", _fake_client)

    await provider.add_model(
        ModelInfo(id="qwen2:7b", name="Qwen2 7B"),
        timeout=8.0,
    )

    assert called == {
        "timeout": [8.0, 5],
        "model": "qwen2:7b",
        "list_count": 1,
    }


async def test_delete_model_calls_delete(monkeypatch) -> None:
    provider = _make_provider()
    called = {"timeout": [], "model": None, "list_count": 0}

    class FakeClient:
        async def delete(self, model: str):
            called["model"] = model

        async def list(self):
            called["list_count"] += 1
            return {"models": []}

    def _fake_client(timeout=5):
        called["timeout"].append(timeout)
        return FakeClient()

    monkeypatch.setattr(provider, "_client", _fake_client)

    await provider.delete_model("qwen2:7b", timeout=6.0)

    assert called == {
        "timeout": [6.0, 5],
        "model": "qwen2:7b",
        "list_count": 1,
    }
