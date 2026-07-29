# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,wrong-import-position
"""Tests for ToolSanitizerMiddleware and _sanitize_tool_messages pipeline.

Regression coverage for Issue #6407: orphan tool_result messages reaching
the model call because ``compress_context`` was not triggered (context
under the size threshold) or because the corruption was introduced
between compression and the model call by another middleware.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest
from agentscope.message import (
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
)

# Stub optional heavy deps so the test file imports without full env
html2text_stub = types.ModuleType("html2text")
html2text_stub.HTML2Text = type("HTML2Text", (), {})
sys.modules.setdefault("html2text", html2text_stub)

from qwenpaw.agents.middlewares import (  # noqa: E402
    ToolSanitizerMiddleware,
)
from qwenpaw.agents.utils.tool_message_utils import (  # noqa: E402
    _sanitize_tool_messages,
    extract_tool_ids,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_tool_blocks(msgs: list) -> tuple[int, int]:
    """Return (tool_call_count, tool_result_count) across the list."""
    calls = 0
    results = 0
    for m in msgs:
        c, r = extract_tool_ids(m)
        calls += len(c)
        results += len(r)
    return calls, results


def _msg(role: str, blocks: list) -> Msg:
    return Msg(name=role, role=role, content=list(blocks))


def _call_block(cid: str, name: str = "t") -> ToolCallBlock:
    return ToolCallBlock(
        type="tool_call",
        id=cid,
        name=name,
        input="{}",
        state=ToolCallState.FINISHED,
    )


def _result_block(
    cid: str,
    name: str = "t",
    text: str = "ok",
) -> ToolResultBlock:
    return ToolResultBlock(
        type="tool_result",
        id=cid,
        name=name,
        output=[TextBlock(type="text", text=text)],
        state=ToolResultState.SUCCESS,
    )


# ---------------------------------------------------------------------------
# _sanitize_tool_messages regression tests
# ---------------------------------------------------------------------------


class TestSanitizeToolMessages:
    def test_orphan_result_is_removed(self):
        """An orphan tool_result with no tool_call anywhere must be dropped."""
        msgs = [
            _msg("user", [TextBlock(type="text", text="u")]),
            _msg("assistant", [TextBlock(type="text", text="a")]),
            _msg("assistant", [_result_block("orphan-1", text="ghost")]),
        ]
        sanitized = _sanitize_tool_messages(msgs)
        calls, results = _count_tool_blocks(sanitized)
        assert calls == 0
        assert results == 0

    def test_valid_pair_survives(self):
        """A well-formed call→result pair must survive the pipeline."""
        msgs = [
            _msg("user", [TextBlock(type="text", text="u")]),
            _msg(
                "assistant",
                [TextBlock(type="text", text="checking"), _call_block("c1")],
            ),
            _msg("assistant", [_result_block("c1", text="content")]),
        ]
        sanitized = _sanitize_tool_messages(msgs)
        calls, results = _count_tool_blocks(sanitized)
        assert calls == 1
        assert results == 1

    def test_self_paired_survives(self):
        """AgentScope 2.0 self-paired (call+result in same msg) survives."""
        msgs = [
            _msg("user", [TextBlock(type="text", text="u")]),
            _msg(
                "assistant",
                [
                    TextBlock(type="text", text="ok"),
                    _call_block("self-1"),
                    _result_block("self-1", text="done"),
                ],
            ),
        ]
        sanitized = _sanitize_tool_messages(msgs)
        calls, results = _count_tool_blocks(sanitized)
        assert calls == 1
        assert results == 1

    def test_mixed_orphans_and_valid(self):
        """Valid pairs kept; only the orphans removed."""
        msgs = [
            _msg("user", [TextBlock(type="text", text="u")]),
            _msg(
                "assistant",
                [TextBlock(type="text", text="a"), _call_block("v1")],
            ),
            _msg("assistant", [_result_block("v1", text="good")]),
            # orphan
            _msg("assistant", [_result_block("orphan-x", text="bad")]),
        ]
        sanitized = _sanitize_tool_messages(msgs)
        calls, results = _count_tool_blocks(sanitized)
        assert calls == 1
        assert results == 1


# ---------------------------------------------------------------------------
# ToolSanitizerMiddleware regression tests
# ---------------------------------------------------------------------------


class TestToolSanitizerMiddleware:
    @pytest.mark.asyncio
    async def test_middleware_strips_orphan_on_model_call(self):
        """Even if a previous middleware produced a corrupted message list,
        ToolSanitizerMiddleware must sanitize it before the provider call.
        """
        mw = ToolSanitizerMiddleware()

        seen: list = []

        async def fake_handler(**kw: Any) -> dict:
            seen.extend(kw.get("messages") or [])
            return {"choices": []}

        class FakeAgent:
            class state:
                context: list = []

            name = "sanitizer-test"

        msgs_in = [
            _msg("user", [TextBlock(type="text", text="u")]),
            _msg("assistant", [TextBlock(type="text", text="a")]),
            _msg("assistant", [_result_block("leaked-orphan", text="xxx")]),
        ]
        await mw.on_model_call(
            FakeAgent(),
            {"messages": list(msgs_in)},
            fake_handler,
        )
        _, results = _count_tool_blocks(seen)
        assert (
            results == 0
        ), "Middleware must drop orphan tool_result before model call"

    @pytest.mark.asyncio
    async def test_middleware_keeps_valid_pairs(self):
        mw = ToolSanitizerMiddleware()
        seen: list = []

        async def fake_handler(**kw: Any) -> dict:
            seen.extend(kw.get("messages") or [])
            return {"choices": []}

        class FakeAgent:
            class state:
                context: list = []

            name = "sanitizer-test-2"

        msgs_in = [
            _msg("user", [TextBlock(type="text", text="u")]),
            _msg(
                "assistant",
                [TextBlock(type="text", text="ok"), _call_block("c-ok")],
            ),
            _msg("assistant", [_result_block("c-ok", text="done")]),
        ]
        await mw.on_model_call(
            FakeAgent(),
            {"messages": list(msgs_in)},
            fake_handler,
        )
        calls, results = _count_tool_blocks(seen)
        assert calls == 1
        assert results == 1

    @pytest.mark.asyncio
    async def test_middleware_sanitizer_exceptions_do_not_crash(self):
        """If sanitize() itself raises (e.g. unexpected message shape) the
        middleware must fall through to the next handler rather than
        crashing the reasoning loop.
        """
        mw = ToolSanitizerMiddleware()

        class Broken:
            """A list-lookalike that raises during iteration inside
            sanitize to simulate a corrupt message shape.
            """

            def __len__(self):
                return 1

            def __iter__(self):
                raise RuntimeError("intentional boom")

            def __getitem__(self, _i):
                raise RuntimeError("intentional boom")

        called = False

        async def fake_handler(**kw: Any) -> dict:
            nonlocal called
            called = True
            return {"choices": []}

        class FakeAgent:
            class state:
                context: list = []

            name = "sanitizer-test-3"

        await mw.on_model_call(
            FakeAgent(),
            {"messages": Broken()},
            fake_handler,
        )
        assert called, "Middleware must fall through on sanitize exception"
