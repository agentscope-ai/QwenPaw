# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qwenpaw.agents.command_handler import CommandHandler


def _make_agent():
    """Build a minimal fake agent satisfying CommandHandler's expectations."""
    agent = MagicMock()
    agent.state = SimpleNamespace(context=[])
    agent.memory_manager = None
    agent.context_manager = None
    return agent


@pytest.mark.asyncio
async def test_process_clear_returns_clear_history_metadata() -> None:
    agent = _make_agent()
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)

    msg = await handler.handle_command("/clear")

    assert msg.metadata == {"clear_history": True, "clear_plan": True}
