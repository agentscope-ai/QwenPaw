# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.chats.history_window``.

Covers the pagination windowing used by ``GET /api/chats/{chat_id}``
(``limit`` + ``before`` cursor). Messages are stubbed with lightweight
objects so the tests stay independent of the conversion pipeline.
"""

# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace
from typing import List, Optional

from qwenpaw.app.chats.history_window import (
    apply_history_window,
    message_original_id,
)


def make_message(original_id: Optional[str]) -> SimpleNamespace:
    metadata = {"original_id": original_id} if original_id else {}
    return SimpleNamespace(metadata=metadata)


def make_history(count: int, prefix: str = "msg") -> List[SimpleNamespace]:
    return [make_message(f"{prefix}-{i}") for i in range(count)]


def ids(messages: List[SimpleNamespace]) -> List[Optional[str]]:
    return [message_original_id(m) for m in messages]


class TestMessageOriginalId:
    def test_reads_original_id(self):
        assert message_original_id(make_message("abc")) == "abc"

    def test_missing_metadata(self):
        assert message_original_id(SimpleNamespace()) is None

    def test_none_metadata(self):
        assert message_original_id(SimpleNamespace(metadata=None)) is None

    def test_non_string_value(self):
        message = SimpleNamespace(metadata={"original_id": 123})
        assert message_original_id(message) is None


class TestApplyHistoryWindow:
    def test_no_arguments_returns_everything(self):
        history = make_history(5)
        window, total, has_more = apply_history_window(history)
        assert window == history
        assert total == 5
        assert has_more is False

    def test_limit_returns_most_recent(self):
        history = make_history(5)
        window, total, has_more = apply_history_window(history, limit=2)
        assert ids(window) == ["msg-3", "msg-4"]
        assert total == 5
        assert has_more is True

    def test_limit_equal_to_length(self):
        history = make_history(3)
        window, total, has_more = apply_history_window(history, limit=3)
        assert ids(window) == ["msg-0", "msg-1", "msg-2"]
        assert total == 3
        assert has_more is False

    def test_limit_larger_than_length(self):
        history = make_history(3)
        window, total, has_more = apply_history_window(history, limit=10)
        assert len(window) == 3
        assert has_more is False

    def test_empty_history(self):
        window, total, has_more = apply_history_window([], limit=50)
        assert window == []
        assert total == 0
        assert has_more is False

    def test_before_keeps_strictly_older_messages(self):
        history = make_history(5)
        window, total, has_more = apply_history_window(history, before="msg-2")
        assert ids(window) == ["msg-0", "msg-1"]
        assert total == 5
        assert has_more is False

    def test_before_with_limit_pages_older_history(self):
        history = make_history(5)
        window, total, has_more = apply_history_window(history, limit=1, before="msg-2")
        assert ids(window) == ["msg-1"]
        assert total == 5
        assert has_more is True

    def test_before_oldest_message_returns_empty(self):
        history = make_history(4)
        window, total, has_more = apply_history_window(history, before="msg-0")
        assert window == []
        assert total == 4
        assert has_more is False

    def test_unknown_cursor_is_ignored(self):
        history = make_history(5)
        window, total, has_more = apply_history_window(
            history, limit=3, before="no-such-cursor"
        )
        assert ids(window) == ["msg-2", "msg-3", "msg-4"]
        assert total == 5
        assert has_more is True

    def test_duplicate_original_id_cuts_at_first_occurrence(self):
        # One AgentScope Msg can expand into several Message objects that
        # share the same metadata.original_id (text / reasoning / tool
        # segments). The cursor must cut before the whole group.
        history = [
            make_message("msg-0"),
            make_message("msg-1"),
            make_message("msg-1"),  # second segment of msg-1
            make_message("msg-2"),
        ]
        window, total, has_more = apply_history_window(history, before="msg-1")
        assert ids(window) == ["msg-0"]
        assert total == 4
        assert has_more is False

    def test_messages_without_original_id_are_kept(self):
        history = [
            make_message(None),
            make_message("msg-1"),
            make_message(None),
        ]
        window, total, has_more = apply_history_window(history, limit=2)
        assert len(window) == 2
        assert total == 3
        assert has_more is True
