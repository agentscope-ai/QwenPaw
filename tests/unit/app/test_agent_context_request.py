# -*- coding: utf-8 -*-
"""Tests for agent request context resolution."""

from types import SimpleNamespace

import pytest

from qwenpaw.app import agent_context


@pytest.mark.asyncio
async def test_agent_config_load_runs_through_sync_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offload the synchronous application config read."""
    config = SimpleNamespace(
        agents=SimpleNamespace(
            active_agent="bot",
            profiles={"bot": SimpleNamespace(enabled=True)},
        ),
    )
    workspace = SimpleNamespace(agent_id="bot")
    calls = []

    async def run_sync_io(func, *args):
        calls.append((func, args))
        return config

    class Manager:
        async def get_agent(self, agent_id):
            assert agent_id == "bot"
            return workspace

    request = SimpleNamespace(
        state=SimpleNamespace(),
        headers={},
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=Manager()),
        ),
    )
    monkeypatch.setattr(agent_context, "run_sync_io", run_sync_io)

    result = await agent_context.get_agent_for_request(request)

    assert result is workspace
    assert calls == [(agent_context.load_config, ())]
