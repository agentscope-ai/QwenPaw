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
    parse_ollama_num_ctx,
    resolve_ollama_context_window,
)
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.thinking import ThinkingControl


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
    # GGUF *.context_length is the model maximum, not the served window.
    assert (
        resolve_ollama_context_window(
            show_payload={"model_info": {"qwen3.context_length": 65536}},
        )
        == 4096
    )
    assert resolve_ollama_context_window(show_payload={}) == 4096
    # Failed probe is not an empty successful show.
    assert resolve_ollama_context_window(show_payload=None) is None
    assert (
        resolve_ollama_context_window(
            show_payload=None,
            served_context=8192,
        )
        == 8192
    )
    assert (
        resolve_ollama_context_window(
            show_payload={},
            use_conservative_fallback=False,
        )
        is None
    )


def test_resolve_cloud_show_without_num_ctx_skips_4096() -> None:
    """Cloud models keep the default window when show omits num_ctx."""
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
    # Blank markers are not the cloud flag. A local show still uses 4k.
    assert (
        resolve_ollama_context_window(
            show_payload={"remote_host": "  ", "remote_model": ""},
        )
        == 4096
    )
    # Name suffix is only a hint when the payload omitted remote fields.
    assert (
        resolve_ollama_context_window(
            show_payload={},
            model_id="kimi-k3:cloud",
        )
        is None
    )
    assert (
        resolve_ollama_context_window(
            show_payload={"parameters": "temperature 0.7\n"},
            model_id="gpt-oss:120b-cloud",
        )
        is None
    )
    assert (
        resolve_ollama_context_window(
            show_payload={},
            model_id="foo-cloud:latest",
        )
        is None
    )
    assert (
        resolve_ollama_context_window(
            show_payload={},
            model_id="cloud-qwen:latest",
        )
        == 4096
    )
    # Explicit num_ctx and a loaded window still win for cloud models.
    assert (
        resolve_ollama_context_window(
            show_payload={
                "remote_host": "https://ollama.com",
                "parameters": "num_ctx 16384\n",
            },
        )
        == 16384
    )
    assert (
        resolve_ollama_context_window(
            show_payload=remote,
            served_context=32768,
        )
        == 32768
    )


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
            raise AssertionError("/api/show must be skipped when /api/ps wins")

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
    # Loaded /api/ps window is final; /api/show is not called.
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
    # No served window and no num_ctx → conservative 4k, not 128k.
    assert models[0].max_input_length_auto_detected == 4096


@pytest.mark.asyncio
async def test_fetch_models_first_use_conservative_fallback(
    monkeypatch,
) -> None:
    """Unloaded model without num_ctx uses 4k instead of the 128k default."""
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
    assert models[0].max_input_length_auto_detected == 4096


@pytest.mark.asyncio
async def test_fetch_models_cloud_show_without_num_ctx_skips_4096(
    monkeypatch,
) -> None:
    """Unloaded cloud models must not pick up the local 4k fallback."""
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
    # Local unloaded model without num_ctx keeps the 4k estimate.
    assert by_id["qwen3:8b"].max_input_length_auto_detected == 4096


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

        async def get(self, url: str):
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            raise TimeoutError("timed out")

    _patch_list_and_native(monkeypatch, FakeClient)

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_native_probe_deadline_returns_originals(
    monkeypatch,
) -> None:
    """Slow /api/show probes stop at the overall deadline.

    Per-request timeout stays on the client. The batch must not wait out
    every unloaded model.
    """
    provider = _make_provider()
    ids = [f"model-{index}:latest" for index in range(16)]
    listed = [ModelInfo(id=model_id, name=model_id) for model_id in ids]
    started = 0
    finished = 0
    captured: dict = {}
    probe_timeout = 0.5

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url: str):
            assert url.endswith("/api/ps")
            return _FakeResponse(200, {"models": []})

        async def post(self, url: str, json: dict):
            nonlocal started, finished
            del url, json
            started += 1
            await asyncio.sleep(5)
            finished += 1
            return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

    _patch_list_and_native(monkeypatch, FakeClient, listed)

    started_at = time.monotonic()
    models = await provider.fetch_models(timeout=probe_timeout)
    elapsed = time.monotonic() - started_at

    assert models is listed
    assert elapsed < 2.5
    # In-flight /api/show calls are cancelled; none of the slow probes finish.
    assert finished == 0
    assert started > 0
    assert captured["timeout"] == probe_timeout
    assert all(
        model.max_input_length_auto_detected is None for model in models
    )


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
