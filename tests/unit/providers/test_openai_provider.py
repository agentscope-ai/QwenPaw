# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

import copaw.providers.openai_provider as openai_provider_module
from copaw.providers.openai_provider import OpenAIProvider


def _make_provider(is_custom: bool = False) -> OpenAIProvider:
    return OpenAIProvider(
        id="openai",
        name="OpenAI",
        base_url="https://mock-openai.local/v1",
        api_key="sk-test",
        is_custom=is_custom,
        chat_model="OpenAIChatModel",
    )


async def test_check_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    calls: list[float | None] = []

    class FakeModels:
        async def list(self, timeout=None):
            calls.append(timeout)
            return SimpleNamespace(data=[])

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=2.5)

    assert ok is True
    assert msg == ""
    assert calls == [2.5]


async def test_check_connection_api_error_returns_false(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self, timeout=None):
            raise RuntimeError("boom")

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)
    monkeypatch.setattr(openai_provider_module, "APIError", Exception)

    ok, msg = await provider.check_connection(timeout=1)

    assert ok is False
    assert msg == f"API error when connecting to `{provider.base_url}`"


async def test_list_model_normalizes_and_deduplicates(monkeypatch) -> None:
    provider = _make_provider()
    rows = [
        SimpleNamespace(id="gpt-4o-mini", name="GPT-4o Mini"),
        SimpleNamespace(id="gpt-4o-mini", name="dup"),
        SimpleNamespace(id="gpt-4.1", name=""),
        SimpleNamespace(id="   ", name="invalid"),
    ]

    class FakeModels:
        async def list(self, timeout=None):
            _ = timeout
            return SimpleNamespace(data=rows)

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3)

    assert [m.id for m in models] == ["gpt-4o-mini", "gpt-4.1"]
    assert [m.name for m in models] == ["GPT-4o Mini", "gpt-4.1"]
    assert provider.models == []  # should not update provider state


async def test_list_model_api_error_returns_empty(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self, timeout=None):
            raise RuntimeError("failed")

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)
    monkeypatch.setattr(openai_provider_module, "APIError", Exception)

    models = await provider.fetch_models(timeout=3)

    assert models == []


async def test_check_model_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    captured: list[dict] = []

    class FakeStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.append(kwargs)
            return FakeStream()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection("gpt-4o-mini", timeout=4)

    assert ok is True
    assert msg == ""
    assert len(captured) == 1
    assert captured[0]["model"] == "gpt-4o-mini"
    assert captured[0]["timeout"] == 4
    assert captured[0]["max_tokens"] == 1
    assert captured[0]["stream"] is True


async def test_check_model_connection_api_error_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeCompletions:
        async def create(self, **kwargs):
            _ = kwargs
            raise RuntimeError("failed")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)
    monkeypatch.setattr(openai_provider_module, "APIError", Exception)

    ok, msg = await provider.check_model_connection("gpt-4o-mini", timeout=4)

    assert ok is False
    assert msg == "API error when connecting to model 'gpt-4o-mini'"


async def test_update_config_updates_non_none_values_and_get_info() -> None:
    provider = _make_provider(is_custom=True)

    provider.update_config(
        {
            "name": "OpenAI Custom",
            "base_url": "https://new.example/v1",
            "api_key": "sk-new",
            "chat_model": "OpenAIChatModel",
            "api_key_prefix": "sk-",
            "generate_kwargs": {"temperature": 0.2, "top_p": 0.9},
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.name == "OpenAI Custom"
    assert provider.base_url == "https://new.example/v1"
    assert provider.api_key == "sk-new"
    assert provider.chat_model == "OpenAIChatModel"
    assert provider.api_key_prefix == "sk-"
    assert provider.generate_kwargs == {"temperature": 0.2, "top_p": 0.9}
    assert info.name == "OpenAI Custom"
    assert info.base_url == "https://new.example/v1"
    assert info.api_key == "sk-new"
    assert info.chat_model == "OpenAIChatModel"
    assert info.api_key_prefix == "sk-"
    assert info.generate_kwargs == {"temperature": 0.2, "top_p": 0.9}
    assert info.is_custom
    assert not info.support_connection_check


async def test_update_config_skips_none_values() -> None:  # noqa: E501
    provider = _make_provider()
    provider.api_key_prefix = "sk-"
    provider.generate_kwargs = {"temperature": 0.1}

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

    assert provider.name == "OpenAI"
    assert provider.base_url == "https://mock-openai.local/v1"
    assert provider.api_key == "sk-test"
    assert provider.chat_model == "OpenAIChatModel"
    assert provider.api_key_prefix == "sk-"
    assert provider.generate_kwargs == {"temperature": 0.1}
    assert info.name == "OpenAI"
    assert info.base_url == "https://mock-openai.local/v1"
    assert info.api_key == "sk-******"
    assert info.chat_model == "OpenAIChatModel"
    assert info.api_key_prefix == "sk-"
    assert info.generate_kwargs == {"temperature": 0.1}


async def test_update_config_does_not_update_chat_model() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "chat_model": "AnotherChatModel",
            "name": "OpenAI Updated",
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.name == "OpenAI Updated"
    assert provider.chat_model == "OpenAIChatModel"
    assert info.name == "OpenAI Updated"
    assert info.chat_model == "OpenAIChatModel"


async def test_update_config_updates_chat_model_for_custom_provider() -> None:
    provider = _make_provider()
    provider.is_custom = True

    provider.update_config(
        {
            "chat_model": "AnotherChatModel",
            "name": "Custom OpenAI",
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.name == "Custom OpenAI"
    assert provider.chat_model == "AnotherChatModel"
    assert info.name == "Custom OpenAI"
    assert info.chat_model == "AnotherChatModel"


async def test_update_config_does_not_update_base_url_when_frozen() -> None:
    provider = _make_provider()
    provider.freeze_url = True

    provider.update_config(
        {
            "base_url": "https://blocked.example/v1",
            "api_key": "sk-frozen",
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.base_url == "https://mock-openai.local/v1"
    assert provider.api_key == "sk-frozen"
    assert info.base_url == "https://mock-openai.local/v1"
    assert info.api_key == "sk-frozen"


# ------------------------------------------------------------------
# wire_api / headers support
# ------------------------------------------------------------------


async def test_update_config_wire_api_valid() -> None:
    provider = _make_provider()

    provider.update_config({"wire_api": "responses"})
    assert provider.wire_api == "responses"

    provider.update_config({"wire_api": "chat_completions"})
    assert provider.wire_api == "chat_completions"


async def test_update_config_wire_api_invalid() -> None:
    provider = _make_provider()

    with pytest.raises(ValueError, match="wire_api must be one of"):
        provider.update_config({"wire_api": "invalid"})


async def test_update_config_wire_api_none_skipped() -> None:
    provider = _make_provider()
    provider.wire_api = "responses"

    provider.update_config({"wire_api": None})

    assert provider.wire_api == "responses"


async def test_update_config_headers_valid() -> None:
    provider = _make_provider()

    provider.update_config({"headers": {"X-Custom": "value"}})
    assert provider.headers == {"X-Custom": "value"}


async def test_update_config_headers_empty_dict() -> None:
    provider = _make_provider()
    provider.headers = {"Old": "val"}

    provider.update_config({"headers": {}})

    assert provider.headers == {}


async def test_update_config_headers_invalid_type() -> None:
    provider = _make_provider()

    with pytest.raises(ValueError, match="headers must be a dict"):
        provider.update_config({"headers": "not a dict"})


async def test_update_config_headers_none_skipped() -> None:
    provider = _make_provider()
    provider.headers = {"Keep": "me"}

    provider.update_config({"headers": None})

    assert provider.headers == {"Keep": "me"}


async def test_get_info_masks_headers() -> None:
    provider = _make_provider()
    provider.headers = {"Authorization": "Bearer sk-secret-key-12345"}

    info = await provider.get_info(mock_secret=True)

    assert "Authorization" in info.headers
    assert info.headers["Authorization"] != "Bearer sk-secret-key-12345"
    assert "***" in info.headers["Authorization"]


async def test_get_info_raw_headers() -> None:
    provider = _make_provider()
    provider.headers = {"X-Token": "abc123"}

    info = await provider.get_info(mock_secret=False)

    assert info.headers == {"X-Token": "abc123"}


async def test_get_info_wire_api() -> None:
    provider = _make_provider()
    provider.wire_api = "responses"

    info = await provider.get_info()

    assert info.wire_api == "responses"


def test_get_chat_model_instance_returns_responses_model() -> None:
    provider = _make_provider()
    provider.wire_api = "responses"
    provider.api_key = "sk-test"
    model = provider.get_chat_model_instance("gpt-4o")
    from copaw.providers.openai_responses_model import OpenAIResponsesChatModel

    assert isinstance(model, OpenAIResponsesChatModel)
