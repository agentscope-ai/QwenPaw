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
    return agent


@pytest.mark.asyncio
async def test_process_clear_returns_clear_history_metadata() -> None:
    agent = _make_agent()
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)

    msg = await handler.handle_command("/clear")

    assert msg.metadata == {"clear_history": True, "clear_plan": True}


@pytest.mark.asyncio
async def test_system_prompt_command_returns_current_prompt() -> None:
    agent = _make_agent()

    async def _get_system_prompt() -> str:
        return "current prompt"

    # pylint: disable=protected-access
    agent._get_system_prompt = _get_system_prompt
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)

    msg = await handler.handle_command("/system_prompt")

    assert handler.is_command("/system_prompt")
    assert "current prompt" in msg.get_text_content()


def _make_config(
    *,
    compact_enabled: bool = True,
    reserve_ratio: float = 0.1,
    summarize_when_compact: bool = True,
):
    return SimpleNamespace(
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                context_compact_config=SimpleNamespace(
                    enabled=compact_enabled,
                    reserve_threshold_ratio=reserve_ratio,
                ),
            ),
            reme_light_memory_config=SimpleNamespace(
                summarize_when_compact=summarize_when_compact,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_compact_respects_disabled_config() -> None:
    agent = _make_agent()
    agent.state = SimpleNamespace(
        context=[object()],
        summary="",
    )
    agent.compress_context = MagicMock()
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)
    # pylint: disable=protected-access
    handler._get_agent_config = lambda: _make_config(compact_enabled=False)

    msg = await handler.handle_command("/compact")

    agent.compress_context.assert_not_called()
    assert "Compact skipped" in msg.get_text_content()


@pytest.mark.asyncio
async def test_compact_uses_manual_force_context_config() -> None:
    captured = {}

    async def _compress_context(context_config=None):
        captured["context_config"] = context_config
        agent.state.summary = "summary"

    agent = _make_agent()
    agent.state = SimpleNamespace(
        context=[object()],
        summary="",
    )
    agent.compress_context = _compress_context
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)
    # pylint: disable=protected-access
    handler._get_agent_config = lambda: _make_config(reserve_ratio=0.2)

    msg = await handler.handle_command("/compact")

    context_config = captured["context_config"]
    assert context_config.trigger_ratio == 0.000001
    assert context_config.reserve_ratio == 0.2
    assert "Compact Complete" in msg.get_text_content()
