# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.command_handler import CommandHandler


def _make_agent():
    """Build a minimal fake agent satisfying CommandHandler's expectations."""
    agent = MagicMock()
    agent.state = SimpleNamespace(context=[], session_id="session-1")
    agent.memory_manager = None
    return agent


def _msg(role: str, text: str, *, name: str | None = None, msg_id: str = ""):
    msg = Msg(
        name=name or ("QwenPaw" if role == "assistant" else "user"),
        role=role,
        content=[TextBlock(type="text", text=text)],
    )
    if msg_id:
        msg.id = msg_id
    return msg


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


@pytest.mark.asyncio
async def test_dream_command_runs_auto_dream_with_hint() -> None:
    agent = _make_agent()
    memory_manager = MagicMock()
    memory_manager.dream = AsyncMock()
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )

    msg = await handler.handle_command("/dream consolidate recent topics")

    assert handler.is_command("/dream")
    memory_manager.dream.assert_awaited_once_with(
        hint="consolidate recent topics",
    )
    assert "Auto-dream Complete" in msg.get_text_content()


@pytest.mark.asyncio
async def test_dream_command_requires_memory_manager() -> None:
    agent = _make_agent()
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)

    msg = await handler.handle_command("/dream")

    assert "Memory Manager Disabled" in msg.get_text_content()


@pytest.mark.asyncio
async def test_memorize_defaults_to_latest_reply_group() -> None:
    agent = _make_agent()
    agent.state.context = [
        _msg("user", "u1"),
        _msg("assistant", "a1", msg_id="r1"),
        _msg("user", "u2"),
        _msg("assistant", "a2", msg_id="r2"),
    ]
    memory_manager = MagicMock()
    memory_manager.auto_memory = AsyncMock()
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )

    msg = await handler.handle_command("/memorize")

    memory_manager.auto_memory.assert_awaited_once()
    await_args = memory_manager.auto_memory.await_args
    assert await_args is not None
    args, kwargs = await_args
    assert [m.get_text_content() for m in args[0]] == ["u2", "a2"]
    assert kwargs == {
        "session_id": "session-1",
        "reply_id": "r2",
        "reply_ids": ["r2"],
    }
    assert "Reply groups: 1" in msg.get_text_content()


@pytest.mark.asyncio
async def test_memorize_count_selects_latest_reply_groups() -> None:
    agent = _make_agent()
    agent.state.context = [
        _msg("user", "u1"),
        _msg("assistant", "a1", msg_id="r1"),
        _msg("user", "u2"),
        _msg("assistant", "a2", msg_id="r2"),
        _msg("user", "u3"),
        _msg("assistant", "a3", msg_id="r3"),
    ]
    memory_manager = MagicMock()
    memory_manager.auto_memory = AsyncMock()
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )

    msg = await handler.handle_command("/memorize 2")

    memory_manager.auto_memory.assert_awaited_once()
    await_args = memory_manager.auto_memory.await_args
    assert await_args is not None
    args, kwargs = await_args
    assert [m.get_text_content() for m in args[0]] == [
        "u2",
        "a2",
        "u3",
        "a3",
    ]
    assert kwargs["reply_id"] == "r3"
    assert kwargs["reply_ids"] == ["r2", "r3"]
    assert "Reply groups: 2" in msg.get_text_content()


@pytest.mark.asyncio
async def test_memorize_falls_back_to_assistant_replies_by_role() -> None:
    agent = _make_agent()
    agent.state.context = [
        _msg("user", "u1"),
        _msg("assistant", "a1", name="ConfiguredName", msg_id="r1"),
        _msg("user", "u2"),
        _msg("assistant", "a2", name="ConfiguredName", msg_id="r2"),
    ]
    memory_manager = MagicMock()
    memory_manager.auto_memory = AsyncMock()
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )

    msg = await handler.handle_command("/memorize")

    memory_manager.auto_memory.assert_awaited_once()
    await_args = memory_manager.auto_memory.await_args
    assert await_args is not None
    args, kwargs = await_args
    assert [m.get_text_content() for m in args[0]] == ["u2", "a2"]
    assert kwargs["reply_id"] == "r2"
    assert kwargs["reply_ids"] == ["r2"]
    assert "Reply groups: 1" in msg.get_text_content()


@pytest.mark.asyncio
async def test_memorize_one_matches_explicit_one() -> None:
    agent = _make_agent()
    agent.state.context = [
        _msg("user", "u1"),
        _msg("assistant", "a1", msg_id="r1"),
    ]
    memory_manager = MagicMock()
    memory_manager.auto_memory = AsyncMock()
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )

    await handler.handle_command("/memorize 1")

    memory_manager.auto_memory.assert_awaited_once()
    await_args = memory_manager.auto_memory.await_args
    assert await_args is not None
    args, kwargs = await_args
    assert [m.get_text_content() for m in args[0]] == ["u1", "a1"]
    assert kwargs["reply_ids"] == ["r1"]


@pytest.mark.asyncio
async def test_memorize_rejects_invalid_count() -> None:
    agent = _make_agent()
    memory_manager = MagicMock()
    memory_manager.auto_memory = AsyncMock()
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )

    msg = await handler.handle_command("/memorize two")

    memory_manager.auto_memory.assert_not_awaited()
    assert "Invalid Count" in msg.get_text_content()


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
