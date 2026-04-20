# -*- coding: utf-8 -*-
"""Regression tests: global routing changes must reload running agents."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

import pytest

from qwenpaw.app.routers import config as config_router
from qwenpaw.config.config import AgentsLLMRoutingConfig
from qwenpaw.providers.models import ModelSlotConfig


class FakeMultiAgentManager:
    """Minimal shape required by schedule_all_agents_reload()."""

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
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_put_global_routing_reloads_every_running_agent(monkeypatch):
    multi_agent = FakeMultiAgentManager(["agent-a", "agent-b"])
    request = _make_request(multi_agent)
    saved = {}

    monkeypatch.setattr(
        config_router,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(),
            ),
        ),
    )
    monkeypatch.setattr(
        config_router,
        "save_config",
        lambda config: saved.setdefault("routing", config.agents.llm_routing),
    )

    body = AgentsLLMRoutingConfig(
        enabled=True,
        mode="local_first",
        local=ModelSlotConfig(
            provider_id="local-provider",
            model="local-model",
        ),
    )

    result = await config_router.put_agents_llm_routing(
        request=request,
        body=body,
    )

    await _drain_pending_tasks()

    assert result == body
    assert saved["routing"] == body
    assert sorted(multi_agent.reloaded) == ["agent-a", "agent-b"]


@pytest.mark.asyncio
async def test_put_global_routing_without_running_agents_is_noop(monkeypatch):
    request = _make_request(FakeMultiAgentManager([]))

    monkeypatch.setattr(
        config_router,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(),
            ),
        ),
    )
    monkeypatch.setattr(config_router, "save_config", lambda _config: None)

    await config_router.put_agents_llm_routing(
        request=request,
        body=AgentsLLMRoutingConfig(),
    )

    await _drain_pending_tasks()
