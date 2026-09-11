# -*- coding: utf-8 -*-
"""Tests for ``create_model_and_formatter`` model override support."""

# pylint: disable=protected-access,redefined-outer-name
from contextlib import contextmanager
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agentscope.formatter import OpenAIChatFormatter, OpenAIResponseFormatter

try:
    from agentscope.formatter import AnthropicChatFormatter
except ImportError:
    AnthropicChatFormatter = None

try:
    from agentscope.formatter import GeminiChatFormatter
except ImportError:
    GeminiChatFormatter = None

from qwenpaw.agents import model_factory
from qwenpaw.config import config as config_module
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers import fallback_chat_model
from qwenpaw.providers import provider as provider_module


_REAL_INSTALL_MODEL_FORMATTER = model_factory._install_model_formatter


class _FakeChatModel:
    """Minimal provider model used by the factory tests."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        self.formatter = SimpleNamespace()
        self.max_retries = 3
        self.qwenpaw_provider_id = "credential-derived"

    def bind_qwenpaw_provider_id(self, provider_id: str) -> None:
        """Record the provider identity selected by the factory."""
        self.qwenpaw_provider_id = provider_id


def _patched_load_agent_config(_agent_id):  # noqa: ARG001
    """Return fake agent config with an overridable active model."""
    return SimpleNamespace(
        active_model=ModelSlotConfig(
            provider_id="default-provider",
            model="default-model",
        ),
        running=SimpleNamespace(
            llm_retry_enabled=False,
            llm_max_retries=0,
            llm_backoff_base=1.0,
            llm_backoff_cap=10.0,
            llm_max_concurrent=None,
            llm_max_qpm=None,
            llm_rate_limit_pause=None,
            llm_rate_limit_jitter=None,
            llm_acquire_timeout=None,
            light_context_config=SimpleNamespace(
                context_compact_config=SimpleNamespace(enabled=False),
            ),
        ),
    )


@pytest.fixture(autouse=True)
def _patch_dependencies(monkeypatch):
    """Avoid touching the real provider manager / retry wrappers."""
    formatter_provider_ids = []

    def install_formatter(model, provider_id=None):
        formatter_provider_ids.append(provider_id)
        formatter = "formatter"
        if hasattr(model, "formatter"):
            model.formatter = formatter
        return formatter

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _patched_load_agent_config,
    )
    monkeypatch.setattr(
        model_factory,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_provider=lambda provider_id: SimpleNamespace(
                    id=provider_id,
                    get_chat_model_instance=(
                        lambda model_name: _FakeChatModel(
                            f"{provider_id}/{model_name}",
                        )
                    ),
                ),
                get_active_chat_model=lambda: None,
                get_active_model=lambda: None,
            ),
        ),
    )
    monkeypatch.setattr(
        model_factory,
        "_install_model_formatter",
        install_formatter,
    )
    monkeypatch.setattr(
        model_factory,
        "TokenRecordingModelWrapper",
        lambda _provider_id, model, **_kwargs: model,
    )
    monkeypatch.setattr(
        model_factory,
        "RetryChatModel",
        lambda model, **_kwargs: model,
    )
    return formatter_provider_ids


def test_override_with_model_slot_config(_patch_dependencies):
    """Passing a ``ModelSlotConfig`` instance overrides ``active_model``."""
    override = ModelSlotConfig(provider_id="p", model="m")

    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, fmt = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override=override,
        )

    assert model.identifier == "p/m"
    assert fmt == "formatter"
    assert _patch_dependencies == ["p"]


def test_factory_binds_returned_formatter_to_provider_model():
    """Callers that ignore the formatter return still use the enhanced one."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, fmt = model_factory.create_model_and_formatter(
            agent_id="agent-1",
        )

    assert model.formatter is fmt


def test_factory_uses_resolved_provider_id(
    monkeypatch,
    _patch_dependencies,
):
    """Resolved provider identity overrides credential-derived fallback."""
    canonical_model = _FakeChatModel("canonical-provider/model")
    wrapper_provider_ids = []
    manager = SimpleNamespace(
        get_provider=lambda _provider_id: SimpleNamespace(
            id="canonical-provider",
            get_chat_model_instance=lambda _model_name: canonical_model,
        ),
    )
    monkeypatch.setattr(
        model_factory,
        "ProviderManager",
        SimpleNamespace(get_instance=lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "TokenRecordingModelWrapper",
        lambda provider_id, model, **_kwargs: (
            wrapper_provider_ids.append(provider_id) or model
        ),
    )

    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override="configured-alias:model",
        )

    assert _patch_dependencies == ["canonical-provider"]
    assert wrapper_provider_ids == ["canonical-provider"]
    assert canonical_model.qwenpaw_provider_id == "canonical-provider"


def test_override_with_dict():
    """A dict matching the ModelSlotConfig schema is validated."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override={"provider_id": "p", "model": "m"},
        )

    assert model.identifier == "p/m"


def test_override_with_string():
    """A ``"provider:model"`` string is parsed via ``str.partition``."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override="p:m",
        )

    assert model.identifier == "p/m"


def test_override_with_string_preserves_colon_in_model_name():
    """Version tags in model names survive first-colon-only splitting."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override="openai:gpt-4o:2024-08-06",
        )

    assert model.identifier == "openai/gpt-4o:2024-08-06"


def test_override_with_invalid_string_falls_back_to_active_model():
    """An invalid override string is ignored and the agent's model wins."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override="no-colon-here",
        )

    assert model.identifier == "default-provider/default-model"


def test_override_with_unsupported_type_falls_back_to_active_model():
    """Non-str/dict/ModelSlotConfig values are ignored."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override=12345,
        )

    assert model.identifier == "default-provider/default-model"


def test_no_override_uses_active_model():
    """Without an override, the agent's persisted active_model is used."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
        )

    assert model.identifier == "default-provider/default-model"


async def test_async_factory_builds_model_in_worker_thread(monkeypatch):
    """The public async factory offloads the complete model build."""
    caller_thread = threading.get_ident()
    build_threads = []

    def record_build(**_kwargs):
        build_threads.append(threading.get_ident())
        return "model", "formatter"

    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        record_build,
    )

    result = await model_factory.create_model_and_formatter_async(
        agent_id="agent-1",
    )

    assert result == ("model", "formatter")
    assert build_threads and build_threads[0] != caller_thread


def test_preloaded_agent_config_preserves_model_settings(monkeypatch):
    """A preloaded config avoids disk I/O and preserves routing settings."""
    config = _patched_load_agent_config("agent-1")
    config.thinking_level = "high"
    config.fallback_models = [
        ModelSlotConfig(provider_id="fallback-provider", model="fallback"),
    ]
    config.fallback_policy = SimpleNamespace(
        enabled=True,
        target_scope="any",
    )
    config.running.llm_retry_enabled = True
    config.running.llm_max_retries = 4
    config.running.llm_max_concurrent = 2
    config.running.light_context_config.context_compact_config = (
        SimpleNamespace(enabled=True, compact_threshold_ratio=0.75)
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: pytest.fail("preloaded config must be reused"),
    )
    providers = {
        "default-provider": SimpleNamespace(
            get_chat_model_instance=lambda model_name: (
                f"default-provider/{model_name}"
            ),
        ),
        "fallback-provider": SimpleNamespace(
            get_model_info=lambda _model_name: SimpleNamespace(is_free=False),
            get_chat_model_instance=lambda model_name: (
                f"fallback-provider/{model_name}"
            ),
        ),
    }
    monkeypatch.setattr(
        model_factory,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_provider=providers.get,
            ),
        ),
    )
    retry_configs = []
    rate_limit_configs = []
    compact_thresholds = []
    thinking_levels = []

    @contextmanager
    def record_thinking_level(level):
        thinking_levels.append(level)
        yield

    def record_retry(model, **kwargs):
        retry_configs.append(kwargs["retry_config"])
        rate_limit_configs.append(kwargs["rate_limit_config"])
        return model

    def record_tokens(_provider_id, model, **kwargs):
        compact_thresholds.append(kwargs["compact_threshold"])
        return model

    monkeypatch.setattr(model_factory, "RetryChatModel", record_retry)
    monkeypatch.setattr(
        model_factory,
        "TokenRecordingModelWrapper",
        record_tokens,
    )
    monkeypatch.setattr(
        fallback_chat_model,
        "FallbackChatModel",
        lambda models: models,
    )
    monkeypatch.setattr(
        provider_module,
        "agent_thinking_level",
        record_thinking_level,
    )

    model, _ = model_factory.create_model_and_formatter(
        agent_id="agent-1",
        agent_config=config,
    )

    assert model == [
        "default-provider/default-model",
        "fallback-provider/fallback",
    ]
    assert [item.max_retries for item in retry_configs] == [4, 4]
    assert [item.max_concurrent for item in rate_limit_configs] == [2, 2]
    assert compact_thresholds == [0.75, 0.75]
    assert thinking_levels == ["high", "high"]


def test_each_fallback_model_gets_its_own_formatter(monkeypatch):
    """Install the protocol formatter before wrapping every model."""
    config = _patched_load_agent_config("agent-1")
    config.fallback_models = [
        ModelSlotConfig(provider_id="fallback-provider", model="fallback"),
    ]
    config.fallback_policy = SimpleNamespace(
        enabled=True,
        target_scope="any",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: config,
    )
    providers = {
        "default-provider": SimpleNamespace(
            get_chat_model_instance=lambda model_name: (
                f"default-provider/{model_name}"
            ),
        ),
        "fallback-provider": SimpleNamespace(
            get_model_info=lambda _model_name: SimpleNamespace(is_free=False),
            get_chat_model_instance=lambda model_name: (
                f"fallback-provider/{model_name}"
            ),
        ),
    }
    monkeypatch.setattr(
        model_factory,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_provider=lambda provider_id: providers[provider_id],
            ),
        ),
    )
    installed = []

    def install(model, provider_id=None):  # noqa: ARG001
        installed.append((model, provider_id))
        return f"formatter:{model}"

    monkeypatch.setattr(model_factory, "_install_model_formatter", install)
    monkeypatch.setattr(
        fallback_chat_model,
        "FallbackChatModel",
        lambda models: models,
    )

    model, formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert model == [
        "default-provider/default-model",
        "fallback-provider/fallback",
    ]
    assert formatter == "formatter:default-provider/default-model"
    assert installed == [
        ("default-provider/default-model", "default-provider"),
        ("fallback-provider/fallback", "fallback-provider"),
    ]


def test_model_override_disables_persisted_fallback_chain(monkeypatch):
    """Per-request and subagent overrides use only the selected model."""
    config = _patched_load_agent_config("agent-1")
    config.fallback_models = [
        ModelSlotConfig(provider_id="fallback-provider", model="fallback"),
    ]
    config.fallback_policy = SimpleNamespace(
        enabled=True,
        target_scope="any",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: config,
    )
    providers = {
        "override-provider": SimpleNamespace(
            get_chat_model_instance=lambda model_name: (
                f"override-provider/{model_name}"
            ),
        ),
        "fallback-provider": SimpleNamespace(
            get_model_info=lambda _model_name: SimpleNamespace(is_free=False),
            get_chat_model_instance=lambda model_name: (
                f"fallback-provider/{model_name}"
            ),
        ),
    }
    monkeypatch.setattr(
        model_factory,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_provider=providers.get,
            ),
        ),
    )
    fallback_calls = []
    monkeypatch.setattr(
        fallback_chat_model,
        "FallbackChatModel",
        fallback_calls.append,
    )

    model, _ = model_factory.create_model_and_formatter(
        agent_id="agent-1",
        model_slot_override={
            "provider_id": "override-provider",
            "model": "override",
        },
    )

    assert model == "override-provider/override"
    assert not fallback_calls


def test_invalid_fallback_slots_are_skipped(monkeypatch):
    """Missing providers and unknown models do not enter the chain."""
    config = _patched_load_agent_config("agent-1")
    config.fallback_models = [
        ModelSlotConfig(provider_id="missing-provider", model="missing"),
        ModelSlotConfig(provider_id="known-provider", model="unknown"),
    ]
    config.fallback_policy = SimpleNamespace(
        enabled=True,
        target_scope="any",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: config,
    )
    providers = {
        "default-provider": SimpleNamespace(
            get_chat_model_instance=lambda model_name: (
                f"default-provider/{model_name}"
            ),
        ),
        "known-provider": SimpleNamespace(
            get_model_info=lambda _model_name: None,
        ),
    }
    monkeypatch.setattr(
        model_factory,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_provider=providers.get,
            ),
        ),
    )
    fallback_calls = []
    monkeypatch.setattr(
        fallback_chat_model,
        "FallbackChatModel",
        fallback_calls.append,
    )

    model, _ = model_factory.create_model_and_formatter(agent_id="agent-1")

    assert model == "default-provider/default-model"
    assert not fallback_calls


@pytest.mark.parametrize(
    "formatter_class",
    [
        formatter
        for formatter in (
            OpenAIChatFormatter,
            OpenAIResponseFormatter,
            AnthropicChatFormatter,
            GeminiChatFormatter,
        )
        if formatter is not None
    ],
)
def test_installs_extended_formatter_for_each_protocol(formatter_class):
    """Install QwenPaw extensions on every supported protocol family."""
    native_formatter = formatter_class()
    model = SimpleNamespace(formatter=native_formatter)

    installed = _REAL_INSTALL_MODEL_FORMATTER(model)

    assert installed is model.formatter
    assert installed is not native_formatter
    assert isinstance(installed, formatter_class)
