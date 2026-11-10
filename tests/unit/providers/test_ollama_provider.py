# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import time
from typing import Any

from agentscope.model import OpenAIChatModel
import pytest

from qwenpaw.providers.ollama_provider import (
    OllamaProvider,
    _ollama_model_aliases,
    parse_ollama_chat_num_ctx,
    parse_ollama_num_ctx,
    parse_ollama_served_context_length,
    resolve_ollama_context_window,
)
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.thinking import ThinkingControl
from qwenpaw.utils.io_utils import run_sync_io


def _make_provider(base_url: str = "http://localhost:11434") -> OllamaProvider:
    return OllamaProvider(
        id="ollama",
        name="Ollama",
        base_url=base_url,
        api_key="EMPTY",
        chat_model="OpenAIChatModel",
    )


async def test_summary_uses_declared_disable_thinking_wire(
    monkeypatch,
) -> None:
    provider = _make_provider()
    provider.models = [
        ModelInfo(
            id="strict-model",
            name="Strict model",
            thinking_control=ThinkingControl(
                kind="budget",
                budget_min=1,
                budget_max=8192,
                supports_off=True,
                wire="compat_budget",
            ),
        ),
    ]
    captured: dict = {}

    async def capture_call(self, *args, **kwargs):
        del self, args
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(OpenAIChatModel, "_call_api", capture_call)
    model = provider.get_chat_model_instance("strict-model")
    result = await model._call_api(
        "strict-model",
        [],
        disable_thinking=True,
    )

    assert result == "ok"
    assert captured == {"extra_body": {"enable_thinking": False}}


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
    assert parse_ollama_num_ctx("num_ctx 512") == 512
    # Non-strings must not raise; one bad model cannot abort the batch.
    assert parse_ollama_num_ctx({"num_ctx": 1}) is None
    assert parse_ollama_num_ctx(["num_ctx 8192"]) is None
    assert parse_ollama_num_ctx(8192) is None
    assert parse_ollama_num_ctx(None) is None


def test_parse_ollama_served_context_length_is_strict() -> None:
    assert parse_ollama_served_context_length(65536) == 65536
    assert parse_ollama_served_context_length(512) == 512
    assert parse_ollama_served_context_length("8192") == 8192
    assert parse_ollama_served_context_length(" 4096 ") == 4096
    # Bools are ints; do not coerce True to 1.
    assert parse_ollama_served_context_length(True) is None
    assert parse_ollama_served_context_length(False) is None
    # Floats must not be truncated into a window.
    assert parse_ollama_served_context_length(8192.0) is None
    assert parse_ollama_served_context_length(12.5) is None
    assert parse_ollama_served_context_length(0) is None
    assert parse_ollama_served_context_length(-1) is None
    assert parse_ollama_served_context_length("invalid") is None
    assert parse_ollama_served_context_length("8192.0") is None
    assert parse_ollama_served_context_length({"value": 8192}) is None
    assert parse_ollama_served_context_length(None) is None


def test_parse_ollama_chat_num_ctx_from_options() -> None:
    assert (
        parse_ollama_chat_num_ctx({"options": {"num_ctx": 131072}}) == 131072
    )
    assert parse_ollama_chat_num_ctx({"num_ctx": 8192}) == 8192
    # Nested options win over a leftover top-level value.
    assert (
        parse_ollama_chat_num_ctx(
            {"num_ctx": 8192, "options": {"num_ctx": 4096}},
        )
        == 4096
    )
    assert (
        parse_ollama_chat_num_ctx({"options": {"num_ctx": "16384"}}) == 16384
    )
    assert parse_ollama_chat_num_ctx({}) is None
    assert parse_ollama_chat_num_ctx({"options": {}}) is None
    assert parse_ollama_chat_num_ctx({"options": "num_ctx 8192"}) is None
    assert parse_ollama_chat_num_ctx({"options": {"num_ctx": 0}}) is None
    assert parse_ollama_chat_num_ctx({"options": {"num_ctx": True}}) is None
    assert parse_ollama_chat_num_ctx(None) is None


def test_resolve_ollama_context_prefers_chat_then_verified_show() -> None:
    show = {
        "parameters": "num_ctx 131072\n",
        "model_info": {"qwen3.context_length": 262144},
    }
    # Our next chat options are the window we will actually send.
    assert (
        resolve_ollama_context_window(
            show_payload=show,
            served_context=262144,
            chat_num_ctx=131072,
        )
        == 131072
    )
    # A foreign /api/ps window must not beat the Modelfile default.
    assert (
        resolve_ollama_context_window(
            show_payload=show,
            served_context=262144,
        )
        == 131072
    )
    # Served is kept only when it matches the Modelfile window.
    assert (
        resolve_ollama_context_window(
            show_payload=show,
            served_context=131072,
        )
        == 131072
    )
    assert resolve_ollama_context_window(show_payload=show) == 131072
    # GGUF *.context_length is the model maximum, not the served window.
    assert (
        resolve_ollama_context_window(
            show_payload={"model_info": {"qwen3.context_length": 65536}},
        )
        is None
    )
    assert resolve_ollama_context_window(show_payload={}) is None
    # Failed probe is not an empty successful show.
    assert resolve_ollama_context_window(show_payload=None) is None
    # Malformed parameters are not an omitted num_ctx.
    assert (
        resolve_ollama_context_window(
            show_payload={"parameters": {"num_ctx": 8192}},
        )
        is None
    )
    # An unverified served window is not persisted.
    assert (
        resolve_ollama_context_window(
            show_payload=None,
            served_context=8192,
        )
        is None
    )


def test_resolve_show_without_num_ctx_leaves_context_unset() -> None:
    """Cloud and local shows without num_ctx stay unset.

    Inventing 4096 is unsafe when OLLAMA_CONTEXT_LENGTH may be below 4096.
    """
    remote = {
        "remote_host": "https://ollama.com",
        "remote_model": "gpt-oss:120b",
        "model_info": {"gptoss.context_length": 131072},
    }
    assert resolve_ollama_context_window(show_payload=remote) is None
    assert (
        resolve_ollama_context_window(
            show_payload={"remote_host": "https://ollama.com"},
        )
        is None
    )
    assert (
        resolve_ollama_context_window(
            show_payload={"remote_model": "gemma4"},
        )
        is None
    )
    # Blank remote markers are not a window.
    assert (
        resolve_ollama_context_window(
            show_payload={"remote_host": "  ", "remote_model": ""},
        )
        is None
    )
    # A local show that omitted num_ctx stays unset too.
    assert (
        resolve_ollama_context_window(
            show_payload={"parameters": "temperature 0.7\n"},
        )
        is None
    )
    # Explicit num_ctx and a loaded window still win.
    assert (
        resolve_ollama_context_window(
            show_payload={
                "remote_host": "https://ollama.com",
                "parameters": "num_ctx 16384\n",
            },
        )
        == 16384
    )
    # A served window cannot be verified against a show with no num_ctx.
    assert (
        resolve_ollama_context_window(
            show_payload=remote,
            served_context=32768,
        )
        is None
    )
    # Chat options still win when show omitted num_ctx.
    assert (
        resolve_ollama_context_window(
            show_payload=remote,
            served_context=32768,
            chat_num_ctx=16384,
        )
        == 16384
    )


def test_ollama_model_aliases_registry_port_gets_latest() -> None:
    """Tag lives in the final path segment; a port colon is not a tag."""
    model_id = "registry.example.com:5000/team/qwen3"
    aliases = _ollama_model_aliases(model_id)
    assert model_id in aliases
    assert f"{model_id}:latest" in aliases
    assert f"{model_id}:latest".lower() in aliases

    tagged = "registry.example.com:5000/team/qwen3:latest"
    tagged_aliases = _ollama_model_aliases(tagged)
    assert tagged in tagged_aliases
    assert model_id in tagged_aliases
    assert model_id.lower() in tagged_aliases

    # Ordinary untagged / :latest ids still round-trip.
    assert "qwen3:latest" in _ollama_model_aliases("qwen3")
    assert "qwen3" in _ollama_model_aliases("qwen3:latest")


def test_native_probe_headers_add_bearer_without_overriding() -> None:
    provider = OllamaProvider(
        id="ollama",
        name="Ollama",
        base_url="http://localhost:11434",
        api_key="sk-remote",
        chat_model="OpenAIChatModel",
        custom_headers={"X-Proxy-Token": "abc"},
    )
    headers = provider._native_probe_headers()
    assert headers["X-Proxy-Token"] == "abc"
    assert headers["Authorization"] == "Bearer sk-remote"

    provider.custom_headers = {
        "authorization": "Bearer from-proxy",
        "X-Proxy-Token": "abc",
    }
    headers = provider._native_probe_headers()
    assert headers["authorization"] == "Bearer from-proxy"
    assert headers["X-Proxy-Token"] == "abc"
    assert sum(1 for key in headers if key.lower() == "authorization") == 1

    provider.api_key = ""
    provider.custom_headers = {"X-Proxy-Token": "abc"}
    assert provider._native_probe_headers() == {"X-Proxy-Token": "abc"}

    provider.api_key = "   "
    assert "Authorization" not in provider._native_probe_headers()


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
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

        async def aclose(self) -> None:
            return None

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
            return _FakeResponse(200, {"parameters": "num_ctx 4096\n"})

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
    # Served window is kept only after it matches the Modelfile num_ctx.
    assert models[0].max_input_length_auto_detected == 4096


@pytest.mark.asyncio
async def test_fetch_models_ignores_foreign_served_context(
    monkeypatch,
) -> None:
    """A runner loaded by another client must not size our compaction.

    ``/api/ps`` may report 262144 from a temporary ``num_ctx`` override,
    but our next chat request reloads at the Modelfile's 131072.
    """
    provider = _make_provider()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(
                200,
                {
                    "models": [
                        {
                            "name": "qwen3:8b",
                            "model": "qwen3:8b",
                            "context_length": 262144,
                        },
                    ],
                },
            )

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            return _FakeResponse(200, {"parameters": "num_ctx 131072\n"})

    _patch_list_and_native(monkeypatch, FakeClient)
    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 131072


@pytest.mark.asyncio
async def test_fetch_models_uses_chat_num_ctx_over_served(
    monkeypatch,
) -> None:
    """Persist the window we will send, not a currently loaded runner."""
    provider = _make_provider()
    provider.generate_kwargs = {"options": {"num_ctx": 131072}}
    show_calls = 0

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            raise AssertionError(
                "native probes are skipped when chat num_ctx is set",
            )

        async def post(self, url: str, json: dict):
            nonlocal show_calls
            show_calls += 1
            raise AssertionError(
                "native probes are skipped when chat num_ctx is set",
            )

    _patch_list_and_native(monkeypatch, FakeClient)
    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 131072
    assert show_calls == 0


@pytest.mark.asyncio
async def test_fetch_models_model_chat_num_ctx_overrides_provider(
    monkeypatch,
) -> None:
    provider = _make_provider()
    provider.generate_kwargs = {"options": {"num_ctx": 8192}}
    provider.models = [
        ModelInfo(
            id="qwen3:8b",
            name="qwen3:8b",
            generate_kwargs={"options": {"num_ctx": 16384}},
        ),
    ]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            raise AssertionError(
                "native probes are skipped when chat num_ctx is set",
            )

        async def post(self, url: str, json: dict):
            raise AssertionError(
                "native probes are skipped when chat num_ctx is set",
            )

    _patch_list_and_native(monkeypatch, FakeClient)
    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 16384


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

        async def aclose(self) -> None:
            return None

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


@pytest.mark.asyncio
async def test_fetch_models_ignores_gguf_context_length(monkeypatch) -> None:
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

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            return _FakeResponse(
                200,
                {"model_info": {"qwen3.context_length": 131072}},
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
    # No served window and no num_ctx → leave auto-detected unset.
    assert models[0].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_unknown_server_override_does_not_invent_4096(
    monkeypatch,
) -> None:
    """Unloaded local model without num_ctx must not invent 4096.

    Inventing 4096 is unsafe when OLLAMA_CONTEXT_LENGTH may be below 4096.
    """
    provider = _make_provider()

    async def fake_super_fetch(self, timeout: float = 5):
        return [ModelInfo(id="fresh:latest", name="fresh:latest")]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            return _FakeResponse(200, {"parameters": "temperature 0.7\n"})

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fake_super_fetch,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.httpx.AsyncClient",
        FakeClient,
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_cloud_show_without_num_ctx_skips_4096(
    monkeypatch,
) -> None:
    """Shows without num_ctx stay unset for cloud and local models."""
    provider = _make_provider()
    listed = [
        ModelInfo(id="gpt-oss:120b", name="gpt-oss:120b"),
        ModelInfo(id="kimi-k3:cloud", name="kimi-k3:cloud"),
        ModelInfo(id="gemma4:cloud", name="gemma4:cloud"),
        ModelInfo(id="qwen3:8b", name="qwen3:8b"),
    ]

    payloads: dict[str, dict[str, Any]] = {
        "gpt-oss:120b": {
            "remote_host": "https://ollama.com",
            "remote_model": "gpt-oss:120b",
            "model_info": {"gptoss.context_length": 131072},
        },
        "kimi-k3:cloud": {"parameters": "temperature 0.7\n"},
        "gemma4:cloud": {
            "remote_host": "https://ollama.com",
            "remote_model": "gemma4",
            "parameters": "num_ctx 16384\n",
        },
        "qwen3:8b": {"parameters": "temperature 0.7\n"},
    }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            return _FakeResponse(200, payloads[json["model"]])

    _patch_list_and_native(monkeypatch, FakeClient, listed)

    models = await provider.fetch_models()
    by_id = {model.id: model for model in models}
    # remote_* is authoritative; GGUF context_length is not a window.
    assert by_id["gpt-oss:120b"].max_input_length_auto_detected is None
    # :cloud suffix when show omitted remote_* and num_ctx.
    assert by_id["kimi-k3:cloud"].max_input_length_auto_detected is None
    # Explicit num_ctx still wins on a cloud model.
    assert by_id["gemma4:cloud"].max_input_length_auto_detected == 16384
    # Local unloaded model without num_ctx stays unset.
    assert by_id["qwen3:8b"].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_accepts_small_num_ctx(monkeypatch) -> None:
    provider = _make_provider()

    async def fake_super_fetch(self, timeout: float = 5):
        return [ModelInfo(id="tiny:latest", name="tiny:latest")]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            return _FakeResponse(200, {"parameters": "num_ctx 512\n"})

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fake_super_fetch,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.httpx.AsyncClient",
        FakeClient,
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 512


@pytest.mark.asyncio
async def test_fetch_models_native_probes_send_configured_headers(
    monkeypatch,
) -> None:
    provider = OllamaProvider(
        id="ollama",
        name="Ollama",
        base_url="http://remote-ollama.example:11434",
        api_key="sk-remote-secret",
        chat_model="OpenAIChatModel",
        custom_headers={"X-Proxy-Token": "abc"},
    )
    captured: dict = {}

    async def fake_super_fetch(self, timeout: float = 5):
        return [ModelInfo(id="qwen3:8b", name="qwen3:8b")]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["headers"] = kwargs.get("headers")
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            captured["get_url"] = url
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            captured["post_url"] = url
            captured["post_json"] = json
            return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

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
    assert captured["get_url"].endswith("/api/ps")
    assert captured["post_url"].endswith("/api/show")
    assert captured["headers"]["X-Proxy-Token"] == "abc"
    assert captured["headers"]["Authorization"] == "Bearer sk-remote-secret"


def _patch_list_and_native(monkeypatch, client_cls, models=None):
    """Replace ``/v1/models`` and the native httpx client."""

    async def fake_super_fetch(self, timeout: float = 5):
        del self, timeout
        return models or [ModelInfo(id="qwen3:8b", name="qwen3:8b")]

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fake_super_fetch,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.httpx.AsyncClient",
        client_cls,
    )


class _ShowStatusClient:
    """``/api/ps`` is empty; ``/api/show`` returns a non-200 status."""

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aclose(self) -> None:
        return None

    async def get(self, url: str):
        return _FakeResponse(200, {"models": []})

    async def post(self, url: str, json: dict):
        assert url.endswith("/api/show")
        return _FakeResponse(self._status_code, {"error": "denied"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_fetch_models_show_auth_failure_leaves_context_unset(
    monkeypatch,
    status_code: int,
) -> None:
    """401/403 on /api/show must not invent the 4096 estimate."""
    provider = _make_provider()

    class FakeClient(_ShowStatusClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(status_code)

    _patch_list_and_native(monkeypatch, FakeClient)

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_show_timeout_leaves_context_unset(
    monkeypatch,
) -> None:
    """A timed-out /api/show leaves the 128k default in place."""
    provider = _make_provider()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            raise TimeoutError("timed out")

    _patch_list_and_native(monkeypatch, FakeClient)

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_deadline_keeps_completed_probes(
    monkeypatch,
) -> None:
    """A slow ``/api/show`` must not discard probes that already finished.

    A verified ``/api/ps`` match is kept even when another model's show
    exceeds the deadline. A show that returns in time is kept.
    Unfinished models stay unset, and the pre-enrichment list is not
    returned.
    """
    provider = _make_provider()
    loaded_id = "loaded:latest"
    fast_id = "fast:latest"
    slow_ids = [f"slow-{index}:latest" for index in range(6)]
    listed = [
        ModelInfo(id=model_id, name=model_id)
        for model_id in (loaded_id, fast_id, *slow_ids)
    ]
    started_slow = 0
    finished_slow = 0
    show_ids: list[str] = []
    captured: dict = {}
    probe_timeout = 0.5

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args
            captured["timeout"] = kwargs.get("timeout")

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(
                200,
                {
                    "models": [
                        {
                            "name": loaded_id,
                            "model": loaded_id,
                            "context_length": 8192,
                        },
                    ],
                },
            )

        async def post(self, url: str, json: dict):
            nonlocal started_slow, finished_slow
            assert url.endswith("/api/show")
            model_id = json["model"]
            show_ids.append(model_id)
            if model_id == loaded_id:
                return _FakeResponse(
                    200,
                    {"parameters": "num_ctx 8192\n"},
                )
            if model_id == fast_id:
                return _FakeResponse(
                    200,
                    {"parameters": "num_ctx 16384\n"},
                )
            started_slow += 1
            await asyncio.sleep(5)
            finished_slow += 1
            return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

    _patch_list_and_native(monkeypatch, FakeClient, listed)

    started_at = time.monotonic()
    models = await provider.fetch_models(timeout=probe_timeout)
    elapsed = time.monotonic() - started_at

    assert models is not listed
    assert elapsed < 2.5
    # In-flight /api/show calls are cancelled; none of the slow probes finish.
    assert finished_slow == 0
    assert started_slow > 0
    assert loaded_id in show_ids
    assert captured["timeout"] == probe_timeout
    by_id = {model.id: model for model in models}
    assert by_id[loaded_id].max_input_length_auto_detected == 8192
    assert by_id[fast_id].max_input_length_auto_detected == 16384
    for model_id in slow_ids:
        assert by_id[model_id].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_shared_deadline_cancels_slow_ps(
    monkeypatch,
) -> None:
    """HTTPX per-call timeout does not bound total /api/ps response time."""
    provider = _make_provider()
    listed = [
        ModelInfo(id="slow-ps:latest", name="slow-ps:latest"),
        ModelInfo(id="fast:latest", name="fast:latest"),
    ]
    ps_finished = 0
    show_ids: list[str] = []
    probe_timeout = 0.1

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            nonlocal ps_finished
            assert url.endswith("/api/ps")
            await asyncio.sleep(1)
            ps_finished += 1
            return _FakeResponse(
                200,
                {
                    "models": [
                        {
                            "name": "slow-ps:latest",
                            "model": "slow-ps:latest",
                            "context_length": 262144,
                        },
                    ],
                },
            )

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            show_ids.append(json["model"])
            return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

    _patch_list_and_native(monkeypatch, FakeClient, listed)

    started_at = time.monotonic()
    models = await provider.fetch_models(timeout=probe_timeout)
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert ps_finished == 0
    by_id = {model.id: model for model in models}
    # The cancelled /api/ps must not persist a late served window.
    assert by_id["slow-ps:latest"].max_input_length_auto_detected is None
    # No time remains for /api/show after the ps deadline.
    assert show_ids == []
    assert by_id["fast:latest"].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_malformed_parameters_does_not_abort_batch(
    monkeypatch,
) -> None:
    """A non-string ``parameters`` value leaves only that model unset."""
    provider = _make_provider()
    listed = [
        ModelInfo(id="bad:latest", name="bad:latest"),
        ModelInfo(id="good:latest", name="good:latest"),
    ]
    payloads: dict[str, dict[str, Any]] = {
        "bad:latest": {"parameters": {"num_ctx": 8192}},
        "good:latest": {"parameters": "num_ctx 8192\n"},
    }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            return _FakeResponse(200, payloads[json["model"]])

    _patch_list_and_native(monkeypatch, FakeClient, listed)

    models = await provider.fetch_models()
    by_id = {model.id: model for model in models}
    # Malformed parameters must omit the field (not clear it).
    assert (
        "max_input_length_auto_detected"
        not in by_id["bad:latest"].model_fields_set
    )
    assert by_id["bad:latest"].max_input_length_auto_detected is None
    assert by_id["good:latest"].max_input_length_auto_detected == 8192


@pytest.mark.asyncio
async def test_fetch_models_constructs_async_client_off_loop(
    monkeypatch,
) -> None:
    """``AsyncClient`` is built via ``run_sync_io`` and closed with aclose."""
    provider = _make_provider()
    calls = {"init": 0, "enter": 0, "aclose": 0, "sync": 0}
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs
            calls["init"] += 1

        async def __aenter__(self):
            calls["enter"] += 1
            return self

        async def aclose(self) -> None:
            calls["aclose"] += 1

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            del url, json
            return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

    async def spy_run_sync_io(operation, /, *args, **kwargs):
        calls["sync"] += 1
        captured["operation"] = operation
        return await run_sync_io(operation, *args, **kwargs)

    _patch_list_and_native(monkeypatch, FakeClient)
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.run_sync_io",
        spy_run_sync_io,
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 8192
    assert calls["init"] == 1
    assert calls["sync"] == 1
    assert captured["operation"] is FakeClient
    assert calls["aclose"] == 1
    assert calls["enter"] == 0


@pytest.mark.asyncio
async def test_check_model_connection_does_not_probe_show(
    monkeypatch,
) -> None:
    """Connection checks list /v1/models and do not call /api/show."""
    provider = _make_provider()
    calls = {"list": 0, "native": 0}

    async def fake_super_fetch(self, timeout: float = 5):
        del self
        calls["list"] += 1
        assert timeout == 3
        return [
            ModelInfo(id="qwen3:8b", name="qwen3:8b"),
            ModelInfo(id="other:latest", name="other:latest"),
        ]

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            calls["native"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            calls["native"] += 1
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            calls["native"] += 1
            return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fake_super_fetch,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_provider.httpx.AsyncClient",
        FakeClient,
    )

    found = await provider.check_model_connection("qwen3:8b", timeout=3)
    assert found.success is True
    assert found.verification == "provider_only"

    missing = await provider.check_model_connection(
        "missing:latest",
        timeout=3,
    )
    assert missing.success is False
    assert missing.error_kind == "model_not_found"
    assert calls["list"] == 2
    assert calls["native"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ps_payload",
    [
        [],  # top-level list (wangfei repro)
        {"models": 123},  # models not iterable
        "not-a-dict",  # unexpected scalar
    ],
)
async def test_fetch_models_invalid_ps_still_probes_show(
    monkeypatch,
    ps_payload: Any,
) -> None:
    """Invalid ``/api/ps`` JSON must not skip ``/api/show`` probes.

    A top-level list or non-iterable ``models`` previously raised inside
    ``_fetch_served_contexts`` and was swallowed by
    ``_enrich_listed_models``, which returned before any show call.
    """
    provider = _make_provider()
    show_calls: list[str] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(200, ps_payload)

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            show_calls.append(json["model"])
            return _FakeResponse(
                200,
                {"parameters": "num_ctx 8192\n"},
            )

    _patch_list_and_native(monkeypatch, FakeClient)

    models = await provider.fetch_models()
    assert show_calls == ["qwen3:8b"]
    assert models[0].max_input_length_auto_detected == 8192


@pytest.mark.asyncio
async def test_successful_unknown_context_clears_stale_auto_detected(
    monkeypatch,
) -> None:
    """Successful show without num_ctx must clear a prior auto-detected value.

    Failed probes omit the field so merge keeps the old window; a successful
    probe that no longer reports context must not retain a stale 65536.
    """
    from qwenpaw.providers.provider_discovery import merge_discovered_model

    provider = _make_provider()
    model_id = "qwen3:8b"
    first = ModelInfo(
        id=model_id,
        name=model_id,
        max_input_length_auto_detected=65536,
    )
    provider.discovered_models = [
        merge_discovered_model(provider, first, "2026-11-06T00:00:00Z"),
    ]
    assert (
        provider.discovered_models[0].max_input_length_auto_detected == 65536
    )

    class UnknownContextClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            # Successful show, Modelfile no longer sets num_ctx.
            return _FakeResponse(200, {"parameters": "temperature 0.7\n"})

    _patch_list_and_native(
        monkeypatch,
        UnknownContextClient,
        models=[ModelInfo(id=model_id, name=model_id)],
    )
    fetched = await provider.fetch_models()
    assert fetched[0].max_input_length_auto_detected is None
    assert "max_input_length_auto_detected" in fetched[0].model_fields_set

    merged = merge_discovered_model(
        provider,
        fetched[0],
        "2026-11-06T01:00:00Z",
    )
    assert merged.max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_failed_show_probe_retains_previous_auto_detected(
    monkeypatch,
) -> None:
    """A failed /api/show must not clear a previously discovered window."""
    from qwenpaw.providers.provider_discovery import merge_discovered_model

    provider = _make_provider()
    model_id = "qwen3:8b"
    first = ModelInfo(
        id=model_id,
        name=model_id,
        max_input_length_auto_detected=65536,
    )
    provider.discovered_models = [
        merge_discovered_model(provider, first, "2026-11-06T00:00:00Z"),
    ]

    class FailedShowClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            return _FakeResponse(403, {"error": "denied"})

    _patch_list_and_native(
        monkeypatch,
        FailedShowClient,
        models=[ModelInfo(id=model_id, name=model_id)],
    )
    fetched = await provider.fetch_models()
    assert "max_input_length_auto_detected" not in fetched[0].model_fields_set

    merged = merge_discovered_model(
        provider,
        fetched[0],
        "2026-11-06T01:00:00Z",
    )
    assert merged.max_input_length_auto_detected == 65536


@pytest.mark.asyncio
async def test_failed_ps_then_unknown_show_retains_previous_auto_detected(
    monkeypatch,
) -> None:
    """A failed /api/ps must not clear a prior window via unknown show.

    ps timeout + successful show without num_ctx used to clear 65536 back
    to the 128k default. Clear only when both probes succeed.
    """
    from qwenpaw.providers.provider_discovery import merge_discovered_model

    provider = _make_provider()
    model_id = "qwen3:8b"
    first = ModelInfo(
        id=model_id,
        name=model_id,
        max_input_length_auto_detected=65536,
    )
    provider.discovered_models = [
        merge_discovered_model(provider, first, "2026-11-06T00:00:00Z"),
    ]

    class FailedPsUnknownShowClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            raise TimeoutError("ps timed out")

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            return _FakeResponse(200, {"parameters": "temperature 0.7\n"})

    _patch_list_and_native(
        monkeypatch,
        FailedPsUnknownShowClient,
        models=[ModelInfo(id=model_id, name=model_id)],
    )
    fetched = await provider.fetch_models()
    assert "max_input_length_auto_detected" not in fetched[0].model_fields_set

    merged = merge_discovered_model(
        provider,
        fetched[0],
        "2026-11-06T01:00:00Z",
    )
    assert merged.max_input_length_auto_detected == 65536


@pytest.mark.asyncio
async def test_malformed_ps_entry_then_unknown_show_retains_previous(
    monkeypatch,
) -> None:
    """Invalid /api/ps context_length must not clear a prior window.

    A malformed per-model entry used to be skipped while the overall
    probe stayed ok=True, so a later show without num_ctx cleared 65536
    back to the 128k default.
    """
    from qwenpaw.providers.provider_discovery import merge_discovered_model

    provider = _make_provider()
    model_id = "qwen3:8b"
    first = ModelInfo(
        id=model_id,
        name=model_id,
        max_input_length_auto_detected=65536,
    )
    provider.discovered_models = [
        merge_discovered_model(provider, first, "2026-11-06T00:00:00Z"),
    ]

    class MalformedPsUnknownShowClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(
                200,
                {
                    "models": [
                        {
                            "name": model_id,
                            "model": model_id,
                            "context_length": "invalid",
                        },
                    ],
                },
            )

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            return _FakeResponse(200, {"parameters": "temperature 0.7\n"})

    _patch_list_and_native(
        monkeypatch,
        MalformedPsUnknownShowClient,
        models=[ModelInfo(id=model_id, name=model_id)],
    )
    fetched = await provider.fetch_models()
    assert "max_input_length_auto_detected" not in fetched[0].model_fields_set

    merged = merge_discovered_model(
        provider,
        fetched[0],
        "2026-11-06T01:00:00Z",
    )
    assert merged.max_input_length_auto_detected == 65536


@pytest.mark.asyncio
async def test_malformed_parameters_retains_previous_auto_detected(
    monkeypatch,
) -> None:
    """Non-string parameters must not clear a previously detected window."""
    from qwenpaw.providers.provider_discovery import merge_discovered_model

    provider = _make_provider()
    model_id = "qwen3:8b"
    first = ModelInfo(
        id=model_id,
        name=model_id,
        max_input_length_auto_detected=8192,
    )
    provider.discovered_models = [
        merge_discovered_model(provider, first, "2026-11-06T00:00:00Z"),
    ]

    class MalformedParametersClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            return _FakeResponse(200, {"parameters": {"num_ctx": 8192}})

    _patch_list_and_native(
        monkeypatch,
        MalformedParametersClient,
        models=[ModelInfo(id=model_id, name=model_id)],
    )
    fetched = await provider.fetch_models()
    assert "max_input_length_auto_detected" not in fetched[0].model_fields_set

    merged = merge_discovered_model(
        provider,
        fetched[0],
        "2026-11-06T01:00:00Z",
    )
    assert merged.max_input_length_auto_detected == 8192


@pytest.mark.asyncio
async def test_fetch_models_registry_port_alias_matches_served_context(
    monkeypatch,
) -> None:
    """registry:port/name without a tag still matches /api/ps :latest rows."""
    provider = _make_provider()
    model_id = "registry.example.com:5000/team/qwen3"

    class RegistryPortClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(
                200,
                {
                    "models": [
                        {
                            "name": f"{model_id}:latest",
                            "model": f"{model_id}:latest",
                            "context_length": 32768,
                        },
                    ],
                },
            )

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            assert json == {"model": model_id}
            return _FakeResponse(200, {"parameters": "num_ctx 32768\n"})

    _patch_list_and_native(
        monkeypatch,
        RegistryPortClient,
        models=[ModelInfo(id=model_id, name=model_id)],
    )
    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 32768


@pytest.mark.asyncio
async def test_fetch_models_repeated_cancel_drains_probes_before_aclose(
    monkeypatch,
) -> None:
    """A second cancel during cleanup must not close the client early."""
    provider = _make_provider()
    state = {
        "started": 0,
        "unwound": 0,
        "aclose": 0,
        "aclose_before_unwind": 0,
    }
    started = asyncio.Event()
    unwind_started = asyncio.Event()
    release_unwind = asyncio.Event()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def aclose(self) -> None:
            if state["unwound"] < state["started"]:
                state["aclose_before_unwind"] += 1
            state["aclose"] += 1

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            assert url.endswith("/api/show")
            del json
            state["started"] += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                unwind_started.set()
                await release_unwind.wait()
                state["unwound"] += 1

    _patch_list_and_native(monkeypatch, FakeClient)

    task = asyncio.create_task(provider.fetch_models(timeout=30))
    await started.wait()
    task.cancel()
    await unwind_started.wait()
    for _ in range(2):
        task.cancel()
        await asyncio.sleep(0)
    finished_early = task.done()

    release_unwind.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert finished_early is False
    assert state["started"] == 1
    assert state["unwound"] == 1
    assert state["aclose"] == 1
    assert state["aclose_before_unwind"] == 0
