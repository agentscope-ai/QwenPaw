# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

import qwenpaw.providers.gemini_provider as gemini_provider_module
from qwenpaw.providers.gemini_provider import GeminiProvider


def _make_provider(**overrides) -> GeminiProvider:
    config = {
        "id": "gemini",
        "name": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "api_key": "gem-test",
        "chat_model": "GeminiChatModel",
    }
    config.update(overrides)
    return GeminiProvider(
        **config,
    )


def test_chat_model_configures_persistent_client_headers(monkeypatch) -> None:
    captured: list[dict] = []
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace()),
    )

    def create_client(**kwargs):
        captured.append(kwargs)
        return fake_client

    monkeypatch.setattr(gemini_provider_module.genai, "Client", create_client)

    model = _make_provider(
        custom_headers={"X-QwenPaw-Test": "enabled"},
    ).get_chat_model_instance("gemini-2.5-flash")

    assert model.client is fake_client
    assert len(captured) == 1
    assert captured[0]["http_options"].headers == {
        "X-QwenPaw-Test": "enabled",
    }


async def test_summary_limit_is_adapted_without_mutating_thinking(
    monkeypatch,
) -> None:
    captured: dict = {}

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("provider failed")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(
        gemini_provider_module.genai,
        "Client",
        lambda **kwargs: fake_client,
    )
    model = _make_provider().get_chat_model_instance("gemini-2.5-flash")

    async def fake_format(self, messages):
        del self, messages
        return []

    monkeypatch.setattr(type(model.formatter), "format", fake_format)
    model.parameters.thinking_enable = True

    with pytest.raises(RuntimeError, match="provider failed"):
        await model._call_api(
            "gemini-2.5-flash",
            [],
            max_tokens=256,
            disable_thinking=True,
        )

    config = captured["config"]
    assert config["max_output_tokens"] == 256
    assert "max_tokens" not in config
    assert config["thinking_config"] == {
        "include_thoughts": False,
        "thinking_budget": 0,
    }
    assert model.parameters.thinking_enable is True


async def test_summary_thinking_override_is_concurrency_safe(
    monkeypatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    configs: list[dict] = []

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            configs.append(kwargs["config"])
            if len(configs) == 1:
                started.set()
                await release.wait()
            return _AsyncIter([])

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(
        gemini_provider_module.genai,
        "Client",
        lambda **kwargs: fake_client,
    )
    model = _make_provider().get_chat_model_instance("gemini-2.5-flash")

    async def fake_format(self, messages):
        del self, messages
        return []

    monkeypatch.setattr(type(model.formatter), "format", fake_format)
    model.parameters.thinking_enable = True

    summary_call = asyncio.create_task(
        model._call_api(
            "gemini-2.5-flash",
            [],
            disable_thinking=True,
        ),
    )
    await started.wait()
    normal_call = await model._call_api("gemini-2.5-flash", [])
    release.set()
    await summary_call

    assert normal_call is not None
    assert configs[0]["thinking_config"]["include_thoughts"] is False
    assert configs[1]["thinking_config"]["include_thoughts"] is True
    assert model.parameters.thinking_enable is True


class _AsyncIter:
    """Helper that turns a list into an async iterator."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


# -- check_connection --------------------------------------------------------


async def test_check_connection_success(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            return _AsyncIter(
                [SimpleNamespace(name="models/gemini-2.5-flash")],
            )

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=2.0)

    assert ok is True
    assert msg == ""


async def test_check_connection_api_error_returns_false(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise genai_errors.APIError(403, {"error": "forbidden"})

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=1.0)

    assert ok is False
    assert "Failed to connect to Google Gemini API" in msg


async def test_check_connection_generic_exception_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise ConnectionError("DNS resolution failed")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=1.0)

    assert ok is False
    assert "Unknown exception" in msg


# -- fetch_models ------------------------------------------------------------


async def test_fetch_models_normalizes_and_deduplicates(monkeypatch) -> None:
    provider = _make_provider()
    rows = [
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
        ),
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="duplicate",
        ),
        SimpleNamespace(
            name="models/gemini-2.5-pro",
            display_name="",
        ),
        SimpleNamespace(name="   ", display_name="invalid"),
    ]

    class FakeModels:
        async def list(self):
            return _AsyncIter(rows)

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3.0)

    assert [m.id for m in models] == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert [m.name for m in models] == ["Gemini 2.5 Flash", "gemini-2.5-pro"]
    assert not provider.models


async def test_fetch_models_api_error_returns_empty(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise genai_errors.APIError(500, {"error": "internal"})

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3.0)

    assert models == []


async def test_fetch_models_generic_exception_returns_empty(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise OSError("network unreachable")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3.0)

    assert models == []


# -- check_model_connection ---------------------------------------------------


async def test_check_model_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    captured: list[dict] = []

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            captured.append(kwargs)
            return _AsyncIter([])

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection(
        "gemini-2.5-flash",
        timeout=4.0,
    )

    assert ok is True
    assert msg == ""
    assert len(captured) == 1
    assert captured[0]["model"] == "gemini-2.5-flash"
    assert captured[0]["contents"] == "ping"


async def test_check_model_connection_empty_model_id_returns_false() -> None:
    provider = _make_provider()

    ok, msg = await provider.check_model_connection("   ", timeout=4.0)

    assert ok is False
    assert msg == "Empty model ID"


async def test_check_model_connection_api_error_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            raise genai_errors.APIError(404, {"error": "not found"})

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection(
        "gemini-2.5-flash",
        timeout=4.0,
    )

    assert ok is False
    assert "not reachable or usable" in msg


async def test_check_model_connection_generic_exception_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            raise TimeoutError("connection timed out")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection(
        "gemini-2.5-flash",
        timeout=4.0,
    )

    assert ok is False
    assert "Unknown exception" in msg


# -- _normalize_models_payload ------------------------------------------------


def test_normalize_models_strips_prefix_and_deduplicates() -> None:
    rows = [
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
        ),
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="dup",
        ),
        SimpleNamespace(
            name="gemini-2.0-flash",
            display_name="No Prefix",
        ),
    ]

    models = GeminiProvider._normalize_models_payload(rows)

    assert [m.id for m in models] == ["gemini-2.5-flash", "gemini-2.0-flash"]
    assert [m.name for m in models] == [
        "Gemini 2.5 Flash",
        "No Prefix",
    ]


def test_normalize_models_empty_and_none() -> None:
    assert not GeminiProvider._normalize_models_payload(None)
    assert not GeminiProvider._normalize_models_payload([])


def test_normalize_models_display_name_with_models_prefix() -> None:
    rows = [
        SimpleNamespace(
            name="models/gemini-2.5-pro",
            display_name="models/gemini-2.5-pro",
        ),
    ]

    models = GeminiProvider._normalize_models_payload(rows)

    assert models[0].id == "gemini-2.5-pro"
    assert models[0].name == "gemini-2.5-pro"


# -- _sanitize_schema_for_gemini --------------------------------------------


def test_sanitize_replaces_standalone_null_type() -> None:
    from qwenpaw.providers.gemini_provider import _sanitize_schema_for_gemini

    schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "null"},
            "command": {"type": "string"},
        },
    }
    result = _sanitize_schema_for_gemini(schema)
    assert result["properties"]["cwd"] == {"type": "object"}
    assert result["properties"]["command"] == {"type": "string"}


def test_sanitize_handles_anyOf_with_null() -> None:
    from qwenpaw.providers.gemini_provider import _sanitize_schema_for_gemini

    schema = {
        "type": "object",
        "properties": {
            "cwd": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            },
        },
    }
    result = _sanitize_schema_for_gemini(schema)
    assert result["properties"]["cwd"] == {"type": "string"}


def test_sanitize_handles_anyOf_with_annotated_null() -> None:
    from qwenpaw.providers.gemini_provider import _sanitize_schema_for_gemini

    schema = {
        "type": "object",
        "properties": {
            "cwd": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null", "title": "None"},
                ],
            },
        },
    }
    result = _sanitize_schema_for_gemini(schema)
    assert result["properties"]["cwd"] == {"type": "string"}


def test_sanitize_nested_standalone_null() -> None:
    from qwenpaw.providers.gemini_provider import _sanitize_schema_for_gemini

    schema = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "properties": {
                    "timeout": {"type": "null"},
                },
            },
        },
    }
    result = _sanitize_schema_for_gemini(schema)
    assert result["properties"]["config"]["properties"]["timeout"] == {
        "type": "object",
    }


def test_sanitize_removes_additional_properties() -> None:
    from qwenpaw.providers.gemini_provider import _sanitize_schema_for_gemini

    schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {},
    }
    result = _sanitize_schema_for_gemini(schema)
    assert "additionalProperties" not in result


def test_sanitize_all_null_anyOf_becomes_object() -> None:
    from qwenpaw.providers.gemini_provider import _sanitize_schema_for_gemini

    schema = {
        "anyOf": [{"type": "null"}, {"type": "null"}],
    }
    result = _sanitize_schema_for_gemini(schema)
    assert "anyOf" not in result


def test_format_tools_strips_schema_metadata_before_sdk_validation() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search for a query.",
                "parameters": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "object",
                    "properties": {
                        "query": {
                            "$schema": (
                                "http://json-schema.org/draft-07/schema#"
                            ),
                            "type": "string",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]
    original_tools = copy.deepcopy(tools)

    model = _make_provider().get_chat_model_instance("gemini-2.5-flash")
    formatted_tools, tool_config = model._format_tools(tools, None)

    config = genai_types.GenerateContentConfig(tools=formatted_tools)
    assert tool_config is None
    assert config.tools is not None
    assert formatted_tools == [
        {
            "function_declarations": [
                {
                    "name": "search",
                    "description": "Search for a query.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            ],
        },
    ]
    assert tools == original_tools


# -- update_config ------------------------------------------------------------


async def test_update_config_updates_non_none_values() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "name": "Gemini Custom",
            "base_url": "https://new.example",
            "api_key": "gem-new",
            "chat_model": "GeminiChatModel",
            "api_key_prefix": "gem-",
            "generate_kwargs": {"temperature": 0.5},
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.name == "Gemini Custom"
    assert provider.api_key == "gem-new"
    assert provider.generate_kwargs == {"temperature": 0.5}
    assert info.name == "Gemini Custom"
    assert info.api_key == "gem-new"


async def test_update_config_skips_none_values() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "name": None,
            "api_key": None,
        },
    )

    assert provider.name == "Gemini"
    assert provider.api_key == "gem-test"
