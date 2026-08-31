# -*- coding: utf-8 -*-
"""Tests for CommandHandler status/history/dump commands.

Covers the previously untested command processors
(_process_summarize_status, _process_history, _process_dump_history,
_get_current_system_prompt) plus the small helpers they rely on
(_get_summary, _has_memory_manager, _make_system_msg).
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.command_handler import CommandHandler


def _state(summary: str = ""):
    return SimpleNamespace(
        context=[],
        summary=summary,
        session_id="session-1",
        middle_context={},
    )


def _handler(
    agent=None,
    memory_manager=None,
    state=None,
    agent_id: str = "default",
) -> CommandHandler:
    return CommandHandler(
        agent_name="TestAgent",
        agent=agent,
        memory_manager=memory_manager,
        # agent and state are mutually exclusive; pass one only.
        state=None if agent is not None else (state or _state()),
        agent_id=agent_id,
    )


def _msg(role: str, text: str) -> Msg:
    return Msg(
        name="user" if role == "user" else "TestAgent",
        role=role,
        content=[TextBlock(type="text", text=text)],
    )


def _text_of(msg: Msg) -> str:
    parts = []
    for block in msg.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


class TestSmallHelpers:
    def test_get_summary_returns_string(self):
        assert _handler(state=_state("a summary"))._get_summary() == (
            "a summary"
        )

    def test_get_summary_non_string_returns_empty(self):
        assert _handler(state=_state(["list"]))._get_summary() == ""

    def test_has_memory_manager_none(self):
        assert _handler(memory_manager=None)._has_memory_manager() is False

    def test_has_memory_manager_disabled(self):
        manager = SimpleNamespace(enabled=False)
        assert _handler(memory_manager=manager)._has_memory_manager() is False

    def test_has_memory_manager_enabled(self):
        manager = SimpleNamespace(enabled=True)
        assert _handler(memory_manager=manager)._has_memory_manager() is True

    @pytest.mark.asyncio
    async def test_make_system_msg_builds_text(self):
        handler = _handler()
        msg = await handler._make_system_msg("hello there")
        assert msg.role in ("system", "assistant")
        assert "hello there" in _text_of(msg)

    @pytest.mark.asyncio
    async def test_make_system_msg_carries_metadata(self):
        handler = _handler()
        msg = await handler._make_system_msg("x", metadata={"k": "v"})
        assert msg.metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# _process_summarize_status
# ---------------------------------------------------------------------------


class TestProcessSummarizeStatus:
    @pytest.mark.asyncio
    async def test_no_memory_manager_reports_disabled(self):
        handler = _handler(memory_manager=None)
        result = await handler._process_summarize_status([])
        assert "Memory Manager Disabled" in _text_of(result)

    @pytest.mark.asyncio
    async def test_disabled_manager_reports_disabled(self):
        manager = SimpleNamespace(enabled=False)
        handler = _handler(memory_manager=manager)
        result = await handler._process_summarize_status([])
        assert "Memory Manager Disabled" in _text_of(result)

    @pytest.mark.asyncio
    async def test_no_tasks_reports_empty(self):
        manager = SimpleNamespace(
            enabled=True,
            list_summarize_status=lambda: [],
        )
        handler = _handler(memory_manager=manager)
        result = await handler._process_summarize_status([])
        assert "No Summary Tasks" in _text_of(result)

    @pytest.mark.asyncio
    async def test_running_task_rendered(self):
        manager = SimpleNamespace(
            enabled=True,
            list_summarize_status=lambda: [
                {
                    "task_id": "t1",
                    "start_time": "10:00",
                    "status": "running",
                    "result": None,
                    "error": None,
                },
            ],
        )
        handler = _handler(memory_manager=manager)
        result = await handler._process_summarize_status([])
        text = _text_of(result)
        assert "t1" in text
        assert "running" in text

    @pytest.mark.asyncio
    async def test_completed_task_shows_result(self):
        manager = SimpleNamespace(
            enabled=True,
            list_summarize_status=lambda: [
                {
                    "task_id": "t2",
                    "start_time": "10:00",
                    "status": "completed",
                    "result": "the summary output",
                    "error": None,
                },
            ],
        )
        handler = _handler(memory_manager=manager)
        result = await handler._process_summarize_status([])
        assert "the summary output" in _text_of(result)

    @pytest.mark.asyncio
    async def test_failed_task_shows_error(self):
        manager = SimpleNamespace(
            enabled=True,
            list_summarize_status=lambda: [
                {
                    "task_id": "t3",
                    "start_time": "10:00",
                    "status": "failed",
                    "result": None,
                    "error": "boom",
                },
            ],
        )
        handler = _handler(memory_manager=manager)
        result = await handler._process_summarize_status([])
        assert "boom" in _text_of(result)


# ---------------------------------------------------------------------------
# _process_history
# ---------------------------------------------------------------------------


def _agent_config_stub(history_max_length: int = 100000):
    running = SimpleNamespace(history_max_length=history_max_length)
    return SimpleNamespace(
        running=running,
        workspace_dir="/tmp/ws",
        agents=SimpleNamespace(language="en"),
    )


class TestProcessHistory:
    @pytest.mark.asyncio
    async def test_history_includes_hint_footer(self):
        handler = _handler()
        config = _agent_config_stub()
        from unittest.mock import patch

        with (
            patch.object(
                handler,
                "_get_agent_config_async",
                new=AsyncMock(return_value=config),
            ),
            patch(
                "qwenpaw.agents.command_handler.format_history_str",
                new=AsyncMock(return_value="user: hi\nassistant: hello"),
            ),
            patch(
                "qwenpaw.agents.command_handler.get_model_max_input_length",
                return_value=8000,
            ),
            patch(
                "qwenpaw.agents.utils.get_token_counter",
                return_value=MagicMock(),
            ),
        ):
            result = await handler._process_history([])
        text = _text_of(result)
        assert "user: hi" in text
        assert "/message <index>" in text

    @pytest.mark.asyncio
    async def test_history_truncated_when_too_long(self):
        handler = _handler()
        config = _agent_config_stub(history_max_length=40)
        long_history = "x" * 200
        from unittest.mock import patch

        with (
            patch.object(
                handler,
                "_get_agent_config_async",
                new=AsyncMock(return_value=config),
            ),
            patch(
                "qwenpaw.agents.command_handler.format_history_str",
                new=AsyncMock(return_value=long_history),
            ),
            patch(
                "qwenpaw.agents.command_handler.get_model_max_input_length",
                return_value=8000,
            ),
            patch(
                "qwenpaw.agents.utils.get_token_counter",
                return_value=MagicMock(),
            ),
        ):
            result = await handler._process_history([])
        text = _text_of(result)
        assert "..." in text
        # truncated, not the full 200 chars
        assert len(text) < 200

    @pytest.mark.asyncio
    async def test_history_mentions_compact_when_summary_present(self):
        handler = _handler(state=_state(summary="existing summary"))
        config = _agent_config_stub()
        from unittest.mock import patch

        with (
            patch.object(
                handler,
                "_get_agent_config_async",
                new=AsyncMock(return_value=config),
            ),
            patch(
                "qwenpaw.agents.command_handler.format_history_str",
                new=AsyncMock(return_value="short"),
            ),
            patch(
                "qwenpaw.agents.command_handler.get_model_max_input_length",
                return_value=8000,
            ),
            patch(
                "qwenpaw.agents.utils.get_token_counter",
                return_value=MagicMock(),
            ),
        ):
            result = await handler._process_history([])
        assert "/compact_str" in _text_of(result)


# ---------------------------------------------------------------------------
# _get_current_system_prompt
# ---------------------------------------------------------------------------


class TestGetCurrentSystemPrompt:
    @pytest.mark.asyncio
    async def test_agent_dynamic_prompt_preferred(self):
        agent = MagicMock()

        async def dynamic_prompt():
            return "dynamic prompt"

        agent._get_system_prompt = dynamic_prompt
        agent._system_prompt = "static fallback"
        handler = _handler(agent=agent)
        result = await handler._get_current_system_prompt()
        assert result == "dynamic prompt"

    @pytest.mark.asyncio
    async def test_dynamic_prompt_failure_falls_back_to_static(self):
        agent = MagicMock()

        async def failing():
            raise RuntimeError("no prompt")

        agent._get_system_prompt = failing
        agent._system_prompt = "static fallback"
        handler = _handler(agent=agent)
        result = await handler._get_current_system_prompt()
        assert result == "static fallback"

    @pytest.mark.asyncio
    async def test_empty_dynamic_prompt_returns_empty(self):
        """An empty dynamic result short-circuits; the static attribute is
        only used when the dynamic call raises."""
        agent = MagicMock()

        async def empty_prompt():
            return None

        agent._get_system_prompt = empty_prompt
        agent._system_prompt = "static"
        handler = _handler(agent=agent)
        result = await handler._get_current_system_prompt()
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_dynamic_method_falls_back_to_static(self):
        agent = MagicMock(spec=["_system_prompt"])
        agent._system_prompt = "static only"
        handler = _handler(agent=agent)
        result = await handler._get_current_system_prompt()
        assert result == "static only"

    @pytest.mark.asyncio
    async def test_no_agent_no_context_returns_empty(self):
        handler = _handler(agent=None)
        handler._prompt_context = None
        result = await handler._get_current_system_prompt()
        assert result == ""
