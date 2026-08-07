# -*- coding: utf-8 -*-
"""Focused unit tests for workspace running-config update ordering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.routers.workspace import put_agents_running_config
from qwenpaw.config import AgentsRunningConfig
from qwenpaw.config.config import AgentProfileConfig


def _embedding_update_configs():
    old_running = AgentsRunningConfig()
    new_running = old_running.model_copy(deep=True)
    old_embedding = old_running.reme_light_memory_config.embedding_model_config
    new_embedding = new_running.reme_light_memory_config.embedding_model_config
    old_embedding.api_key = "old-key"
    old_embedding.model_name = "old-model"
    new_embedding.api_key = "new-key"
    new_embedding.model_name = "new-model"
    return old_running, new_running


@pytest.mark.asyncio
async def test_running_config_persists_before_embedding_hot_update() -> None:
    old_running, new_running = _embedding_update_configs()
    events: list[str] = []

    async def apply_embedding(_config):
        events.append("apply")
        return True

    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(
        side_effect=apply_embedding,
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=memory_manager,
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    def save_config(_agent_id, _agent_config):
        events.append("save")

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.app.routers.workspace.save_agent_config",
            side_effect=save_config,
        ),
        patch(
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        response = await put_agents_running_config(
            new_running,
            MagicMock(),
        )

    assert events == ["save", "apply"]
    assert response is new_running
    schedule_reload.assert_not_called()


@pytest.mark.asyncio
async def test_running_config_save_failure_does_not_touch_runtime() -> None:
    old_running, new_running = _embedding_update_configs()
    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=True)
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=memory_manager,
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.app.routers.workspace.save_agent_config",
            side_effect=OSError("disk full"),
        ),
        patch(
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        with pytest.raises(OSError, match="disk full"):
            await put_agents_running_config(new_running, MagicMock())

    memory_manager.apply_tested_embedding.assert_not_awaited()
    schedule_reload.assert_not_called()


@pytest.mark.asyncio
async def test_embedding_hot_update_failure_falls_back_to_reload() -> None:
    old_running, new_running = _embedding_update_configs()
    events: list[str] = []

    async def apply_embedding(_config):
        events.append("apply")
        raise RuntimeError("index rebuild failed")

    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(
        side_effect=apply_embedding,
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=memory_manager,
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    def save_config(_agent_id, _agent_config):
        events.append("save")

    def schedule_reload(_request, _agent_id):
        events.append("reload")

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.app.routers.workspace.save_agent_config",
            side_effect=save_config,
        ),
        patch(
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
            side_effect=schedule_reload,
        ),
    ):
        response = await put_agents_running_config(
            new_running,
            MagicMock(),
        )

    assert events == ["save", "apply", "reload"]
    assert response is new_running
