# -*- coding: utf-8 -*-
# pylint: disable=protected-access
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
async def test_clear_resets_stop_gates_and_pending_gate_state() -> None:
    agent = _make_agent()
    mode = MagicMock()
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(
            plugins=SimpleNamespace(modes=[mode]),
        ),
        agent=agent,
    )
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        prompt_context=ctx,
    )

    await handler.handle_command("/clear")

    mode.on_conversation_reset.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_new_empty_resets_stop_gates() -> None:
    agent = _make_agent()
    mode = MagicMock()
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(
            plugins=SimpleNamespace(modes=[mode]),
        ),
        agent=agent,
    )
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        prompt_context=ctx,
    )

    await handler.handle_command("/new")

    mode.on_conversation_reset.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_new_no_mem_mgr_resets_stop_gates() -> None:
    agent = _make_agent()
    agent.state.context = [
        _msg("user", "hi"),
    ]
    mode = MagicMock()
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(
            plugins=SimpleNamespace(modes=[mode]),
        ),
        agent=agent,
    )
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        prompt_context=ctx,
    )

    msg = await handler.handle_command("/new")

    mode.on_conversation_reset.assert_called_once_with(ctx)
    assert "Memory Manager Disabled" in msg.get_text_content()


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
async def test_reme_status_reports_memory_and_count_warning() -> None:
    agent = _make_agent()
    memory_manager = MagicMock()
    memory_manager.reme_status = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            answer=(
                "Memory (estimated component object size)\n"
                "  file_store:default  12.00 MiB\n"
                "  Components total  12.00 MiB\n"
                "  Process RSS       80.00 MiB"
            ),
            metadata={"status": {"memory": {"process_rss": "80.00 MiB"}}},
        ),
    )
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )

    msg = await handler.handle_command("/reme_status")
    text = msg.get_text_content()

    assert handler.is_command("/reme_status")
    memory_manager.reme_status.assert_awaited_once_with()
    assert "Process RSS       80.00 MiB" in text
    assert "may be counted more than once" in text
    assert "EMBEDDING_STORE" in text
    assert msg.metadata == {
        "status": {"memory": {"process_rss": "80.00 MiB"}},
    }


@pytest.mark.asyncio
async def test_reme_status_requires_memory_manager() -> None:
    agent = _make_agent()
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)

    msg = await handler.handle_command("/reme_status")

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
    strategy: str = "scroll",
):
    return SimpleNamespace(
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                strategy=strategy,
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


class _FakeCtxConfig(SimpleNamespace):
    """Minimal stand-in for AgentScope's ContextConfig with model_copy()."""

    def model_copy(self, *, update):
        merged = {
            "trigger_ratio": self.trigger_ratio,
            "reserve_ratio": self.reserve_ratio,
            **update,
        }
        return _FakeCtxConfig(**merged)


@pytest.mark.asyncio
async def test_compact_uses_manual_force_context_config() -> None:
    """Under scroll, manual /compact clones the live agent's context_config,
    dropping the auto trigger but leaving the reserve tail untouched so it
    matches the same recent-tail budget as auto compaction."""
    from qwenpaw.agents.command_handler import _FORCE_TRIGGER_RATIO

    captured = {}

    async def _compress_context(context_config=None):
        captured["context_config"] = context_config
        agent.state.summary = "summary"

    agent = _make_agent()
    agent.state = SimpleNamespace(
        context=[object()],
        summary="",
    )
    agent.context_config = _FakeCtxConfig(trigger_ratio=0.8, reserve_ratio=0.2)
    agent.compress_context = _compress_context
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)
    # pylint: disable=protected-access
    handler._get_agent_config = lambda: _make_config(
        reserve_ratio=0.2,
        strategy="scroll",
    )

    msg = await handler.handle_command("/compact")

    context_config = captured["context_config"]
    assert context_config.trigger_ratio == _FORCE_TRIGGER_RATIO
    # The reserve tail is kept at the agent's configured value, not shrunk.
    assert context_config.reserve_ratio == 0.2
    # The live agent's own config is left untouched (model_copy, not mutated).
    assert agent.context_config.reserve_ratio == 0.2
    assert "Compact Complete" in msg.get_text_content()


def test_scroll_compact_detail_hides_internal_index_terms() -> None:
    index_text = (
        "===== Tier 0 (recently compressed) =====\n"
        "  [seq 2850–2852]\n"
        "    · seq 2851  ⟦ 执行 yes | head -n 3000 成功，输出 3000 行重复字符串 ⟧"
    )

    # pylint: disable=protected-access
    detail = CommandHandler._format_scroll_compact_detail(index_text)

    assert "执行 yes | head -n 3000 成功" in detail
    assert "Tier 0" not in detail
    assert "seq 2851" not in detail
    assert "live context" in detail


@pytest.mark.asyncio
async def test_compact_under_native_keeps_configured_reserve() -> None:
    """Under native, manual /compact forces the trigger but must NOT shrink the
    reserve: native compaction is lossy (the non-reserved middle is summarized
    away), so it keeps the agent's configured reserve_ratio for the same
    recent-tail continuity as auto compaction."""
    from qwenpaw.agents.command_handler import _FORCE_TRIGGER_RATIO

    captured = {}

    async def _compress_context(context_config=None):
        captured["context_config"] = context_config
        agent.state.summary = "summary"

    agent = _make_agent()
    agent.state = SimpleNamespace(
        context=[object()],
        summary="",
    )
    agent.context_config = _FakeCtxConfig(trigger_ratio=0.8, reserve_ratio=0.2)
    agent.compress_context = _compress_context
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)
    # pylint: disable=protected-access
    handler._get_agent_config = lambda: _make_config(
        reserve_ratio=0.2,
        strategy="native",
    )

    await handler.handle_command("/compact")

    context_config = captured["context_config"]
    # Trigger is still forced so the manual command always runs...
    assert context_config.trigger_ratio == _FORCE_TRIGGER_RATIO
    # ...but the reserve is left at the agent's configured value (the base),
    # NOT shrunk to the scroll-only _FORCE_RESERVE_RATIO.
    assert context_config.reserve_ratio == 0.2
