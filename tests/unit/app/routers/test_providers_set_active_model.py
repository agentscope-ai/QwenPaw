# -*- coding: utf-8 -*-
"""Regression tests: Settings → global LLM swap must hot-reload agents.

A running ``ReActAgent`` binds its chat model at construction time
(``react_agent.py:150``). Persisting a new global default via
``PUT /models/active`` with ``scope="global"`` changes only the on-disk
``ProviderManager`` state — without scheduling a reload, every agent
currently in ``MultiAgentManager.agents`` keeps serving from the old
model instance, so the chat page silently ignores the setting change.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

import pytest

from qwenpaw.app.routers import providers as providers_router
from qwenpaw.providers.models import ModelSlotConfig


class DummyProviderManager:
    def __init__(self) -> None:
        self.active_model = ModelSlotConfig(
            provider_id="old-global",
            model="old-model",
        )
        self.activate_calls: List[tuple[str, str]] = []

    async def activate_model(self, provider_id: str, model_id: str) -> None:
        self.activate_calls.append((provider_id, model_id))
        self.active_model = ModelSlotConfig(
            provider_id=provider_id,
            model=model_id,
        )

    def get_active_model(self) -> ModelSlotConfig | None:
        return self.active_model


class FakeMultiAgentManager:
    """Mirrors the ``agents`` dict + ``reload_agent`` entry points used by
    :func:`qwenpaw.app.utils.schedule_all_agents_reload`."""

    def __init__(self, agent_ids: List[str]) -> None:
        self.agents = {
            agent_id: MagicMock(name=f"Workspace({agent_id})")
            for agent_id in agent_ids
        }
        self.reloaded: List[str] = []

    async def reload_agent(self, agent_id: str) -> bool:
        self.reloaded.append(agent_id)
        return True


def _make_request(multi_agent_manager) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=multi_agent_manager),
        ),
    )


async def _drain_pending_tasks() -> None:
    """Let the background reload tasks run to completion."""
    # Give asyncio.create_task() scheduling a chance to execute.
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_global_set_reloads_every_running_agent():
    """Saving a new global model must schedule a reload for each agent
    currently instantiated in the MultiAgentManager — otherwise the
    swap is invisible to live chat sessions."""
    manager = DummyProviderManager()
    multi_agent = FakeMultiAgentManager(["agent-a", "agent-b", "agent-c"])
    request = _make_request(multi_agent)

    body = providers_router.ModelSlotRequest(
        provider_id="new-global",
        model="new-model",
        scope="global",
    )

    result = await providers_router.set_active_model(
        request=request,
        manager=manager,
        body=body,
    )

    await _drain_pending_tasks()

    assert manager.activate_calls == [("new-global", "new-model")]
    assert result.active_llm == ModelSlotConfig(
        provider_id="new-global",
        model="new-model",
    )
    assert sorted(multi_agent.reloaded) == ["agent-a", "agent-b", "agent-c"]


@pytest.mark.asyncio
async def test_global_set_without_running_agents_is_noop():
    """With no agents booted yet, the reload loop should simply do
    nothing — not crash, not raise. Covers the cold-start path."""
    manager = DummyProviderManager()
    multi_agent = FakeMultiAgentManager([])
    request = _make_request(multi_agent)

    body = providers_router.ModelSlotRequest(
        provider_id="new-global",
        model="new-model",
        scope="global",
    )

    await providers_router.set_active_model(
        request=request,
        manager=manager,
        body=body,
    )
    await _drain_pending_tasks()

    assert not multi_agent.reloaded


@pytest.mark.asyncio
async def test_global_set_tolerates_missing_multi_agent_manager():
    """If the app state has no ``multi_agent_manager`` (e.g. CLI-only
    boot), the global save path should log a warning and succeed, not
    crash the request."""
    manager = DummyProviderManager()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace()),
    )

    body = providers_router.ModelSlotRequest(
        provider_id="new-global",
        model="new-model",
        scope="global",
    )

    result = await providers_router.set_active_model(
        request=request,
        manager=manager,
        body=body,
    )
    await _drain_pending_tasks()

    assert result.active_llm == ModelSlotConfig(
        provider_id="new-global",
        model="new-model",
    )


@pytest.mark.asyncio
async def test_global_set_reload_surface_before_fix(monkeypatch):
    """Pin the contract: the global branch must call
    ``schedule_all_agents_reload``. Regression test so the wiring can't
    be silently dropped again."""
    manager = DummyProviderManager()
    multi_agent = FakeMultiAgentManager(["agent-a"])
    request = _make_request(multi_agent)

    called: list = []

    def fake_reload_all(req) -> None:
        called.append(req)

    monkeypatch.setattr(
        providers_router,
        "schedule_all_agents_reload",
        fake_reload_all,
    )

    body = providers_router.ModelSlotRequest(
        provider_id="new-global",
        model="new-model",
        scope="global",
    )

    await providers_router.set_active_model(
        request=request,
        manager=manager,
        body=body,
    )

    assert called == [request]
