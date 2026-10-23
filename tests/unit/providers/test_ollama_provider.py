# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.ollama_provider import (
    OllamaProvider,
    parse_ollama_model_context_length,
    parse_ollama_num_ctx,
    resolve_ollama_context_window,
)


def _make_provider(base_url: str = "http://localhost:11434") -> OllamaProvider:
    return OllamaProvider(
        id="ollama",
        name="Ollama",
        base_url=base_url,
        api_key="EMPTY",
        chat_model="OpenAIChatModel",
    )


@pytest.mark.parametrize(
    ("base_url", "expected_base_url"),
    [
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://localhost:11434/", "http://localhost:11434"),
        ("http://localhost:11434/v1", "http://localhost:11434"),
        ("http://localhost:11434/v1/", "http://localhost:11434"),
    ],
)
def test_base_url_is_normalized_on_init(
    base_url: str,
    expected_base_url: str,
) -> None:
    provider = _make_provider(base_url=base_url)

    assert provider.base_url == expected_base_url


@pytest.mark.parametrize(
    "env_base_url",
    [
        "http://env-ollama.local:11434",
        "http://env-ollama.local:11434/",
        "http://env-ollama.local:11434/v1",
        "http://env-ollama.local:11434/v1/",
    ],
)
async def test_auto_load_from_env_normalizes_base_url(
    monkeypatch,
    env_base_url: str,
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", env_base_url)

    provider = OllamaProvider(
        id="ollama",
        name="Ollama",
        chat_model="OpenAIChatModel",
    )

    assert provider.base_url == "http://env-ollama.local:11434"


def test_update_config_normalizes_base_url() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "base_url": "http://updated-ollama.local:11434/v1/",
        },
    )

    assert provider.base_url == "http://updated-ollama.local:11434"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434",
        "http://localhost:11434/",
        "http://localhost:11434/v1",
        "http://localhost:11434/v1/",
    ],
)
def test_client_uses_single_v1_suffix(monkeypatch, base_url: str) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncOpenAI:
        def __init__(self, *, base_url, api_key, timeout) -> None:
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            captured["timeout"] = timeout

    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.AsyncOpenAI",
        FakeAsyncOpenAI,
    )

    provider = _make_provider(base_url=base_url)
    getattr(provider, "_client")(timeout=7)

    assert captured == {
        "base_url": "http://localhost:11434/v1",
        "api_key": "EMPTY",
        "timeout": 7,
    }


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434",
        "http://localhost:11434/",
        "http://localhost:11434/v1",
        "http://localhost:11434/v1/",
    ],
)
def test_get_chat_model_instance_uses_single_v1_suffix(
    monkeypatch,
    base_url: str,
) -> None:
    captured: list[dict] = []

    class FakeCompat:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(
        "qwenpaw.providers.openai_chat_model_compat.OpenAIChatModelCompat",
        FakeCompat,
    )

    provider = _make_provider(base_url=base_url)
    provider.get_chat_model_instance("llama3.1")

    assert captured[0]["model"] == "llama3.1"
    assert captured[0]["credential"].api_key.get_secret_value() == "EMPTY"
    assert captured[0]["stream"] is True
    assert str(captured[0]["credential"].base_url).rstrip("/") == (
        "http://localhost:11434/v1"
    )


def test_parse_ollama_num_ctx_from_parameters() -> None:
    assert parse_ollama_num_ctx("temperature 0.7\nnum_ctx 8192\n") == 8192
    assert parse_ollama_num_ctx("temperature 0.7") is None
    assert parse_ollama_num_ctx("num_ctx 512") is None  # below ModelInfo floor


def test_parse_ollama_model_context_length() -> None:
    assert (
        parse_ollama_model_context_length(
            {"qwen3.context_length": 131072, "other": 1},
        )
        == 131072
    )
    assert parse_ollama_model_context_length({}) is None


def test_resolve_ollama_context_prefers_served_then_num_ctx() -> None:
    show = {
        "parameters": "num_ctx 8192\n",
        "model_info": {"qwen3.context_length": 131072},
    }
    assert (
        resolve_ollama_context_window(
            show_payload=show,
            served_context=4096,
        )
        == 4096
    )
    assert resolve_ollama_context_window(show_payload=show) == 8192
    assert (
        resolve_ollama_context_window(
            show_payload={"model_info": {"qwen3.context_length": 65536}},
        )
        == 65536
    )
    assert resolve_ollama_context_window(show_payload={}) is None


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_fetch_models_attaches_served_context(monkeypatch) -> None:
    provider = _make_provider()

    async def fake_super_fetch(self, timeout: float = 5):
        return [ModelInfo(id="qwen3:8b", name="qwen3:8b")]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(
                200,
                {
                    "models": [
                        {
                            "name": "qwen3:8b",
                            "model": "qwen3:8b",
                            "context_length": 4096,
                        },
                    ],
                },
            )

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            assert json == {"model": "qwen3:8b"}
            return _FakeResponse(
                200,
                {
                    "parameters": "num_ctx 8192\n",
                    "model_info": {"qwen3.context_length": 131072},
                },
            )

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fake_super_fetch,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.httpx.AsyncClient",
        FakeClient,
    )

    models = await provider.fetch_models()
    assert len(models) == 1
    # Loaded /api/ps window wins over Modelfile num_ctx.
    assert models[0].max_input_length_auto_detected == 4096


@pytest.mark.asyncio
async def test_fetch_models_uses_show_when_not_loaded(monkeypatch) -> None:
    provider = _make_provider()

    async def fake_super_fetch(self, timeout: float = 5):
        return [ModelInfo(id="qwen3:8b", name="qwen3:8b")]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            return _FakeResponse(
                200,
                {
                    "parameters": "num_ctx 8192\n",
                    "model_info": {"qwen3.context_length": 131072},
                },
            )

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fake_super_fetch,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.httpx.AsyncClient",
        FakeClient,
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 8192
