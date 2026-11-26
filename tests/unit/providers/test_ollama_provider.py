# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from agentscope.model import OpenAIChatModel
import pytest

from qwenpaw.providers.ollama_discovery import (
    _parse_positive_context_int,
    classify_ollama_show_payload,
    parse_ollama_model_training_context,
    parse_ollama_num_ctx,
    resolve_ollama_context_window,
)
from qwenpaw.providers.ollama_provider import OllamaProvider
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.provider_discovery import (
    apply_discovery_metadata,
    merge_discovered_model,
)
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
    # Unicode "digits" and overlong ASCII strings must not raise.
    assert parse_ollama_num_ctx("num_ctx ²") is None
    assert parse_ollama_num_ctx("num_ctx " + "1" * 19) is None
    assert parse_ollama_num_ctx("num_ctx " + "1" * 4300) is None


def test_parse_positive_context_int_is_strict() -> None:
    assert _parse_positive_context_int(65536) == 65536
    assert _parse_positive_context_int(512) == 512
    # model_info values are JSON numbers; strings are not accepted.
    assert _parse_positive_context_int("8192") is None
    assert _parse_positive_context_int(" 4096 ") is None
    assert _parse_positive_context_int("²") is None
    # Bools are ints; do not coerce True to 1.
    assert _parse_positive_context_int(True) is None
    assert _parse_positive_context_int(False) is None
    # Floats must not be truncated into a context length.
    assert _parse_positive_context_int(8192.0) is None
    assert _parse_positive_context_int(12.5) is None
    assert _parse_positive_context_int(0) is None
    assert _parse_positive_context_int(-1) is None
    assert _parse_positive_context_int("invalid") is None
    assert _parse_positive_context_int("8192.0") is None
    assert _parse_positive_context_int({"value": 8192}) is None
    assert _parse_positive_context_int(None) is None


def test_parse_ollama_model_training_context() -> None:
    assert parse_ollama_model_training_context(None) is None
    assert parse_ollama_model_training_context([]) is None
    assert parse_ollama_model_training_context("32768") is None
    # Only general.architecture + ".context_length". Do not take the
    # minimum, and do not fall back to a bare context_length key.
    assert (
        parse_ollama_model_training_context(
            {
                "general.architecture": "qwen3",
                "qwen3.context_length": 32768,
                "context_length": 16384,
                "llama.context_length": 65536,
            },
        )
        == 32768
    )
    # Architecture names are stripped; string lengths are not JSON numbers.
    assert (
        parse_ollama_model_training_context(
            {
                "general.architecture": "  qwen3  ",
                "qwen3.context_length": 32768,
            },
        )
        == 32768
    )
    assert (
        parse_ollama_model_training_context(
            {
                "general.architecture": "  qwen3  ",
                "qwen3.context_length": "32768",
            },
        )
        is None
    )
    missing_architecture = (
        {"qwen3.context_length": 32768},
        {"general.architecture": "", "qwen3.context_length": 32768},
        {"general.architecture": "   ", "qwen3.context_length": 32768},
        {"general.architecture": 1, "qwen3.context_length": 32768},
        {"general.architecture": None, "qwen3.context_length": 32768},
        {"general.architecture": "qwen3"},
    )
    for model_info in missing_architecture:
        assert parse_ollama_model_training_context(model_info) is None
    for raw in (0, True, False, 32768.0, 12.5, "nope", "8192.0", -1, "32768"):
        assert (
            parse_ollama_model_training_context(
                {
                    "general.architecture": "qwen3",
                    "qwen3.context_length": raw,
                },
            )
            is None
        )


def test_classify_ollama_show_payload() -> None:
    assert classify_ollama_show_payload(None) == ("failed", None)
    assert classify_ollama_show_payload("not-a-dict") == ("failed", None)
    assert classify_ollama_show_payload(
        {"parameters": {"num_ctx": 8192}},
    ) == ("malformed", None)
    assert classify_ollama_show_payload(
        {"parameters": None},
    ) == ("malformed", None)
    assert classify_ollama_show_payload({}) == ("unknown", None)
    assert classify_ollama_show_payload(
        {"parameters": "temperature 0.7\n"},
    ) == ("unknown", None)
    assert classify_ollama_show_payload(
        {"parameters": "num_ctx 8192\n"},
    ) == ("resolved", 8192)


def test_resolve_ollama_context_uses_modelfile_num_ctx() -> None:
    show = {
        "parameters": "num_ctx 131072\n",
        "model_info": {
            "general.architecture": "qwen3",
            "qwen3.context_length": 262144,
        },
    }
    # A higher training cap does not raise the Modelfile window.
    assert resolve_ollama_context_window(show) == 131072
    # Training context alone is not a window.
    assert (
        resolve_ollama_context_window(
            {
                "model_info": {
                    "general.architecture": "qwen3",
                    "qwen3.context_length": 65536,
                },
            },
        )
        is None
    )
    assert resolve_ollama_context_window({}) is None


def test_resolve_show_without_num_ctx_leaves_context_unset() -> None:
    """Cloud and local shows without num_ctx stay unset.

    Inventing 4096 is unsafe when OLLAMA_CONTEXT_LENGTH may be below 4096.
    """
    remote = {
        "remote_host": "https://ollama.com",
        "remote_model": "gpt-oss:120b",
        "model_info": {"gptoss.context_length": 131072},
    }
    assert resolve_ollama_context_window(remote) is None
    assert (
        resolve_ollama_context_window(
            {"remote_host": "https://ollama.com"},
        )
        is None
    )
    assert resolve_ollama_context_window({"remote_model": "gemma4"}) is None
    # Blank remote markers are not a window.
    assert (
        resolve_ollama_context_window(
            {"remote_host": "  ", "remote_model": ""},
        )
        is None
    )
    # A local show that omitted num_ctx stays unset too.
    assert (
        resolve_ollama_context_window(
            {"parameters": "temperature 0.7\n"},
        )
        is None
    )
    # Explicit num_ctx still wins.
    assert (
        resolve_ollama_context_window(
            {
                "remote_host": "https://ollama.com",
                "parameters": "num_ctx 16384\n",
            },
        )
        == 16384
    )


def test_resolve_caps_num_ctx_by_training_context() -> None:
    """Ollama clamps NumCtx to the architecture training context.

    A 32K model with Modelfile ``num_ctx 65536`` is served at 32768.
    Persisting the raw Modelfile value would disagree with that runner.
    The cap is ``general.architecture + ".context_length"`` only.
    """
    show = {
        "parameters": "num_ctx 65536\n",
        "model_info": {
            "general.architecture": "qwen3",
            "qwen3.context_length": 32768,
        },
    }
    assert resolve_ollama_context_window(show) == 32768
    # Sibling keys do not replace the architecture cap.
    assert (
        resolve_ollama_context_window(
            {
                "parameters": "num_ctx 65536\n",
                "model_info": {
                    "general.architecture": "qwen3",
                    "qwen3.context_length": 32768,
                    "context_length": 16384,
                    "llama.context_length": 65536,
                },
            },
        )
        == 32768
    )

    # 0 / missing / invalid context_length is not a cap.
    no_cap_payloads: list[dict[str, Any]] = [
        {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": 0,
            },
        },
        {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": True,
            },
        },
        {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": 32768.0,
            },
        },
        {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": "nope",
            },
        },
        {"parameters": "num_ctx 65536\n", "model_info": {}},
        {"parameters": "num_ctx 65536\n"},
        {"parameters": "num_ctx 65536\n", "model_info": "32768"},
        {
            "parameters": "num_ctx 65536\n",
            "model_info": {"qwen3.context_length": 32768},
        },
        {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": " ",
                "qwen3.context_length": 32768,
            },
        },
    ]
    for payload in no_cap_payloads:
        assert resolve_ollama_context_window(payload) == 65536

    # Training max alone is not a window.
    assert (
        resolve_ollama_context_window(
            {
                "model_info": {
                    "general.architecture": "qwen3",
                    "qwen3.context_length": 32768,
                },
            },
        )
        is None
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
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def _show_client(
    *,
    payload: dict[str, Any] | None = None,
    payloads: dict[str, dict[str, Any]] | None = None,
    status_code: int = 200,
    post_error: BaseException | None = None,
    on_post: Callable | None = None,
    on_init: Callable | None = None,
    requested: list[str] | None = None,
) -> type:
    """Build a shared ``/api/show`` stand-in for ``fetch_models`` tests."""

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args
            if on_init is not None:
                on_init(kwargs)

        async def aclose(self) -> None:
            return None

        async def get(self, url: str):
            raise AssertionError(f"unexpected GET {url}")

        async def post(self, url: str, json: dict):
            if requested is not None:
                requested.append(url)
            if on_post is not None:
                return await on_post(url, json)
            assert url.endswith("/api/show")
            if post_error is not None:
                raise post_error
            if payloads is not None:
                body = payloads[json["model"]]
            elif payload is not None:
                body = payload
            else:
                body = {"error": "denied"}
            return _FakeResponse(status_code, body)

    return FakeClient


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
        "qwenpaw.providers.ollama_discovery.httpx.AsyncClient",
        client_cls,
    )


def _listed(*model_ids: str) -> list[ModelInfo]:
    return [ModelInfo(id=model_id, name=model_id) for model_id in model_ids]


@pytest.mark.asyncio
async def test_fetch_models_attaches_show_num_ctx(monkeypatch) -> None:
    """Attach Modelfile ``num_ctx`` from ``/api/show``."""
    provider = _make_provider()
    requested: list[str] = []

    _patch_list_and_native(
        monkeypatch,
        _show_client(
            payload={"parameters": "num_ctx 4096\n"},
            requested=requested,
        ),
    )

    models = await provider.fetch_models()
    assert len(models) == 1
    assert models[0].max_input_length_auto_detected == 4096
    assert requested == [f"{provider.base_url}/api/show"]


@pytest.mark.asyncio
async def test_fetch_models_ignores_chat_num_ctx_and_uses_clamped_show(
    monkeypatch,
) -> None:
    """Chat ``options.num_ctx`` must not skip probes or be persisted.

    The OpenAI-compatible chat path cannot set Ollama's context size.
    The window is the Modelfile ``num_ctx`` clamped to the architecture
    training context.
    """
    provider = _make_provider()
    provider.generate_kwargs = {"options": {"num_ctx": 131072}}
    calls = {"show": 0}

    async def on_post(url: str, json: dict):
        del json
        assert url.endswith("/api/show")
        calls["show"] += 1
        return _FakeResponse(
            200,
            {
                "parameters": "num_ctx 65536\n",
                "model_info": {
                    "general.architecture": "qwen3",
                    "qwen3.context_length": 32768,
                },
            },
        )

    _patch_list_and_native(monkeypatch, _show_client(on_post=on_post))
    models = await provider.fetch_models()
    assert calls == {"show": 1}
    assert models[0].max_input_length_auto_detected == 32768


@pytest.mark.asyncio
async def test_fetch_models_model_chat_num_ctx_does_not_skip_probes(
    monkeypatch,
) -> None:
    """Per-model ``options.num_ctx`` is not a window and does not skip probes.

    A show with no Modelfile ``num_ctx`` leaves the window unset. Training
    context is not used as the window either.
    """
    provider = _make_provider()
    provider.generate_kwargs = {"options": {"num_ctx": 8192}}
    provider.models = [
        ModelInfo(
            id="qwen3:8b",
            name="qwen3:8b",
            generate_kwargs={"options": {"num_ctx": 16384}},
        ),
    ]
    calls = {"show": 0}

    async def on_post(url: str, json: dict):
        del json
        assert url.endswith("/api/show")
        calls["show"] += 1
        return _FakeResponse(
            200,
            {
                "model_info": {
                    "general.architecture": "qwen3",
                    "qwen3.context_length": 32768,
                },
            },
        )

    _patch_list_and_native(monkeypatch, _show_client(on_post=on_post))
    models = await provider.fetch_models()
    assert calls == {"show": 1}
    assert models[0].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_uses_modelfile_num_ctx(monkeypatch) -> None:
    """Persist an explicit Modelfile ``num_ctx`` when no training cap applies."""
    provider = _make_provider()
    _patch_list_and_native(
        monkeypatch,
        _show_client(
            payload={
                "parameters": "num_ctx 8192\n",
                "model_info": {"qwen3.context_length": 131072},
            },
        ),
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 8192


@pytest.mark.asyncio
async def test_fetch_models_caps_num_ctx_by_training_context(
    monkeypatch,
) -> None:
    """Persist the clamped Modelfile window, not the raw ``num_ctx``.

    Ollama serves ``min(num_ctx, architecture training context)``.
    """
    provider = _make_provider()
    clamped_id = "clamped:latest"
    other_id = "other:latest"
    zero_id = "zero-cap:latest"
    missing_id = "missing-cap:latest"
    invalid_id = "invalid-cap:latest"
    info_only_id = "info-only:latest"
    listed = _listed(
        clamped_id,
        other_id,
        zero_id,
        missing_id,
        invalid_id,
        info_only_id,
    )
    shows: dict[str, dict[str, Any]] = {
        clamped_id: {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": 32768,
                "context_length": 16384,
                "llama.context_length": 65536,
            },
        },
        other_id: {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": 32768,
            },
        },
        zero_id: {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": 0,
            },
        },
        missing_id: {"parameters": "num_ctx 65536\n"},
        invalid_id: {
            "parameters": "num_ctx 65536\n",
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": "nope",
            },
        },
        info_only_id: {
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": 32768,
            },
        },
    }

    _patch_list_and_native(
        monkeypatch,
        _show_client(payloads=shows),
        listed,
    )
    models = await provider.fetch_models()
    by_id = {model.id: model for model in models}
    assert by_id[clamped_id].max_input_length_auto_detected == 32768
    assert by_id[other_id].max_input_length_auto_detected == 32768
    assert by_id[zero_id].max_input_length_auto_detected == 65536
    assert by_id[missing_id].max_input_length_auto_detected == 65536
    assert by_id[invalid_id].max_input_length_auto_detected == 65536
    assert by_id[info_only_id].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_ignores_gguf_context_length(monkeypatch) -> None:
    provider = _make_provider()
    _patch_list_and_native(
        monkeypatch,
        _show_client(
            payload={"model_info": {"qwen3.context_length": 131072}},
        ),
    )

    models = await provider.fetch_models()
    # model_info alone is not a window.
    assert models[0].max_input_length_auto_detected is None
    assert "max_input_length_auto_detected" in models[0].model_fields_set


@pytest.mark.asyncio
async def test_fetch_models_local_show_without_num_ctx_leaves_context_unset(
    monkeypatch,
) -> None:
    """A local model without num_ctx must not invent a fallback window.

    Inventing 4096 is unsafe when OLLAMA_CONTEXT_LENGTH may be below 4096.
    """
    provider = _make_provider()
    _patch_list_and_native(
        monkeypatch,
        _show_client(payload={"parameters": "temperature 0.7\n"}),
        _listed("fresh:latest"),
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected is None
    assert "max_input_length_auto_detected" in models[0].model_fields_set


@pytest.mark.asyncio
async def test_fetch_models_cloud_show_without_num_ctx_leaves_context_unset(
    monkeypatch,
) -> None:
    """Shows without num_ctx stay unset for cloud and local models."""
    provider = _make_provider()
    listed = _listed(
        "gpt-oss:120b",
        "kimi-k3:cloud",
        "gemma4:cloud",
        "qwen3:8b",
    )
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

    _patch_list_and_native(
        monkeypatch,
        _show_client(payloads=payloads),
        listed,
    )

    models = await provider.fetch_models()
    by_id = {model.id: model for model in models}
    # remote_* is authoritative; GGUF context_length is not a window.
    assert by_id["gpt-oss:120b"].max_input_length_auto_detected is None
    # :cloud suffix when show omitted remote_* and num_ctx.
    assert by_id["kimi-k3:cloud"].max_input_length_auto_detected is None
    # Explicit num_ctx still wins on a cloud model.
    assert by_id["gemma4:cloud"].max_input_length_auto_detected == 16384
    # Local model without num_ctx stays unset.
    assert by_id["qwen3:8b"].max_input_length_auto_detected is None


@pytest.mark.asyncio
async def test_fetch_models_accepts_small_num_ctx(monkeypatch) -> None:
    provider = _make_provider()
    _patch_list_and_native(
        monkeypatch,
        _show_client(payload={"parameters": "num_ctx 512\n"}),
        _listed("tiny:latest"),
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

    def on_init(kwargs: dict) -> None:
        captured["headers"] = kwargs.get("headers")
        captured["timeout"] = kwargs.get("timeout")

    async def on_post(url: str, json: dict):
        captured["post_url"] = url
        captured["post_json"] = json
        return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

    _patch_list_and_native(
        monkeypatch,
        _show_client(on_init=on_init, on_post=on_post),
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected == 8192
    assert captured["post_url"].endswith("/api/show")
    assert captured["headers"]["X-Proxy-Token"] == "abc"
    assert captured["headers"]["Authorization"] == "Bearer sk-remote-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_fetch_models_show_auth_failure_leaves_context_unset(
    monkeypatch,
    status_code: int,
) -> None:
    """401/403 on /api/show must leave the previous window in place."""
    provider = _make_provider()
    _patch_list_and_native(
        monkeypatch,
        _show_client(status_code=status_code),
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected is None
    assert "max_input_length_auto_detected" not in models[0].model_fields_set


@pytest.mark.asyncio
async def test_fetch_models_show_timeout_leaves_context_unset(
    monkeypatch,
) -> None:
    """A timed-out /api/show leaves the 128k default in place."""
    provider = _make_provider()
    _patch_list_and_native(
        monkeypatch,
        _show_client(post_error=TimeoutError("timed out")),
    )

    models = await provider.fetch_models()
    assert models[0].max_input_length_auto_detected is None
    assert "max_input_length_auto_detected" not in models[0].model_fields_set


@pytest.mark.asyncio
async def test_fetch_models_deadline_keeps_completed_probes(
    monkeypatch,
) -> None:
    """A slow ``/api/show`` must not discard probes that already finished.

    HTTPX's per-call timeout does not bound total response time. The
    shared wall-clock deadline cancels unfinished shows. A show that
    returns in time is kept. Unfinished models stay unset, and the
    pre-enrichment list is not returned.
    """
    provider = _make_provider()
    loaded_id = "loaded:latest"
    fast_id = "fast:latest"
    slow_ids = [f"slow-{index}:latest" for index in range(6)]
    listed = _listed(loaded_id, fast_id, *slow_ids)
    started_slow = 0
    finished_slow = 0
    show_ids: list[str] = []
    captured: dict = {}
    probe_timeout = 0.5

    def on_init(kwargs: dict) -> None:
        captured["timeout"] = kwargs.get("timeout")

    async def on_post(url: str, json: dict):
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

    _patch_list_and_native(
        monkeypatch,
        _show_client(on_init=on_init, on_post=on_post),
        listed,
    )

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
        assert (
            "max_input_length_auto_detected"
            not in by_id[model_id].model_fields_set
        )


@pytest.mark.asyncio
async def test_fetch_models_malformed_parameters_does_not_abort_batch(
    monkeypatch,
) -> None:
    """A non-string ``parameters`` value leaves only that model unset."""
    provider = _make_provider()
    listed = _listed("bad:latest", "good:latest")
    payloads: dict[str, dict[str, Any]] = {
        "bad:latest": {"parameters": {"num_ctx": 8192}},
        "good:latest": {"parameters": "num_ctx 8192\n"},
    }

    _patch_list_and_native(
        monkeypatch,
        _show_client(payloads=payloads),
        listed,
    )

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

        async def post(self, url: str, json: dict):
            del url, json
            return _FakeResponse(200, {"parameters": "num_ctx 8192\n"})

    async def spy_run_sync_io(operation, /, *args, **kwargs):
        calls["sync"] += 1
        captured["operation"] = operation
        return await run_sync_io(operation, *args, **kwargs)

    _patch_list_and_native(monkeypatch, FakeClient)
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_discovery.run_sync_io",
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
        return _listed("qwen3:8b", "other:latest")

    def boom(*args, **kwargs):
        del args, kwargs
        calls["native"] += 1
        raise AssertionError("connection check must not construct a client")

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fake_super_fetch,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ollama_discovery.httpx.AsyncClient",
        boom,
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


def _seed_discovered_window(
    provider: OllamaProvider,
    model_id: str,
    window: int,
) -> None:
    first = ModelInfo(
        id=model_id,
        name=model_id,
        max_input_length_auto_detected=window,
    )
    provider.discovered_models = [
        merge_discovered_model(provider, first, "2026-11-06T00:00:00Z"),
    ]


@pytest.mark.asyncio
async def test_successful_unknown_context_clears_stale_auto_detected(
    monkeypatch,
) -> None:
    """Successful show without num_ctx must clear a prior auto-detected value.

    Failed probes omit the field so merge keeps the old window; a successful
    probe that no longer reports context must not retain a stale 65536.
    """
    provider = _make_provider()
    model_id = "qwen3:8b"
    _seed_discovered_window(provider, model_id, 65536)
    assert (
        provider.discovered_models[0].max_input_length_auto_detected == 65536
    )

    _patch_list_and_native(
        monkeypatch,
        _show_client(payload={"parameters": "temperature 0.7\n"}),
        models=_listed(model_id),
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
    provider = _make_provider()
    model_id = "qwen3:8b"
    _seed_discovered_window(provider, model_id, 65536)

    _patch_list_and_native(
        monkeypatch,
        _show_client(status_code=403),
        models=_listed(model_id),
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
    provider = _make_provider()
    model_id = "qwen3:8b"
    _seed_discovered_window(provider, model_id, 8192)

    _patch_list_and_native(
        monkeypatch,
        _show_client(payload={"parameters": {"num_ctx": 8192}}),
        models=_listed(model_id),
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
async def test_null_parameters_retains_previous_auto_detected(
    monkeypatch,
) -> None:
    """Explicit parameters: null must keep a previously detected window."""
    provider = _make_provider()
    model_id = "qwen3:8b"
    _seed_discovered_window(provider, model_id, 8192)

    _patch_list_and_native(
        monkeypatch,
        _show_client(payload={"parameters": None}),
        models=_listed(model_id),
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
async def test_omitted_parameters_clears_stale_auto_detected(
    monkeypatch,
) -> None:
    """A successful show that omits parameters must clear a stale window."""
    provider = _make_provider()
    model_id = "qwen3:8b"
    _seed_discovered_window(provider, model_id, 8192)

    _patch_list_and_native(
        monkeypatch,
        _show_client(
            payload={"model_info": {"general.architecture": "qwen3"}},
        ),
        models=_listed(model_id),
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


def test_apply_discovery_metadata_clears_stale_auto_detected() -> None:
    """Successful unknown context must clear configured auto-detected values."""
    provider = _make_provider()
    configured = ModelInfo(
        id="qwen3:8b",
        name="qwen3:8b",
        max_input_length_auto_detected=65536,
    )
    provider.models = [configured]
    fetched = ModelInfo(
        id="qwen3:8b",
        name="qwen3:8b",
        max_input_length_auto_detected=None,
    )
    assert "max_input_length_auto_detected" in fetched.model_fields_set

    apply_discovery_metadata(provider, [fetched], "2026-11-12T00:00:00Z")
    assert configured.max_input_length_auto_detected is None


def test_apply_discovery_metadata_clear_respects_config_overrides() -> None:
    provider = _make_provider()
    configured = ModelInfo(
        id="qwen3:8b",
        name="qwen3:8b",
        max_input_length_auto_detected=65536,
        config_overrides=["max_input_length_auto_detected"],
    )
    provider.models = [configured]
    fetched = ModelInfo(
        id="qwen3:8b",
        name="qwen3:8b",
        max_input_length_auto_detected=None,
    )

    apply_discovery_metadata(provider, [fetched], "2026-11-12T00:00:00Z")
    assert configured.max_input_length_auto_detected == 65536


def test_apply_discovery_metadata_omitted_field_keeps_previous() -> None:
    """Failed probes omit the field; apply must not treat that as a clear."""
    provider = _make_provider()
    configured = ModelInfo(
        id="qwen3:8b",
        name="qwen3:8b",
        max_input_length_auto_detected=65536,
    )
    provider.models = [configured]
    fetched = ModelInfo(id="qwen3:8b", name="qwen3:8b")
    assert "max_input_length_auto_detected" not in fetched.model_fields_set

    apply_discovery_metadata(provider, [fetched], "2026-11-12T00:00:00Z")
    assert configured.max_input_length_auto_detected == 65536


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
