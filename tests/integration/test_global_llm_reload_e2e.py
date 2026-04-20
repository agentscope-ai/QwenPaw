# -*- coding: utf-8 -*-
"""End-to-end: PUT /models/active with scope=global reloads running agents.

Exercises the real HTTP stack — a minimal FastAPI app with the real
providers router, a real MultiAgentManager, and stub Workspace objects
that log their reload. Proves the whole path (HTTP → router →
schedule_all_agents_reload → asyncio.create_task →
MultiAgentManager.reload_agent) wires through correctly, not just the
function in isolation.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.routers import providers as providers_router
from qwenpaw.providers.models import ModelSlotConfig


class DummyProviderManager:
    def __init__(self) -> None:
        self.active_model = ModelSlotConfig(
            provider_id="opencode",
            model="nemotron-3-super-free",
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


class _RecordingMultiAgentManager(MultiAgentManager):
    """Real MultiAgentManager subclass that only records reload requests."""

    def __init__(self, agent_ids: List[str]) -> None:
        super().__init__()
        self.reloaded: List[str] = []
        self._reload_done = asyncio.Event()
        for agent_id in agent_ids:
            # Populate the internal dict directly with a placeholder so that
            # ``list(self.agents.keys())`` returns them. reload_agent is
            # overridden to avoid touching Workspace/config.
            self.agents[agent_id] = SimpleNamespace(agent_id=agent_id)

    async def reload_agent(self, agent_id: str) -> bool:
        self.reloaded.append(agent_id)
        if set(self.reloaded) >= set(self.agents.keys()):
            self._reload_done.set()
        return True

    async def wait_for_reloads(self, timeout: float = 2.0) -> None:
        await asyncio.wait_for(self._reload_done.wait(), timeout=timeout)


def _make_app(
    provider_manager: DummyProviderManager,
    multi_agent: _RecordingMultiAgentManager,
) -> FastAPI:
    app = FastAPI()
    app.state.provider_manager = provider_manager
    app.state.multi_agent_manager = multi_agent

    def _override_provider_manager():
        return provider_manager

    app.dependency_overrides[
        providers_router.get_provider_manager
    ] = _override_provider_manager
    app.include_router(providers_router.router)
    return app


@pytest.mark.asyncio
async def test_put_global_active_schedules_reload_for_every_agent():
    """PUT /active with scope=global over real HTTP must propagate the
    change to every agent currently in MultiAgentManager."""
    provider = DummyProviderManager()
    multi_agent = _RecordingMultiAgentManager(
        ["default", "qa-bot", "worker-1"],
    )
    app = _make_app(provider, multi_agent)

    with TestClient(app) as client:
        resp = client.put(
            "/models/active",
            json={
                "provider_id": "aliyun-codingplan",
                "model": "qwen3.6-plus",
                "scope": "global",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["active_llm"] == {
            "provider_id": "aliyun-codingplan",
            "model": "qwen3.6-plus",
        }

        await multi_agent.wait_for_reloads(timeout=3.0)

    assert provider.activate_calls == [
        ("aliyun-codingplan", "qwen3.6-plus"),
    ]
    assert sorted(multi_agent.reloaded) == [
        "default",
        "qa-bot",
        "worker-1",
    ]


@pytest.mark.asyncio
async def test_put_agent_scope_does_not_reload_other_agents(monkeypatch):
    """PUT /active with scope=agent must only reload that one agent —
    the global-wide reload must not fire for agent-scoped writes."""
    provider = DummyProviderManager()
    multi_agent = _RecordingMultiAgentManager(
        ["default", "qa-bot"],
    )
    app = _make_app(provider, multi_agent)

    # Stub out the filesystem side of agent config so the handler
    # persists a "write" without touching disk.
    saved: Dict[str, ModelSlotConfig] = {}

    def _fake_load_agent_config(_agent_id: str):
        return SimpleNamespace(
            active_model=saved.get(_agent_id),
        )

    def _fake_save_agent_config(agent_id: str, agent_config) -> None:
        saved[agent_id] = agent_config.active_model

    async def _fake_get_agent_for_request(_request, agent_id=None):
        return SimpleNamespace(agent_id=agent_id or "default")

    monkeypatch.setattr(
        providers_router,
        "load_agent_config",
        _fake_load_agent_config,
    )
    monkeypatch.setattr(
        providers_router,
        "save_agent_config",
        _fake_save_agent_config,
    )
    monkeypatch.setattr(
        providers_router,
        "get_agent_for_request",
        _fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        providers_router,
        "_validate_model_slot",
        lambda *_args, **_kwargs: None,
    )
    # Guard: the probe must not raise in unit-land.
    monkeypatch.setattr(
        provider,
        "maybe_probe_multimodal",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    with TestClient(app) as client:
        resp = client.put(
            "/models/active",
            json={
                "provider_id": "opencode",
                "model": "big-pickle",
                "scope": "agent",
                "agent_id": "default",
            },
        )
        assert resp.status_code == 200, resp.text

    # Give any pending reload task a chance to run.
    await asyncio.sleep(0.05)

    # Only the targeted agent should be reloaded. The global-wide
    # broadcast must not touch qa-bot.
    assert "qa-bot" not in multi_agent.reloaded
    assert "default" in multi_agent.reloaded
