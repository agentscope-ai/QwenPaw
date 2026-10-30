# -*- coding: utf-8 -*-
"""Tests for the shared channel quote-context prefix recognizer.

Channels prepend the quoted (replied-to) message as a
``[quoted ...]`` block before the user's own text. Command routing
consumers strip that prefix with ``strip_quote_context_prefix``
(see issue #8342).
"""

from __future__ import annotations

import pytest

from qwenpaw.utils.quote_context import strip_quote_context_prefix


class TestStripQuoteContextPrefix:
    """Core contract of the shared quote-context recognizer."""

    @pytest.mark.parametrize(
        "text",
        [
            "/stop",
            "/daemon status",
            "normal chat without any prefix",
            "[other tag] /stop",
            "mid-text [quoted message: x] stays as-is",
        ],
    )
    def test_text_without_prefix_unchanged(self, text: str) -> None:
        assert strip_quote_context_prefix(text) == text

    def test_none_becomes_empty(self) -> None:
        assert strip_quote_context_prefix(None) == ""

    def test_empty_becomes_empty(self) -> None:
        assert strip_quote_context_prefix("") == ""

    def test_quoted_command_reply_resolves_user_text(self) -> None:
        text = "[quoted message: Alice: quarterly report]\n/stop"
        assert strip_quote_context_prefix(text) == "/stop"

    def test_quoted_daemon_command_with_indent(self) -> None:
        text = "[quoted message: Alice: quarterly report]\n  /daemon status"
        assert strip_quote_context_prefix(text) == "/daemon status"

    def test_multiline_quoted_content(self) -> None:
        text = "[quoted message: line one\nline two]\n/stop"
        assert strip_quote_context_prefix(text) == "/stop"

    def test_prefix_without_content(self) -> None:
        text = "[quoted message]\n/stop"
        assert strip_quote_context_prefix(text) == "/stop"

    def test_media_failure_prefix_alone(self) -> None:
        text = "[quoted media: download failed]"
        assert strip_quote_context_prefix(text) == ""

    def test_stacked_prefixes(self) -> None:
        text = (
            "[quoted media: download failed]\n"
            "[quoted message: Alice: quarterly report]\n"
            "/stop"
        )
        assert strip_quote_context_prefix(text) == "/stop"

    def test_command_only_inside_quote_stays_out(self) -> None:
        # The user's own text is not a command; only the quoted content
        # contains one. The remaining text must not start with "/".
        text = "[quoted message: /stop]\nare you there?"
        assert strip_quote_context_prefix(text) == "are you there?"

    def test_quote_only_reply_has_no_user_text(self) -> None:
        # Replying with only a quoted message (no new text) must not
        # resurrect the quoted content as the user's own command.
        text = "[quoted message: /stop]"
        assert strip_quote_context_prefix(text) == ""

    def test_bracket_inside_quoted_content_degrades_safely(self) -> None:
        # The recognizer matches up to the first "]"; a quoted content
        # containing "]" leaves a remainder that does not start with the
        # prefix — the safe outcome for command classification.
        text = "[quoted message: a]b]\n/stop"
        assert strip_quote_context_prefix(text) == "b]\n/stop"
