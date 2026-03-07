# -*- coding: utf-8 -*-

from copaw.agents.model_factory import _create_remote_model_instance
from copaw.agents.model_factory import _session_affinity_hash
from copaw.providers.models import ResolvedModelConfig


class _DummyChatModel:
    def __init__(
        self,
        model_name: str,
        *,
        api_key: str,
        stream: bool,
        client_kwargs: dict,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.stream = stream
        self.client_kwargs = client_kwargs


def test_custom_provider_injects_session_affinity_when_enabled() -> None:
    llm_cfg = ResolvedModelConfig(
        provider_id="custom-vllm",
        model="qwen",
        base_url="http://127.0.0.1:8000/v1",
        api_key="test-key",
        is_custom=True,
        enable_session_affinity=True,
    )

    model = _create_remote_model_instance(
        llm_cfg,
        _DummyChatModel,
        session_id="session-1",
    )
    headers = model.client_kwargs["default_headers"]
    assert headers["x-session-affinity"] == _session_affinity_hash("session-1")


def test_custom_provider_keeps_user_defined_affinity_header() -> None:
    llm_cfg = ResolvedModelConfig(
        provider_id="custom-vllm",
        model="qwen",
        base_url="http://127.0.0.1:8000/v1",
        api_key="test-key",
        is_custom=True,
        extra_headers={
            "X-Session-Affinity": "user-defined-affinity",
            "x-extra": "demo",
        },
        enable_session_affinity=True,
        session_affinity_header="x-session-affinity",
    )

    model = _create_remote_model_instance(
        llm_cfg,
        _DummyChatModel,
        session_id="session-1",
    )
    headers = model.client_kwargs["default_headers"]
    assert headers["X-Session-Affinity"] == "user-defined-affinity"
    assert "x-session-affinity" not in headers
    assert headers["x-extra"] == "demo"


def test_non_custom_provider_does_not_inject_affinity_header() -> None:
    llm_cfg = ResolvedModelConfig(
        provider_id="openai",
        model="gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        is_custom=False,
        enable_session_affinity=True,
    )

    model = _create_remote_model_instance(
        llm_cfg,
        _DummyChatModel,
        session_id="session-1",
    )
    headers = model.client_kwargs.get("default_headers", {})
    assert all(
        header_name.lower() != "x-session-affinity" for header_name in headers
    )


def test_custom_provider_supports_custom_affinity_header_name() -> None:
    llm_cfg = ResolvedModelConfig(
        provider_id="custom-vllm",
        model="qwen",
        base_url="http://127.0.0.1:8000/v1",
        api_key="test-key",
        is_custom=True,
        enable_session_affinity=True,
        session_affinity_header="x-affinity",
    )

    model = _create_remote_model_instance(
        llm_cfg,
        _DummyChatModel,
        session_id="session-2",
    )
    headers = model.client_kwargs["default_headers"]
    assert headers["x-affinity"] == _session_affinity_hash("session-2")


def test_custom_provider_skips_affinity_when_session_is_empty() -> None:
    llm_cfg = ResolvedModelConfig(
        provider_id="custom-vllm",
        model="qwen",
        base_url="http://127.0.0.1:8000/v1",
        api_key="test-key",
        is_custom=True,
        enable_session_affinity=True,
    )

    model = _create_remote_model_instance(
        llm_cfg,
        _DummyChatModel,
        session_id="",
    )
    headers = model.client_kwargs.get("default_headers", {})
    assert all(
        header_name.lower() != "x-session-affinity" for header_name in headers
    )
