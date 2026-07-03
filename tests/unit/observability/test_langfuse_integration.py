# -*- coding: utf-8 -*-
"""Tests for Langfuse observability integration components.

Covers:
- LangfuseTraceHook: trace scope opened in PRE_EXECUTE, skipped when disabled
- LangfuseTraceCleanupHook: trace scope closed in FINALLY phase
- LangfuseToolSpanMiddleware: tool observations created/skipped correctly
- OpenAIChatModelCompat.__call__: Langfuse kwargs injection
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from qwenpaw.observability import langfuse as lf


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


class FakeObservation:
    def __init__(self, observation_id: str):
        self.id = observation_id
        self.updates: list[dict] = []
        self.ended = False

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return self

    def end(self):
        self.ended = True
        return self


class FakeClient:
    def __init__(self):
        self.started: list[dict] = []
        self.next_id = 0

    def start_observation(self, **kwargs):
        self.started.append(kwargs)
        self.next_id += 1
        return FakeObservation(f"obs-{self.next_id}")


@pytest.fixture(autouse=True)
def reset_langfuse_context(monkeypatch):
    """Ensure clean Langfuse state for each test."""
    lf.clear_current_trace()
    monkeypatch.setattr(lf, "_langfuse_client", lambda: None)
    yield
    lf.clear_current_trace()


# ---------------------------------------------------------------------------
# Helper: build a minimal HookContext
# ---------------------------------------------------------------------------


def _make_hook_context(**overrides) -> Any:
    from qwenpaw.runtime.hooks import HookContext

    defaults = {
        "request": SimpleNamespace(user_id="u1", channel="test"),
        "session_id": "sess-1",
        "agent_id": "agent-1",
        "root_session_id": "root-sess-1",
        "root_agent_id": "root-agent-1",
        "workspace_dir": None,
        "workspace": None,
        "app_services": None,
        "input_msgs": [],
        "agent_config": None,
        "session_state": None,
        "agent": None,
        "error": None,
        "mode_state": {},
        "extras": {},
    }
    defaults.update(overrides)
    return HookContext(**defaults)


# ===========================================================================
# Tests: LangfuseTraceHook
# ===========================================================================


class TestLangfuseTraceHook:
    """LangfuseTraceHook (PRE_EXECUTE) tests."""

    async def test_skips_when_langfuse_disabled(self, monkeypatch):
        """Hook returns immediately when Langfuse is not enabled."""
        from qwenpaw.hooks.observability.langfuse_hook import LangfuseTraceHook

        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: False)
        hook = LangfuseTraceHook()
        ctx = _make_hook_context()

        result = await hook.run(ctx)

        assert not ctx.extras
        assert result.action.value == "continue"

    async def test_opens_trace_scope_when_enabled(self, monkeypatch):
        """Hook opens a Langfuse trace scope and stores it in ctx.extras."""
        from qwenpaw.hooks.observability.langfuse_hook import (
            LangfuseTraceHook,
            _LANGFUSE_SCOPE_KEY,
        )

        client = FakeClient()
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
        monkeypatch.setattr(lf, "_langfuse_client", lambda: client)

        hook = LangfuseTraceHook()
        ctx = _make_hook_context()

        await hook.run(ctx)

        assert _LANGFUSE_SCOPE_KEY in ctx.extras
        assert lf.get_current_trace() is not None
        assert lf.get_current_trace().name == "qwenpaw.agent.react_loop"
        assert len(client.started) == 1

    async def test_handles_scope_open_failure(self, monkeypatch):
        """Hook swallows exceptions from scope.__aenter__ gracefully."""
        from qwenpaw.hooks.observability.langfuse_hook import (
            LangfuseTraceHook,
            _LANGFUSE_SCOPE_KEY,
        )

        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)

        def bad_client():
            raise RuntimeError("client init failed")

        monkeypatch.setattr(lf, "_langfuse_client", bad_client)

        hook = LangfuseTraceHook()
        ctx = _make_hook_context()

        result = await hook.run(ctx)

        assert _LANGFUSE_SCOPE_KEY not in ctx.extras
        assert result.action.value == "continue"


# ===========================================================================
# Tests: LangfuseTraceCleanupHook
# ===========================================================================


class TestLangfuseTraceCleanupHook:
    """LangfuseTraceCleanupHook (FINALLY) tests."""

    async def test_noop_when_no_scope_in_extras(self):
        """Cleanup does nothing when no scope was stored."""
        from qwenpaw.hooks.observability.langfuse_hook import (
            LangfuseTraceCleanupHook,
        )

        hook = LangfuseTraceCleanupHook()
        ctx = _make_hook_context()

        result = await hook.run(ctx)

        assert result.action.value == "continue"

    async def test_closes_scope_on_success(self, monkeypatch):
        """Cleanup calls __aexit__ with None args on success."""
        from qwenpaw.hooks.observability.langfuse_hook import (
            LangfuseTraceCleanupHook,
            LangfuseTraceHook,
            _LANGFUSE_SCOPE_KEY,
        )

        client = FakeClient()
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
        monkeypatch.setattr(lf, "_langfuse_client", lambda: client)

        # Open the scope first
        open_hook = LangfuseTraceHook()
        ctx = _make_hook_context()
        await open_hook.run(ctx)

        assert _LANGFUSE_SCOPE_KEY in ctx.extras

        # Close it
        cleanup_hook = LangfuseTraceCleanupHook()
        await cleanup_hook.run(ctx)

        assert _LANGFUSE_SCOPE_KEY not in ctx.extras
        assert lf.get_current_trace() is None

    async def test_closes_scope_on_error(self, monkeypatch):
        """Cleanup passes exception info to __aexit__."""
        from qwenpaw.hooks.observability.langfuse_hook import (
            LangfuseTraceCleanupHook,
            LangfuseTraceHook,
            _LANGFUSE_SCOPE_KEY,
        )

        client = FakeClient()
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
        monkeypatch.setattr(lf, "_langfuse_client", lambda: client)

        open_hook = LangfuseTraceHook()
        ctx = _make_hook_context()
        await open_hook.run(ctx)

        # Simulate an error during execution
        ctx.error = ValueError("something broke")

        cleanup_hook = LangfuseTraceCleanupHook()
        await cleanup_hook.run(ctx)

        assert _LANGFUSE_SCOPE_KEY not in ctx.extras
        obs = client.started[0]
        assert obs["as_type"] == "span"


# ===========================================================================
# Tests: LangfuseToolSpanMiddleware
# ===========================================================================


class TestLangfuseToolSpanMiddleware:
    """LangfuseToolSpanMiddleware tests."""

    async def test_passthrough_when_no_active_trace(self, monkeypatch):
        """Middleware passes events through when no trace is active."""
        from qwenpaw.agents.middlewares import LangfuseToolSpanMiddleware

        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)

        mw = LangfuseToolSpanMiddleware()
        events_in = ["chunk1", "chunk2", "done"]

        async def fake_next_handler():
            for e in events_in:
                yield e

        collected = []
        agent = SimpleNamespace()
        input_kwargs = {
            "tool_call": SimpleNamespace(name="test", input={}, id="tc-1"),
        }

        async for event in mw.on_acting(
            agent,
            input_kwargs,
            fake_next_handler,
        ):
            collected.append(event)

        assert collected == events_in

    async def test_creates_tool_span_when_trace_active(self, monkeypatch):
        """Middleware wraps tool execution in a Langfuse tool span."""
        from agentscope.message import TextBlock
        from agentscope.tool import ToolResponse

        from qwenpaw.agents.middlewares import LangfuseToolSpanMiddleware

        client = FakeClient()
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
        monkeypatch.setattr(lf, "_langfuse_client", lambda: client)

        lf.set_current_trace(
            trace_id="trace-1",
            parent_observation_id="root-obs",
            name="agent.react_loop",
            metadata={"session_id": "s1"},
        )

        tool_response = ToolResponse(
            content=[TextBlock(type="text", text="result data")],
            id="tc-1",
        )

        async def fake_next_handler():
            yield tool_response

        mw = LangfuseToolSpanMiddleware()
        agent = SimpleNamespace()
        input_kwargs = {
            "tool_call": SimpleNamespace(
                name="execute_shell",
                input={"command": "ls"},
                id="tc-1",
            ),
        }

        collected = []
        async for event in mw.on_acting(
            agent,
            input_kwargs,
            fake_next_handler,
        ):
            collected.append(event)

        assert len(collected) == 1
        assert collected[0] is tool_response
        assert len(client.started) == 1
        assert client.started[0]["name"] == "tool.execute_shell"
        assert client.started[0]["as_type"] == "tool"


# ===========================================================================
# Tests: OpenAIChatModelCompat.__call__ Langfuse injection
# ===========================================================================


class TestOpenAIChatModelCompatLangfuseInjection:
    """Test that __call__ injects Langfuse kwargs when trace is active."""

    async def test_no_injection_when_no_trace(self, monkeypatch):
        """No Langfuse kwargs added when no trace context is active."""
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)

        captured_kwargs: dict = {}

        async def mock_super_call(*_args, **kwargs):  # noqa: ARG001
            captured_kwargs.update(kwargs)
            return SimpleNamespace(content=[])

        from qwenpaw.providers.openai_chat_model_compat import (
            OpenAIChatModelCompat,
        )

        with patch.object(
            OpenAIChatModelCompat.__mro__[1],
            "__call__",
            mock_super_call,
        ):
            model = object.__new__(OpenAIChatModelCompat)
            model.model = "qwen-max"
            await model.__call__(messages=[], tools=[])

        assert "trace_id" not in captured_kwargs

    async def test_injects_kwargs_when_trace_active(self, monkeypatch):
        """Langfuse kwargs are injected when trace context exists."""
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)

        lf.set_current_trace(
            trace_id="trace-99",
            parent_observation_id="obs-parent",
            name="agent.react_loop",
            metadata={"session_id": "s1"},
        )

        captured_kwargs: dict = {}

        async def mock_super_call(*_args, **kwargs):  # noqa: ARG001
            captured_kwargs.update(kwargs)
            return SimpleNamespace(content=[])

        from qwenpaw.providers.openai_chat_model_compat import (
            OpenAIChatModelCompat,
        )

        with patch.object(
            OpenAIChatModelCompat.__mro__[1],
            "__call__",
            mock_super_call,
        ):
            model = object.__new__(OpenAIChatModelCompat)
            model.model = "qwen-max"
            await model.__call__(messages=[], tools=[])

        assert captured_kwargs["trace_id"] == "trace-99"
        assert captured_kwargs["name"] == "llm.qwen-max"
        assert captured_kwargs["parent_observation_id"] == "obs-parent"

    async def test_caller_kwargs_override_langfuse(self, monkeypatch):
        """Explicit caller kwargs take priority over Langfuse defaults."""
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)

        lf.set_current_trace(
            trace_id="trace-99",
            parent_observation_id="obs-parent",
            name="agent.react_loop",
            metadata={},
        )

        captured_kwargs: dict = {}

        async def mock_super_call(*_args, **kwargs):  # noqa: ARG001
            captured_kwargs.update(kwargs)
            return SimpleNamespace(content=[])

        from qwenpaw.providers.openai_chat_model_compat import (
            OpenAIChatModelCompat,
        )

        with patch.object(
            OpenAIChatModelCompat.__mro__[1],
            "__call__",
            mock_super_call,
        ):
            model = object.__new__(OpenAIChatModelCompat)
            model.model = "qwen-max"
            # Pass an explicit name to override Langfuse's
            await model.__call__(
                messages=[],
                tools=[],
                name="custom-name",
            )

        assert captured_kwargs["name"] == "custom-name"
        assert captured_kwargs["trace_id"] == "trace-99"
