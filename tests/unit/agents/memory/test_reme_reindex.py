# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ReMe index maintenance after embedding changes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.config.config import AgentProfileConfig


@pytest.mark.asyncio
async def test_manual_reindex_clears_persisted_requirement() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager._reindex_lock = asyncio.Lock()
    manager.agent_id = "bot"
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="ok"),
    )
    profile = AgentProfileConfig(id="bot", name="Bot")
    profile.running.reme_light_memory_config.needs_reindex = True

    with (
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
            return_value=profile,
        ),
        patch(
            "qwenpaw.agents.memory.reme_light_memory_manager.save_agent_config",
        ) as save_config,
    ):
        response = await manager.rebuild_index()

    assert response.success is True
    assert profile.running.reme_light_memory_config.needs_reindex is False
    save_config.assert_called_once_with("bot", profile)
