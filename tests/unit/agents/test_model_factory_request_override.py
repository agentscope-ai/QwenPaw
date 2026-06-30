# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ModelNotFoundException, ProviderError
from qwenpaw.schemas import AgentRequest


def _running_config() -> SimpleNamespace:
    return SimpleNamespace(
        llm_retry_enabled=False,
        llm_max_retries=0,
        llm_backoff_base=0.1,
        llm_backoff_cap=1.0,
        llm_max_concurrent=1,
        llm_max_qpm=0,
        llm_rate_limit_pause=0.0,
        llm_rate_limit_jitter=0.0,
        llm_acquire_timeout=1.0,
    )


class FakeProvider:
    def __init__(self, *model_ids: str) -> None:
        self._model_ids = set(model_ids)
        self.calls: list[str] = []

    def has_model(self, model_id: str) -> bool:
        return model_id in self._model_ids

    def get_chat_model_instance(self, model_id: str) -> SimpleNamespace:
        self.calls.append(model_id)
        return SimpleNamespace(model=model_id)


class FakeProviderManager:
    def __init__(
        self,
        providers: dict[str, FakeProvider],
        active_model: ModelSlotConfig | None = None,
    ) -> None:
        self._providers = providers
        self._active_model = active_model

    def get_provider(self, provider_id: str) -> FakeProvider | None:
        return self._providers.get(provider_id)

    def get_active_model(self) -> ModelSlotConfig | None:
        return self._active_model


def _patch_model_factory(
    monkeypatch: pytest.MonkeyPatch,
    manager: FakeProviderManager,
    *,
    agent_model: ModelSlotConfig | None = None,
) -> None:
    agent_config = SimpleNamespace(
        active_model=agent_model,
        running=_running_config(),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: agent_config,
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        lambda: manager,
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_active_chat_model",
        lambda: SimpleNamespace(model=manager.get_active_model().model),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _model: None,
    )
    monkeypatch.setattr(
        model_factory,
        "TokenRecordingModelWrapper",
        lambda provider_id, model: SimpleNamespace(
            provider_id=provider_id,
            model=model.model,
        ),
    )
    monkeypatch.setattr(
        model_factory,
        "RetryChatModel",
        lambda inner, retry_config=None, rate_limit_config=None: inner,
    )


def test_agent_request_declares_model_field() -> None:
    assert "model" in AgentRequest.model_fields


def test_request_model_override_wins_over_agent_active_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_provider = FakeProvider("agent-model")
    override_provider = FakeProvider("override-model")
    _patch_model_factory(
        monkeypatch,
        FakeProviderManager(
            {
                "agent-provider": agent_provider,
                "override-provider": override_provider,
            },
        ),
        agent_model=ModelSlotConfig(
            provider_id="agent-provider",
            model="agent-model",
        ),
    )

    model, _formatter = model_factory.create_model_and_formatter(
        agent_id="agent-a",
        model_override="override-provider:override-model",
    )

    assert model.provider_id == "override-provider"
    assert model.model == "override-model"
    assert override_provider.calls == ["override-model"]
    assert agent_provider.calls == []


def test_empty_request_model_falls_back_to_agent_active_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_provider = FakeProvider("agent-model")
    _patch_model_factory(
        monkeypatch,
        FakeProviderManager({"agent-provider": agent_provider}),
        agent_model=ModelSlotConfig(
            provider_id="agent-provider",
            model="agent-model",
        ),
    )

    model, _formatter = model_factory.create_model_and_formatter(
        agent_id="agent-a",
        model_override="",
    )

    assert model.provider_id == "agent-provider"
    assert model.model == "agent-model"
    assert agent_provider.calls == ["agent-model"]


def test_empty_request_model_falls_back_to_global_active_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_model_factory(
        monkeypatch,
        FakeProviderManager(
            {},
            active_model=ModelSlotConfig(
                provider_id="global-provider",
                model="global-model",
            ),
        ),
    )

    model, _formatter = model_factory.create_model_and_formatter(
        agent_id="agent-a",
        model_override="",
    )

    assert model.provider_id == "global-provider"
    assert model.model == "global-model"


@pytest.mark.parametrize(
    ("override", "exc_type", "match"),
    [
        ("missing-provider:model", ProviderError, "Provider 'missing-provider'"),
        (
            "agent-provider:missing-model",
            ModelNotFoundException,
            "agent-provider/missing-model",
        ),
        ("missing-colon", ProviderError, "provider:model"),
    ],
)
def test_invalid_request_model_override_has_clear_error(
    monkeypatch: pytest.MonkeyPatch,
    override: str,
    exc_type: type[Exception],
    match: str,
) -> None:
    _patch_model_factory(
        monkeypatch,
        FakeProviderManager({"agent-provider": FakeProvider("agent-model")}),
    )

    with pytest.raises(exc_type, match=match):
        model_factory.create_model_and_formatter(model_override=override)
