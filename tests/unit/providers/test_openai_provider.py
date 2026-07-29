# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

from agentscope.model import OpenAIChatModel

import qwenpaw.providers.openai_provider as openai_provider_module
from qwenpaw.providers.openai_provider import OpenAIProvider


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
    assert msg.startswith(
        f"API error when connecting to `{provider.base_url}`",
    )


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
    assert not provider.models  # should not update provider state


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
    assert captured[0]["max_tokens"] == 20
    assert captured[0]["stream"] is True


async def test_check_gpt5_model_uses_max_completion_tokens(
    monkeypatch,
) -> None:
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

    ok, msg = await provider.check_model_connection("gpt-5.2", timeout=4)

    assert ok is True
    assert msg == ""
    assert captured[0]["max_completion_tokens"] == 20
    assert "max_tokens" not in captured[0]


def test_token_limit_kwargs_handles_reasoning_model_ids() -> None:
    assert openai_provider_module._token_limit_kwargs(
        "openai/gpt-5-mini",
        200,
    ) == {"max_completion_tokens": 200}
    assert openai_provider_module._token_limit_kwargs(
        "o3",
        200,
    ) == {"max_completion_tokens": 200}
    assert openai_provider_module._token_limit_kwargs(
        "openai/o4-mini",
        200,
    ) == {"max_completion_tokens": 200}
    assert openai_provider_module._token_limit_kwargs(
        "openai/gpt-4o-mini",
        200,
    ) == {"max_tokens": 200}


async def test_summary_limit_uses_reasoning_model_parameter(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def fake_call_api(self, *args, **kwargs):
        del self, args
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(OpenAIChatModel, "_call_api", fake_call_api)
    model = _make_provider().get_chat_model_instance("gpt-5.2")

    result = await model._call_api(
        "gpt-5.2",
        [],
        max_tokens=256,
        disable_thinking=True,
    )

    assert result == "ok"
    assert captured["max_completion_tokens"] == 256
    assert "max_tokens" not in captured


def test_get_gpt5_model_maps_configured_max_tokens() -> None:
    provider = _make_provider()
    provider.generate_kwargs = {"max_tokens": 4096}

    model = provider.get_chat_model_instance("gpt-5.2")

    assert model.parameters.max_tokens is None
    assert model._extra_generate_kwargs == {
        "max_completion_tokens": 4096,
    }


def test_get_o_series_model_maps_configured_max_tokens() -> None:
    provider = _make_provider()
    provider.generate_kwargs = {"max_tokens": 4096}

    model = provider.get_chat_model_instance("o3")

    assert model.parameters.max_tokens is None
    assert model._extra_generate_kwargs == {
        "max_completion_tokens": 4096,
    }


def test_get_gpt5_model_preserves_explicit_max_completion_tokens() -> None:
    provider = _make_provider()
    provider.generate_kwargs = {
        "max_tokens": 4096,
        "max_completion_tokens": 2048,
    }

    model = provider.get_chat_model_instance("gpt-5-mini")

    assert model.parameters.max_tokens is None
    assert model._extra_generate_kwargs == {
        "max_completion_tokens": 2048,
    }


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
    assert msg.startswith(
        "API error when connecting to model 'gpt-4o-mini'",
    )
    assert "failed" in msg


async def test_check_model_connection_non_chat_model_skips_chat_probe(
    monkeypatch,
) -> None:
    provider = _make_provider()
    chat_calls: list[dict] = []
    connection_checks: list[float] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            chat_calls.append(kwargs)
            raise AssertionError("chat probe must not run for non-chat model")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    async def fake_check_connection(self, timeout=5):
        del self
        connection_checks.append(timeout)
        return True, ""

    monkeypatch.setattr(
        OpenAIProvider,
        "check_connection",
        fake_check_connection,
    )

    for model_id in (
        "wan2.2-t2v-plus",
        "qwen3-asr-flash",
        "paraformer-realtime-v2",
        "text-embedding-v3",
    ):
        ok, msg = await provider.check_model_connection(model_id, timeout=4)
        assert ok is True
        assert "not a chat model" in msg

    assert not chat_calls
    assert connection_checks == [4, 4, 4, 4]


class _FakeHTTPResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def _install_fake_httpx_get(monkeypatch, requests: list, response) -> None:
    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, params=None, headers=None):
            requests.append(
                {"url": url, "params": params, "headers": headers},
            )
            return response

    monkeypatch.setattr(
        openai_provider_module.httpx,
        "AsyncClient",
        FakeAsyncClient,
    )


def _make_dashscope_like_provider() -> OpenAIProvider:
    return OpenAIProvider(
        id="dashscope",
        name="DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
        chat_model="OpenAIChatModel",
    )


async def test_dashscope_non_chat_model_uses_upload_policy_probe(
    monkeypatch,
) -> None:
    provider = _make_dashscope_like_provider()
    requests: list[dict] = []
    _install_fake_httpx_get(
        monkeypatch,
        requests,
        _FakeHTTPResponse(200, {"data": {"upload_host": "x"}}),
    )

    ok, msg = await provider.check_model_connection(
        "wan2.2-t2v-plus",
        timeout=4,
    )

    assert ok is True
    assert "upload-policy" in msg
    assert requests[0]["url"] == (
        "https://dashscope.aliyuncs.com/api/v1/uploads"
    )
    assert requests[0]["params"] == {
        "action": "getPolicy",
        "model": "wan2.2-t2v-plus",
    }
    assert requests[0]["headers"]["Authorization"] == "Bearer sk-test"


async def test_dashscope_non_chat_model_invalid_key_fails(
    monkeypatch,
) -> None:
    provider = _make_dashscope_like_provider()
    requests: list[dict] = []
    _install_fake_httpx_get(
        monkeypatch,
        requests,
        _FakeHTTPResponse(
            401,
            {"code": "InvalidApiKey", "message": "Invalid API-key"},
        ),
    )

    ok, msg = await provider.check_model_connection(
        "qwen3-asr-flash",
        timeout=4,
    )

    assert ok is False
    assert "rejected the API key" in msg
    assert "InvalidApiKey" in msg


async def test_dashscope_non_chat_model_unknown_model_fails(
    monkeypatch,
) -> None:
    provider = _make_dashscope_like_provider()
    requests: list[dict] = []
    _install_fake_httpx_get(
        monkeypatch,
        requests,
        _FakeHTTPResponse(
            400,
            {"code": "InvalidParameter", "message": "Model not exist"},
        ),
    )

    ok, msg = await provider.check_model_connection(
        "wan99-t2v-fake",
        timeout=4,
    )

    assert ok is False
    assert "does not recognise model" in msg


async def test_dashscope_non_chat_model_policy_unsupported_still_ok(
    monkeypatch,
) -> None:
    provider = _make_dashscope_like_provider()
    requests: list[dict] = []
    _install_fake_httpx_get(
        monkeypatch,
        requests,
        _FakeHTTPResponse(
            400,
            {
                "code": "InvalidParameter",
                "message": "file upload is not supported",
            },
        ),
    )

    ok, msg = await provider.check_model_connection(
        "cosyvoice-tts-v3",
        timeout=4,
    )

    assert ok is True
    assert "API key verified" in msg


async def test_dashscope_non_chat_model_transient_statuses_fail(
    monkeypatch,
) -> None:
    for status_code in (404, 408, 429, 500, 502, 503):
        provider = _make_dashscope_like_provider()
        requests: list[dict] = []
        _install_fake_httpx_get(
            monkeypatch,
            requests,
            _FakeHTTPResponse(
                status_code,
                {"code": "ServerError", "message": "unavailable"},
            ),
        )

        ok, msg = await provider.check_model_connection(
            "wan2.2-t2v-plus",
            timeout=4,
        )

        assert ok is False, status_code
        assert f"status={status_code}" in msg


async def test_ark_non_chat_model_uses_task_list_probe(monkeypatch) -> None:
    provider = OpenAIProvider(
        id="volcengine-cn",
        name="Volcengine",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="ak-test",
        chat_model="OpenAIChatModel",
    )
    requests: list[dict] = []
    _install_fake_httpx_get(
        monkeypatch,
        requests,
        _FakeHTTPResponse(200, {"items": [], "total": 0}),
    )

    ok, msg = await provider.check_model_connection(
        "doubao-seedance-1-0-pro",
        timeout=4,
    )

    assert ok is True
    assert "task-list" in msg
    assert requests[0]["url"] == (
        "https://ark.cn-beijing.volces.com"
        "/api/v3/contents/generations/tasks"
    )
    assert requests[0]["headers"]["Authorization"] == "Bearer ak-test"


async def test_ark_non_chat_model_invalid_key_fails(monkeypatch) -> None:
    provider = OpenAIProvider(
        id="volcengine-cn",
        name="Volcengine",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="ak-bad",
        chat_model="OpenAIChatModel",
    )
    requests: list[dict] = []
    _install_fake_httpx_get(
        monkeypatch,
        requests,
        _FakeHTTPResponse(
            401,
            {
                "error": {
                    "code": "AuthenticationError",
                    "message": "invalid api key",
                },
            },
        ),
    )

    ok, msg = await provider.check_model_connection(
        "doubao-seedance-1-0-pro",
        timeout=4,
    )

    assert ok is False
    assert "rejected the API key" in msg
    assert "AuthenticationError" in msg


async def test_check_model_connection_api_type_mismatch_treated_as_ok(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeCompletions:
        async def create(self, **kwargs):
            _ = kwargs
            raise RuntimeError(
                "Error code: 403 - current user api does not support "
                "asynchronous calls",
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)
    monkeypatch.setattr(openai_provider_module, "APIError", Exception)

    # A generation model whose id does not match the non-chat patterns
    ok, msg = await provider.check_model_connection("my-video-gen", timeout=4)

    assert ok is True
    assert "dedicated non-chat" in msg


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
