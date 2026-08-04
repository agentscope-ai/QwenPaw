# -*- coding: utf-8 -*-
from __future__ import annotations

from agentscope.message import Msg

from qwenpaw.app.chats.utils import (
    _abspath_from_url,
    _is_local_file_url,
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


def test_clean_display_text_strips_both_skill_and_headline():
    text = "/run<skill name='x'>body</skill>\n<!-- ⟦ h ⟧ -->"
    out = clean_display_text(text, "user")
    assert "<skill" not in out and "⟦" not in out and "/run" in out


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
    ``visual_history`` / ``visual_context`` messages. They are model-only
    reconstructions, never the user's transcript."""
    for name in ("visual_history", "visual_context"):
        collapsed = Msg(
            name=name,
            role="user",
            content=[
                {"type": "text", "text": "[pages 1-3 of prior history]"},
            ],
        )
        assert not agentscope_msg_to_message(collapsed), name


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
# _clean_title
# ---------------------------------------------------------------------------


def test_clean_title_strips_quotes_and_punctuation():
    assert _clean_title('"Hello World,"') == "Hello World"


def test_clean_title_takes_first_line():
    assert _clean_title("Line one\nLine two") == "Line one"


def test_clean_title_empty_returns_empty():
    assert _clean_title("") == ""
    assert _clean_title("   ") == ""


def test_clean_title_truncates_long_title():
    long_title = "x" * 200
    result = _clean_title(long_title)
    assert len(result) <= 80
