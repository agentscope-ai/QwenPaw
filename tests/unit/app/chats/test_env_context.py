# -*- coding: utf-8 -*-
"""Unit tests for environment context and dynamic time injection.

Covers:

- ``build_env_context()`` no longer includes a static ``Current date``
  so that prompt caching benefits from stable env context.
- ``Runtime._inject_current_time()`` prepends a dynamic timestamp to
  the last user message *after* slash-command dispatch, leaving the
  raw text untouched for hooks and commands.
"""
# pylint: disable=protected-access,redefined-outer-name
# pylint: disable=unused-argument,wrong-import-position
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from qwenpaw.app.chats.utils import build_env_context
from qwenpaw.runtime.runtime import Runtime


# ---------------------------------------------------------------------------
# _inject_current_time helpers
# ---------------------------------------------------------------------------


def _make_user_msg(content: list[dict[str, str]]) -> Any:
    """Create a minimal Msg-like object that represents a user message."""
    return SimpleNamespace(role="user", content=content)


def _make_assistant_msg() -> Any:
    """Create a minimal Msg-like object for a non-user message."""
    return SimpleNamespace(
        role="assistant",
        content=[{"type": "text", "text": "ok"}],
    )


# ---------------------------------------------------------------------------
# build_env_context — must NOT contain a static current date
# ---------------------------------------------------------------------------


class TestBuildEnvContext:
    """The env context string should be stable across requests."""

    def test_no_current_date_field(self) -> None:
        """``build_env_context()`` must not contain a ``Current date`` line."""
        ctx = build_env_context(session_id="s1", user_id="u1", add_hint=True)
        assert "Current date" not in ctx, (
            "build_env_context() should no longer inject a static "
            "current date.  Dynamic time is handled by "
            "Runtime._inject_current_time()."
        )

    def test_stable_across_calls(self) -> None:
        """Without time injection the env context should be identical."""
        ctx1 = build_env_context(
            session_id="s1",
            user_id="u1",
            working_dir="/tmp",
            add_hint=True,
        )
        ctx2 = build_env_context(
            session_id="s1",
            user_id="u1",
            working_dir="/tmp",
            add_hint=True,
        )
        assert ctx1 == ctx2, (
            "build_env_context() returned different values for the "
            "same arguments — it should be deterministic."
        )


# ---------------------------------------------------------------------------
# _inject_current_time — dynamic time prefix on the last user message
# ---------------------------------------------------------------------------


class TestInjectCurrentTime:
    """``Runtime._inject_current_time()`` prepends time to user text."""

    def test_prepends_to_text_block(self) -> None:
        """A normal text-only user message gets a ``Current time:`` prefix."""
        msgs = [
            _make_assistant_msg(),
            _make_user_msg([{"type": "text", "text": "hello"}]),
        ]
        Runtime._inject_current_time(msgs)  # type: ignore[arg-type]
        text = msgs[-1].content[0]["text"]
        assert text.startswith(
            "Current time:",
        ), f"Expected text to start with 'Current time:', got {text!r}"
        # Original content should appear after the prefix
        assert text.rstrip().endswith(
            "hello",
        ), f"Expected original text 'hello' to be preserved, got {text!r}"

    def test_inserts_text_block_for_media_only(self) -> None:
        """Inserts text block when user msg has no text block."""
        msgs = [
            _make_assistant_msg(),
            _make_user_msg(
                [
                    {
                        "type": "image_url",
                        "image_url": "data:img/png;base64,abc",
                    },
                ],
            ),
        ]
        Runtime._inject_current_time(msgs)  # type: ignore[arg-type]
        content = msgs[-1].content
        assert content[0]["type"] == "text"
        assert content[0]["text"].startswith("Current time:")
        # The original image block should still be present
        assert any(b.get("type") == "image_url" for b in content)

    def test_ignores_non_user_messages(self) -> None:
        """Only last user message is modified; assistant keeps raw text."""
        msgs = [
            _make_assistant_msg(),
            _make_user_msg([{"type": "text", "text": "user says hi"}]),
        ]
        Runtime._inject_current_time(msgs)  # type: ignore[arg-type]
        assert (
            msgs[0].content[0]["text"] == "ok"
        ), "Assistant message should not be modified."
        assert msgs[1].content[0]["text"].startswith("Current time:")

    def test_timestamp_format_english(self) -> None:
        """The weekday should be in English (``strftime('%A')``)."""
        msgs = [_make_user_msg([{"type": "text", "text": "test"}])]
        Runtime._inject_current_time(msgs)  # type: ignore[arg-type]
        text = msgs[0].content[0]["text"]
        # Should contain something like "(Wednesday)" not "(星期三)"
        assert "(" in text and ")" in text
        weekday_part = text[text.rfind("(") + 1 : text.rfind(")")]
        # Should not be Chinese
        assert not any(
            "\u4e00" <= c <= "\u9fff" for c in weekday_part
        ), f"Weekday should be English, got {weekday_part!r}"

    def test_empty_message_list(self) -> None:
        """An empty message list should not raise."""
        Runtime._inject_current_time([])  # type: ignore[arg-type]

    def test_no_role_attribute(self) -> None:
        """Messages without a ``role`` are skipped gracefully."""
        msgs = [SimpleNamespace(content=[{"type": "text", "text": "no role"}])]
        Runtime._inject_current_time(msgs)  # type: ignore[arg-type]
        # Should not crash and should not modify the non-role message
        assert msgs[0].content[0]["text"] == "no role"
