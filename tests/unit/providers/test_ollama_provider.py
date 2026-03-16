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
    assert msg == f"Failed to connect to Ollama at `{provider.base_url}`: boom"


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
    assert msg == "Model connection failed for `qwen2:7b`: failed"


async def test_update_config_updates_non_none_values_and_get_info(
    monkeypatch,
) -> None:
    provider = _make_provider()

    async def fake_fetch_models(self, timeout: float = 5):
        assert self is provider
        assert timeout == 1
        return [ModelInfo(id="qwen2:7b", name="Qwen2 7B")]

    monkeypatch.setattr(OllamaProvider, "fetch_models", fake_fetch_models)

    provider.update_config(
        {
            "name": "Ollama Local",
            "base_url": "http://127.0.0.1:11434",
            "api_key": "EMPTY-NEW",
            "chat_model": "OllamaChatModel",
            "generate_kwargs": {"temperature": 0.3, "num_ctx": 4096},
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.name == "Ollama Local"
    assert provider.base_url == "http://127.0.0.1:11434"
    assert provider.api_key == "EMPTY-NEW"
    assert provider.chat_model == "OllamaChatModel"
    assert provider.generate_kwargs == {
        "temperature": 0.3,
        "num_ctx": 4096,
    }
    assert info.name == "Ollama Local"
    assert info.base_url == "http://127.0.0.1:11434"
    assert info.api_key == "EMPTY-NEW"
    assert info.chat_model == "OllamaChatModel"
    assert info.generate_kwargs == {
        "temperature": 0.3,
        "num_ctx": 4096,
    }


async def test_update_config_skips_none_values_and_get_info(
    monkeypatch,
) -> None:
    provider = _make_provider()
    provider.generate_kwargs = {"temperature": 0.1}

    async def fake_fetch_models(self, timeout: float = 5):
        assert self is provider
        assert timeout == 1
        return [ModelInfo(id="llama3:8b", name="llama3:8b")]

    monkeypatch.setattr(OllamaProvider, "fetch_models", fake_fetch_models)

    provider.update_config(
        {
            "name": None,
            "base_url": None,
            "api_key": None,
            "chat_model": None,
            "api_key_prefix": None,
            "generate_kwargs": None,
        },
    )

    info = await provider.get_info()

    assert provider.name == "Ollama"
    assert provider.base_url == "http://localhost:11434"
    assert provider.api_key == "EMPTY"
    assert provider.chat_model == "OllamaChatModel"
    assert provider.generate_kwargs == {"temperature": 0.1}
    assert info.name == "Ollama"
    assert info.base_url == "http://localhost:11434"
    assert info.api_key == "******"
    assert info.chat_model == "OllamaChatModel"
    assert info.generate_kwargs == {"temperature": 0.1}


async def test_update_config_keeps_chat_model_for_non_custom_provider(
    monkeypatch,
) -> None:
    provider = _make_provider()

    async def fake_fetch_models(self, timeout: float = 5):
        assert self is provider
        assert timeout == 1
        return []

    monkeypatch.setattr(OllamaProvider, "fetch_models", fake_fetch_models)

    provider.update_config(
        {
            "chat_model": "AnotherChatModel",
            "name": "Ollama Updated",
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.name == "Ollama Updated"
    assert provider.chat_model == "OllamaChatModel"
    assert info.name == "Ollama Updated"
    assert info.chat_model == "OllamaChatModel"
    assert info.api_key == "EMPTY"


async def test_add_model_calls_pull(monkeypatch) -> None:
    provider = _make_provider()
    called = {"timeout": [], "model": None, "list_count": 0}
    payload = {"models": []}

    class FakeClient:
        def __init__(self) -> None:
            self.payload = payload

        async def pull(self, model: str):
            called["model"] = model
            self.payload["models"].append(
                SimpleNamespace(model=model, name=model),
            )

        async def list(self):
            called["list_count"] += 1
            return self.payload

    def _fake_client(timeout=5):
        called["timeout"].append(timeout)
        return FakeClient()

    monkeypatch.setattr(provider, "_client", _fake_client)

    await provider.add_model(
        ModelInfo(id="qwen2:7b", name="Qwen2 7B"),
        timeout=8.0,
    )

    assert provider.extra_models == [ModelInfo(id="qwen2:7b", name="qwen2:7b")]

    assert called == {
        "timeout": [8.0, 5],
        "model": "qwen2:7b",
        "list_count": 1,
    }


async def test_delete_model_calls_delete(monkeypatch) -> None:
    provider = _make_provider()
    called = {"timeout": [], "model": None, "list_count": 0}
    payload = {
        "models": [
            SimpleNamespace(model="qwen3:8b"),
            SimpleNamespace(model="qwen3:4b"),
        ],
    }

    class FakeClient:
        def __init__(self):
            self.payload = payload

        async def delete(self, model: str):
            called["model"] = model
            for m in self.payload["models"]:
                if m.model == model:
                    self.payload["models"].remove(m)
                    break

        async def list(self):
            called["list_count"] += 1
            return self.payload

    def _fake_client(timeout=5):
        called["timeout"].append(timeout)
        return FakeClient()

    monkeypatch.setattr(provider, "_client", _fake_client)

    await provider.delete_model("qwen3:8b", timeout=6.0)

    assert called == {
        "timeout": [6.0, 5],
        "model": "qwen3:8b",
        "list_count": 1,
    }

    assert provider.extra_models == [ModelInfo(id="qwen3:4b", name="qwen3:4b")]
