# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agentscope.message import Msg, TextBlock

from qwenpaw.app.chats.utils import (
    _abspath_from_url,
    _is_local_file_url,
    _normalize_msg_timestamp,
    _resolve_content_url,
    agentscope_msg_to_message,
    clean_display_text,
    strip_injected_skill_block,
)
from qwenpaw.app.chats.title_generator import _clean_title
from qwenpaw.constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    SCROLL_MEMORY_MESSAGE_TAG,
    SYNTHETIC_USER_MESSAGE_TAGS,
)
from qwenpaw.runtime.reply_cycle import set_reply_block_metadata


def test_display_headline_cleanup_is_only_for_assistant_text():
    text = "literal document\n⟦ a quoted line ⟧"
    for role in ("user", "tool", "system"):
        assert clean_display_text(text, role) == text
    assert clean_display_text("answer\n⟦ index ⟧", "assistant") == "answer"


# ---------------------------------------------------------------------------
# _is_local_file_url
# ---------------------------------------------------------------------------


def test_is_local_file_url_file_scheme():
    assert _is_local_file_url("file:///tmp/x.txt") is True


def test_is_local_file_url_unix_path():
    assert _is_local_file_url("/home/user/doc.pdf") is True


def test_is_local_file_url_windows_path():
    assert _is_local_file_url("C:\\Users\\doc.pdf") is True


def test_is_local_file_url_rejects_http():
    assert _is_local_file_url("https://example.com/f") is False


def test_is_local_file_url_rejects_data_uri():
    assert _is_local_file_url("data:image/png;base64,abc") is False


def test_is_local_file_url_rejects_empty():
    assert _is_local_file_url("") is False


# ---------------------------------------------------------------------------
# _abspath_from_url
# ---------------------------------------------------------------------------


def test_abspath_from_file_url():
    assert _abspath_from_url("file:///tmp/x.txt") == "/tmp/x.txt"


def test_abspath_from_bare_path():
    assert _abspath_from_url("/tmp/x.txt") == "/tmp/x.txt"


def test_abspath_decodes_percent():
    assert (
        _abspath_from_url("file:///path/my%20file.txt") == "/path/my file.txt"
    )


def test_abspath_removes_windows_drive_uri_prefix():
    assert (
        _abspath_from_url("file:///D:/tmp/screen.png") == "D:/tmp/screen.png"
    )


# ---------------------------------------------------------------------------
# _resolve_content_url
# ---------------------------------------------------------------------------


def test_resolve_local_returns_abspath():
    assert _resolve_content_url("file:///tmp/x.txt") == "/tmp/x.txt"


def test_resolve_remote_passthrough():
    assert (
        _resolve_content_url("https://example.com/f")
        == "https://example.com/f"
    )


# ---------------------------------------------------------------------------
# strip_injected_skill_block
# ---------------------------------------------------------------------------


def test_strip_skill_block_removes_user_skill():
    text = "/hello<skill name='greeter'>expanded content</skill>"
    result = strip_injected_skill_block(text, "user")
    assert "<skill" not in result
    assert "/hello" in result


def test_strip_skill_block_skips_non_user_role():
    text = "some text<skill name='x'>content</skill>"
    assert strip_injected_skill_block(text, "assistant") == text


def test_strip_skill_block_skips_when_no_skill_tag():
    assert strip_injected_skill_block("plain text", "user") == "plain text"


# ---------------------------------------------------------------------------
# clean_display_text — headline hidden in the HTTP history path too
# ---------------------------------------------------------------------------


def test_clean_display_text_strips_headline_comment():
    text = "done\n<!-- ⟦ milestone here ⟧ -->"
    assert clean_display_text(text, "assistant") == "done"


def test_clean_display_text_strips_lookalike_brackets():
    # Qwen substitutes U+301A/U+301B for the intended U+27E6/U+27E7.
    assert clean_display_text("ok\n〚 lookalike 〛", "assistant") == "ok"


def test_clean_display_text_keeps_plain_text():
    assert clean_display_text("hello world", "user") == "hello world"


def test_clean_display_text_preserves_user_suffix_not_owned_by_scroll():
    text = "/run<skill name='x'>body</skill>\n<!-- ⟦ h ⟧ -->"
    assert clean_display_text(text, "user") == text


def test_msg_to_message_hides_headline_in_history_path():
    """Regression: the GET /chats/{id} path now strips the ⟦…⟧ headline, so it
    no longer reappears after navigating away from the chat and back."""
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": "all set\n<!-- ⟦ shipped ⟧ -->"}],
    )
    [message] = agentscope_msg_to_message(msg)
    rendered = "".join(c.text for c in message.content)
    assert "⟦" not in rendered and "shipped" not in rendered
    assert "all set" in rendered


def test_msg_to_message_omits_runtime_hints_from_history():
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            {
                "type": "hint",
                "hint": (
                    "<system-reminder>private runtime state"
                    "</system-reminder>"
                ),
                "source": '{"label": "System"}',
            },
            {"type": "text", "text": "visible answer"},
        ],
    )

    [message] = agentscope_msg_to_message(msg)
    rendered = "".join(c.text for c in message.content)
    assert rendered == "visible answer"
    assert "system-reminder" not in rendered


def test_msg_to_message_omits_tagged_scroll_memory_placeholder():
    placeholder = Msg(
        name="memory",
        role="user",
        content=[
            {
                "type": "text",
                "text": "<system-info>private model context</system-info>",
            },
        ],
        metadata={
            QWENPAW_MESSAGE_TAG_KEY: SCROLL_MEMORY_MESSAGE_TAG,
        },
    )

    assert not agentscope_msg_to_message(placeholder)


def test_msg_to_message_omits_legacy_scroll_memory_placeholder():
    placeholder = Msg(
        name="memory",
        role="user",
        content=[
            {
                "type": "text",
                "text": (
                    "<system-info>\n"
                    "[context compressed] archived map\n"
                    "</system-info>"
                ),
            },
        ],
    )

    assert not agentscope_msg_to_message(placeholder)


def test_msg_to_message_preserves_user_discussion_of_compressed_context():
    user_msg = Msg(
        name="user",
        role="user",
        content=[
            {
                "type": "text",
                "text": (
                    "Why does <system-info> contain " "[context compressed]?"
                ),
            },
        ],
    )

    [message] = agentscope_msg_to_message(user_msg)
    rendered = "".join(c.text for c in message.content)
    assert "[context compressed]" in rendered


def test_msg_to_message_preserves_ordinary_memory_named_message():
    user_msg = Msg(
        name="memory",
        role="user",
        content=[{"type": "text", "text": "remember this preference"}],
    )

    [message] = agentscope_msg_to_message(user_msg)
    rendered = "".join(c.text for c in message.content)
    assert rendered == "remember this preference"


def test_msg_to_message_omits_synthetic_user_stubs():
    """Runtime-injected user-role stubs (auto-continue, loop continuation,
    rubric evaluation) are model-only context. Rendering them as user cards
    made the original instruction appear rewritten after a session switch."""
    for tag in SYNTHETIC_USER_MESSAGE_TAGS:
        stub = Msg(
            name="user",
            role="user",
            content=[
                {"type": "text", "text": "Continue working on the task."},
            ],
            metadata={QWENPAW_MESSAGE_TAG_KEY: tag},
        )
        assert not agentscope_msg_to_message(stub), tag


def test_msg_to_message_omits_visual_compression_placeholders():
    """Visual-compression collapse rewrites history into user-role
    ``visual_history`` messages. They are model-only
    reconstructions, never the user's transcript."""
    collapsed = Msg(
        name="visual_history",
        role="user",
        content=[
            {"type": "text", "text": "[pages 1-3 of prior history]"},
        ],
    )
    assert not agentscope_msg_to_message(collapsed)


def test_msg_to_message_keeps_user_message_with_unknown_tag():
    user_msg = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "real question"}],
        metadata={QWENPAW_MESSAGE_TAG_KEY: "some_future_tag"},
    )

    [message] = agentscope_msg_to_message(user_msg)
    rendered = "".join(c.text for c in message.content)
    assert rendered == "real question"


def test_msg_to_message_keeps_assistant_message_with_synthetic_tag():
    """The synthetic-tag filter is scoped to user-role stubs only."""
    tag = next(iter(SYNTHETIC_USER_MESSAGE_TAGS))
    assistant_msg = Msg(
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": "still working"}],
        metadata={QWENPAW_MESSAGE_TAG_KEY: tag},
    )

    [message] = agentscope_msg_to_message(assistant_msg)
    rendered = "".join(c.text for c in message.content)
    assert rendered == "still working"


def test_history_batch_hides_scroll_internals_but_keeps_transcript():
    """A reloaded compacted session exposes only real conversation turns."""
    messages = [
        Msg(
            name="memory",
            role="user",
            content=[
                {
                    "type": "text",
                    "text": (
                        "<system-info>\n"
                        "[context compressed] private continuation state\n"
                        "</system-info>"
                    ),
                },
            ],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: SCROLL_MEMORY_MESSAGE_TAG,
            },
        ),
        Msg(
            name="user",
            role="user",
            content=[{"type": "text", "text": "keep this request visible"}],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "text",
                    "text": (
                        "keep this answer visible\n"
                        "⟦ private retrieval headline ⟧"
                    ),
                },
            ],
        ),
    ]

    rendered_messages = agentscope_msg_to_message(messages)
    rendered_text = "\n".join(
        content.text
        for message in rendered_messages
        for content in message.content
    )

    assert len(rendered_messages) == 2
    assert "keep this request visible" in rendered_text
    assert "keep this answer visible" in rendered_text
    assert "system-info" not in rendered_text
    assert "private continuation state" not in rendered_text
    assert "private retrieval headline" not in rendered_text


# ---------------------------------------------------------------------------
# message timestamp normalization
# ---------------------------------------------------------------------------


def test_normalize_msg_timestamp_naive_process_utc_to_shanghai():
    """Docker/UTC process: naive wall clock is UTC (#6301)."""
    shanghai = ZoneInfo("Asia/Shanghai")
    with patch(
        "qwenpaw.app.chats.utils._process_local_tz",
        return_value=ZoneInfo("UTC"),
    ):
        assert (
            _normalize_msg_timestamp("2026-08-10 12:52:57.000000", shanghai)
            == "2026-08-10T20:52:57+08:00"
        )


def test_normalize_msg_timestamp_naive_process_shanghai_no_drift():
    """Desktop Asia/Shanghai: naive wall clock stays on the same face."""
    shanghai = ZoneInfo("Asia/Shanghai")
    with patch(
        "qwenpaw.app.chats.utils._process_local_tz",
        return_value=shanghai,
    ):
        assert (
            _normalize_msg_timestamp("2026-08-10 12:52:57.000000", shanghai)
            == "2026-08-10T12:52:57+08:00"
        )


def test_normalize_msg_timestamp_aware_keeps_instant():
    shanghai = ZoneInfo("Asia/Shanghai")
    assert (
        _normalize_msg_timestamp("2026-08-10T04:52:57+00:00", shanghai)
        == "2026-08-10T12:52:57+08:00"
    )


def test_normalize_msg_timestamp_invalid_passthrough():
    shanghai = ZoneInfo("Asia/Shanghai")
    assert _normalize_msg_timestamp("not-a-date", shanghai) == "not-a-date"


def test_agentscope_msg_to_message_timestamp_uses_process_local_tz():
    """End-to-end through agentscope_msg_to_message (Shanghai process)."""
    msg = Msg(
        name="user",
        role="user",
        content=[
            {
                "type": "text",
                "text": "hi",
                "created_at": "2026-08-10T12:52:57.000000",
            },
        ],
        created_at="2026-08-10T12:52:57.000000",
    )
    shanghai = ZoneInfo("Asia/Shanghai")
    with (
        patch(
            "qwenpaw.app.chats.utils.load_config",
            return_value=SimpleNamespace(user_timezone="Asia/Shanghai"),
        ),
        patch(
            "qwenpaw.app.chats.utils._process_local_tz",
            return_value=shanghai,
        ),
    ):
        [message] = agentscope_msg_to_message(msg)

    assert message.metadata["timestamp"] == "2026-08-10T12:52:57+08:00"
    # Wall-clock must not drift into the future relative to the source.
    converted = datetime.fromisoformat(message.metadata["timestamp"])
    assert converted.hour == 12
    assert converted.tzinfo is not None


def test_agentscope_msg_to_message_uses_each_block_created_at():
    msg = Msg(
        name="assistant",
        role="assistant",
        created_at="2026-08-25T14:14:57.338880",
        content=[
            {
                "type": "thinking",
                "thinking": "first",
                "created_at": "2026-08-25T14:14:58.000000",
            },
            {
                "type": "tool_call",
                "id": "call-1",
                "name": "shell",
                "input": '{"command":"dir"}',
                "created_at": "2026-08-25T14:15:00.000000",
            },
            {
                "type": "text",
                "text": "done",
                "created_at": "2026-08-25T14:15:47.510253",
            },
        ],
    )
    shanghai = ZoneInfo("Asia/Shanghai")
    with (
        patch(
            "qwenpaw.app.chats.utils.load_config",
            return_value=SimpleNamespace(user_timezone="Asia/Shanghai"),
        ),
        patch(
            "qwenpaw.app.chats.utils._process_local_tz",
            return_value=shanghai,
        ),
    ):
        messages = agentscope_msg_to_message(msg)

    assert [message.metadata["timestamp"] for message in messages] == [
        "2026-08-25T14:14:58+08:00",
        "2026-08-25T14:15:00+08:00",
        "2026-08-25T14:15:47.510253+08:00",
    ]


def test_history_message_ids_are_stable_and_keep_distinct_occurrences():
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            {"type": "text", "text": "started"},
            {
                "type": "tool_call",
                "id": "call-1",
                "name": "shell",
                "input": "{}",
            },
            {"type": "text", "text": "finished"},
        ],
    )
    before = agentscope_msg_to_message(msg)
    replay = agentscope_msg_to_message(
        Msg.from_dict(msg.model_dump(mode="json")),
    )
    assert [item.id for item in before] == [item.id for item in replay]
    assert len({item.id for item in before}) == 3
    later = TextBlock(text="later")
    msg.content.append(later)
    set_reply_block_metadata(msg, later, {"timeline_order": 9})
    grown = agentscope_msg_to_message(msg)
    assert [item.id for item in grown[:3]] == [item.id for item in before]
    assert len({item.id for item in grown}) == 4
    segment_block = TextBlock(text="another reply")
    segment = Msg(
        id=msg.id,
        name="assistant",
        role="assistant",
        content=[segment_block],
    )
    set_reply_block_metadata(segment, segment_block, {"timeline_order": 10})
    segmented = agentscope_msg_to_message([msg, segment])
    assert len({item.id for item in segmented}) == len(segmented)
    restored_segment = Msg(
        id=msg.id,
        name="assistant",
        role="assistant",
        content=[msg.content[-1]],
    )
    assert agentscope_msg_to_message(restored_segment)[0].id == grown[-1].id
    repeated_text = Msg(
        name="user",
        role="user",
        content=[TextBlock(text="same words")],
    )
    other_turn = Msg(
        name="user",
        role="user",
        content=[TextBlock(text="same words")],
    )
    assert (
        agentscope_msg_to_message(repeated_text)[0].id
        != agentscope_msg_to_message(other_turn)[0].id
    )


def test_agentscope_msg_to_message_preserves_each_block_metadata():
    started = TextBlock(text="started")
    finished = TextBlock(text="finished")
    msg = Msg(
        name="assistant",
        role="assistant",
        metadata={"run_id": "run-1"},
        content=[started, finished],
    )
    set_reply_block_metadata(
        msg,
        started,
        {"timeline_group_id": "input-1", "timeline_order": 2},
    )
    set_reply_block_metadata(
        msg,
        finished,
        {"timeline_group_id": "input-1", "timeline_order": 5},
    )

    messages = agentscope_msg_to_message(msg)

    assert [message.content[0].text for message in messages] == [
        "started",
        "finished",
    ]
    assert [
        message.metadata["metadata"]["timeline_order"] for message in messages
    ] == [2, 5]
    assert all(
        message.metadata["metadata"]["run_id"] == "run-1"
        for message in messages
    )


# ---------------------------------------------------------------------------
# _clean_title
# ---------------------------------------------------------------------------


def test_agentscope_msg_to_message_exposes_finished_at():
    """Issue #6826: the API must expose the real reply-end time so the
    frontend can display it instead of the created_at alias."""
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": "done"}],
        created_at="2026-08-10T12:52:57.000000",
        finished_at="2026-08-10T12:54:03.000000",
    )
    shanghai = ZoneInfo("Asia/Shanghai")
    with (
        patch(
            "qwenpaw.app.chats.utils.load_config",
            return_value=SimpleNamespace(user_timezone="Asia/Shanghai"),
        ),
        patch(
            "qwenpaw.app.chats.utils._process_local_tz",
            return_value=shanghai,
        ),
    ):
        [message] = agentscope_msg_to_message(msg)

    assert message.metadata["finished_at"] == "2026-08-10T12:54:03+08:00"
    # timestamp (created_at alias) keeps its existing behaviour.
    assert message.metadata["timestamp"] == "2026-08-10T12:52:57+08:00"


def test_agentscope_msg_to_message_finished_at_none_when_absent():
    """Legacy sessions without the stamp fall back to timestamp."""
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": "legacy"}],
        created_at="2026-08-10T12:52:57.000000",
    )
    shanghai = ZoneInfo("Asia/Shanghai")
    with (
        patch(
            "qwenpaw.app.chats.utils.load_config",
            return_value=SimpleNamespace(user_timezone="Asia/Shanghai"),
        ),
        patch(
            "qwenpaw.app.chats.utils._process_local_tz",
            return_value=shanghai,
        ),
    ):
        [message] = agentscope_msg_to_message(msg)

    assert message.metadata["finished_at"] is None


def test_clean_title_strips_quotes_and_punctuation():
    assert _clean_title('"Hello World,"') == "Hello World"


def test_clean_title_takes_first_line():
    assert _clean_title("Line one\nLine two") == "Line one"


def test_clean_title_empty_returns_empty():
    assert _clean_title("") == ""
    assert _clean_title("   ") == ""


def test_clean_title_keeps_long_title():
    long_title = "x" * 200
    result = _clean_title(long_title)
    assert result == long_title


def test_termination_display_hides_internal_instructions():
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.app.chats.replies import project_replies

    agent = SimpleNamespace(state=SimpleNamespace(context=[]))
    cycle = SimpleNamespace(
        run_id="run", terminated_input_ids=lambda _: ["private-input-id"]
    )
    Runtime._record_request_termination(agent, cycle, "cancelled")
    notice = agent.state.context[0]
    original = notice.model_dump(mode="json")
    [visible] = agentscope_msg_to_message(notice)
    assert visible.content[0].text == "已取消尚未完成的请求；已执行的操作不会回滚。"
    assert "private-input-id" not in visible.content[0].text
    assert notice.model_dump(mode="json") == original
    assert "只处理后续新请求" in notice.content[0].text
    assert not project_replies([notice])
