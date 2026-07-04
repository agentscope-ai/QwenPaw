# -*- coding: utf-8 -*-
# pylint: disable=missing-class-docstring,missing-function-docstring
# pylint: disable=too-few-public-methods,protected-access,no-member
# pylint: disable=use-implicit-booleaness-not-comparison
"""Tests for model_factory fallback wiring."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agentscope.model import ChatModelBase

from qwenpaw.agents import model_factory
from qwenpaw.config.config import (
    AgentsLLMFallbackConfig,
    AgentsLLMRoutingConfig,
    AgentsRunningConfig,
    ModelSlotConfig,
)
from qwenpaw.providers.fallback_chat_model import FallbackChatModel
from qwenpaw.providers.retry_chat_model import RetryChatModel
from qwenpaw.token_usage import TokenRecordingModelWrapper


class PrimaryFormatter:
    pass


class BackupFormatter:
    pass


class FakeChatModel(ChatModelBase):
    def __init__(self, name: str, formatter_cls=PrimaryFormatter) -> None:
        super().__init__(
            credential=None,
            model=name,
            parameters=None,
            stream=False,
        )
        self.formatter = formatter_cls()

    async def __call__(self, *args, **kwargs):  # pragma: no cover
        del args, kwargs
        raise NotImplementedError


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        formatter_cls=PrimaryFormatter,
    ) -> None:
        self.provider_id = provider_id
        self.formatter_cls = formatter_cls
        self.created: list[str] = []
        self.models = [
            SimpleNamespace(id="main"),
            SimpleNamespace(id="standby"),
        ]
        self.extra_models = []

    def get_chat_model_instance(self, model_id: str) -> FakeChatModel:
        self.created.append(model_id)
        return FakeChatModel(model_id, self.formatter_cls)


class FakeProviderManager:
    def __init__(self, *, backup_formatter_cls=PrimaryFormatter) -> None:
        self.providers = {
            "primary": FakeProvider("primary"),
            "backup": FakeProvider("backup", backup_formatter_cls),
        }

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)

    def get_active_model(self):
        return ModelSlotConfig(provider_id="primary", model="global-model")


def _agent_config(
    *,
    fallback_enabled: bool = False,
    compact_threshold: float = 0.8,
):
    running = AgentsRunningConfig()
    ctx_config = running.light_context_config
    ctx_config.context_compact_config.compact_threshold_ratio = (
        compact_threshold
    )
    return SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="primary", model="main"),
        running=running,
        llm_routing=AgentsLLMRoutingConfig(
            fallback=AgentsLLMFallbackConfig(
                enabled=fallback_enabled,
                models=[
                    ModelSlotConfig(provider_id="backup", model="standby"),
                ],
            ),
        ),
    )


def _patch_factory(manager: FakeProviderManager, agent_config):
    return (
        patch.object(
            model_factory.ProviderManager,
            "get_instance",
            return_value=manager,
        ),
        patch(
            "qwenpaw.config.config.load_agent_config",
            return_value=agent_config,
        ),
        patch.object(
            model_factory,
            "_create_formatter_instance",
            return_value=object(),
        ),
    )


def test_create_model_disabled_fallback_returns_retry_wrapper() -> None:
    manager = FakeProviderManager()
    patches = _patch_factory(manager, _agent_config(fallback_enabled=False))
    with patches[0], patches[1], patches[2]:
        model, _formatter = model_factory.create_model_and_formatter("agent-1")

    assert isinstance(model, RetryChatModel)
    assert isinstance(
        model._inner,
        TokenRecordingModelWrapper,
    )  # pylint: disable=protected-access
    assert manager.providers["primary"].created == ["main"]
    assert manager.providers["backup"].created == []


def test_create_model_passes_compact_threshold_to_token_wrapper() -> None:
    manager = FakeProviderManager()
    patches = _patch_factory(
        manager,
        _agent_config(fallback_enabled=False, compact_threshold=0.5),
    )
    with patches[0], patches[1], patches[2]:
        model, _formatter = model_factory.create_model_and_formatter("agent-1")

    assert isinstance(model, RetryChatModel)
    assert model._inner._compact_threshold == 0.5


def test_create_model_enabled_fallback_returns_fallback_wrapper() -> None:
    manager = FakeProviderManager()
    patches = _patch_factory(manager, _agent_config(fallback_enabled=True))
    with patches[0], patches[1], patches[2]:
        model, _formatter = model_factory.create_model_and_formatter("agent-1")

    assert isinstance(model, FallbackChatModel)
    assert [candidate.label for candidate in model.candidates] == [
        "primary:main",
        "backup:standby",
    ]
    assert all(
        isinstance(candidate.model, RetryChatModel)
        for candidate in model.candidates
    )
    assert manager.providers["primary"].created == ["main"]
    assert manager.providers["backup"].created == ["standby"]


def test_create_model_skips_fallback_with_different_formatter_family() -> None:
    manager = FakeProviderManager(backup_formatter_cls=BackupFormatter)
    patches = _patch_factory(manager, _agent_config(fallback_enabled=True))
    with patches[0], patches[1], patches[2]:
        model, _formatter = model_factory.create_model_and_formatter("agent-1")

    assert isinstance(model, RetryChatModel)
    assert manager.providers["primary"].created == ["main"]
    assert manager.providers["backup"].created == ["standby"]
