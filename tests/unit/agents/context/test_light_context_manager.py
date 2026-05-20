# -*- coding: utf-8 -*-
"""Unit tests for LightContextManager automation memory handling."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg

from qwenpaw.agents.context.light_context_manager import (
    LightContextManager,
    _should_skip_automation_memory,
)


def _agent_with_source(source: str):
    return SimpleNamespace(_request_context={"source": source})


@pytest.mark.parametrize("source", ["cron", "heartbeat", "CRON"])
def test_should_skip_automation_memory_for_system_sources(source):
    assert _should_skip_automation_memory(_agent_with_source(source)) is True


@pytest.mark.parametrize("source", ["", "console", "user"])
def test_should_not_skip_automation_memory_for_user_sources(source):
    assert _should_skip_automation_memory(_agent_with_source(source)) is False


@pytest.mark.asyncio
async def test_post_reply_skips_auto_memory_for_cron_source(tmp_path):
    manager = LightContextManager(str(tmp_path), "default")
    memory_manager = SimpleNamespace(auto_memory=AsyncMock())
    memory = SimpleNamespace(
        content=[(Msg("user", "cron task input", "user"), None)],
    )
    agent = SimpleNamespace(
        memory_manager=memory_manager,
        memory=memory,
        _request_context={"source": "cron"},
    )

    await manager.post_reply(agent, {}, None)

    memory_manager.auto_memory.assert_not_called()


@pytest.mark.asyncio
async def test_post_reply_keeps_auto_memory_for_user_source(tmp_path):
    manager = LightContextManager(str(tmp_path), "default")
    memory_manager = SimpleNamespace(auto_memory=AsyncMock())
    user_msg = Msg("user", "normal user input", "user")
    memory = SimpleNamespace(content=[(user_msg, None)])
    agent = SimpleNamespace(
        memory_manager=memory_manager,
        memory=memory,
        _request_context={"source": "user"},
    )

    await manager.post_reply(agent, {}, None)

    memory_manager.auto_memory.assert_awaited_once_with(
        all_messages=[user_msg],
    )
