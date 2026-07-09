# -*- coding: utf-8 -*-
"""Tests for ``create_model_and_formatter`` model override support."""

# pylint: disable=protected-access,redefined-outer-name
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.config import config as config_module
from qwenpaw.config.config import ModelSlotConfig


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
                    provider_id=provider_id,
                    get_chat_model_instance=(
                        lambda model_name: f"{provider_id}/{model_name}"
                    ),
                ),
                get_active_chat_model=lambda: None,
                get_active_model=lambda: None,
            ),
        ),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _model: "formatter",
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


def test_override_with_model_slot_config():
    """Passing a ``ModelSlotConfig`` instance overrides ``active_model``."""
    override = ModelSlotConfig(provider_id="p", model="m")

    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, fmt = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override=override,
        )

    assert model == "p/m"
    assert fmt == "formatter"


def test_override_with_dict():
    """A dict matching the ModelSlotConfig schema is validated."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override={"provider_id": "p", "model": "m"},
        )

    assert model == "p/m"


def test_override_with_string():
    """A ``"provider:model"`` string is parsed via ``str.partition``."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override="p:m",
        )

    assert model == "p/m"


def test_override_with_string_preserves_colon_in_model_name():
    """Version tags in model names survive first-colon-only splitting."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override="openai:gpt-4o:2024-08-06",
        )

    assert model == "openai/gpt-4o:2024-08-06"


def test_override_with_invalid_string_falls_back_to_active_model():
    """An invalid override string is ignored and the agent's model wins."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override="no-colon-here",
        )

    assert model == "default-provider/default-model"


def test_override_with_unsupported_type_falls_back_to_active_model():
    """Non-str/dict/ModelSlotConfig values are ignored."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
            model_slot_override=12345,
        )

    assert model == "default-provider/default-model"


def test_no_override_uses_active_model():
    """Without an override, the agent's persisted active_model is used."""
    with patch.object(model_factory, "RetryConfig") as retry_cls:
        retry_cls.return_value = "rc"
        model, _ = model_factory.create_model_and_formatter(
            agent_id="agent-1",
        )

    assert model == "default-provider/default-model"
