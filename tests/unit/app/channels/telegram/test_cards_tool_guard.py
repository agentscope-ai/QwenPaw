# -*- coding: utf-8 -*-
"""Unit tests for the Telegram tool-guard approval card.

Covers the request-context cache and its eviction, the processed-click
dedup cache, the inline keyboard builders, MarkdownV2 escaping, the
resolved-text formatting in both streaming and non-streaming shapes,
the callback_data parser, the outbound render path and the inbound
CallbackQuery handling (toast, message edit, ``/approval`` injection).
The channel and its python-telegram-bot application are stubbed, so
nothing reaches the network.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import pytest
from telegram.constants import ParseMode
from telegram.error import BadRequest

from qwenpaw.app.channels.telegram.cards import tool_guard as tg

CALLBACK_DATA_BUDGET = 64  # Telegram hard limit


class _StubBot:
    def __init__(self, error=None):
        self.sent = []
        self._error = error

    async def send_message(self, **kwargs):
        if self._error is not None:
            raise self._error
        self.sent.append(kwargs)
        return object()


class _StubChannel:
    """Minimal stand-in for ``TelegramChannel``."""

    channel = "telegram"

    def __init__(
        self,
        *,
        enabled=True,
        with_application=True,
        enqueue=True,
        send_error=None,
    ):
        self.enabled = enabled
        self._application = (
            _StubApplication(send_error=send_error)
            if with_application
            else None
        )
        self.enqueued = []
        self._enqueue = self.enqueued.append if enqueue else None


class _StubApplication:
    def __init__(self, *, bot=None, send_error=None):
        self.bot = bot if bot is not None else _StubBot(send_error)


class _StubUser:
    def __init__(self, username=None, first_name=None, user_id=77):
        self.username = username
        self.first_name = first_name
        self.id = user_id


_UNSET = object()


class _StubQuery:
    """Stand-in for a Telegram ``CallbackQuery``."""

    def __init__(
        self,
        data="tga:rid-1",
        from_user=_UNSET,
        answer_error=None,
        edit_error=None,
    ):
        self.data = data
        # A sentinel keeps ``from_user=None`` (an operator-less callback)
        # distinguishable from "not supplied".
        self.from_user = (
            _StubUser(username="taige") if from_user is _UNSET else from_user
        )
        self.answers = []
        self.edits = []
        self._answer_error = answer_error
        self._edit_error = edit_error

    async def answer(self, text=None, show_alert=False):
        if self._answer_error is not None:
            raise self._answer_error
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, **kwargs):
        if self._edit_error is not None:
            raise self._edit_error
        self.edits.append(kwargs)


def _event(content="please approve"):
    class _Msg:
        pass

    msg = _Msg()
    msg.content = content
    return msg


def _send_meta(**overrides):
    meta = {
        "chat_id": "chat-1",
        "sender_id": "sender-1",
        "session_id": "session-1",
        "is_group": False,
    }
    meta.update(overrides)
    return meta


@pytest.fixture(name="clean_caches", autouse=True)
def _clean_caches():
    """Keep both module-level caches isolated per test."""
    saved_ctx = dict(tg._request_context_cache)
    saved_proc = dict(tg._processed_requests)
    tg._request_context_cache.clear()
    tg._processed_requests.clear()
    yield
    tg._request_context_cache.clear()
    tg._processed_requests.clear()
    tg._request_context_cache.update(saved_ctx)
    tg._processed_requests.update(saved_proc)


# ---------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------


class TestRequestContextCache:
    def test_round_trip(self):
        tg._cache_request_context(
            "rid-1",
            "shell",
            "high",
            "body",
            {"chat_id": "c1"},
        )

        assert tg._get_request_context("rid-1") == {
            "tool_name": "shell",
            "severity": "high",
            "body_text": "body",
            "session_ctx": {"chat_id": "c1"},
        }

    def test_unknown_request_returns_none(self):
        assert tg._get_request_context("nope") is None

    def test_eviction_halves_the_cache(self, monkeypatch):
        monkeypatch.setattr(tg, "_CACHE_MAX_SIZE", 4)

        for index in range(5):
            tg._cache_request_context(f"rid-{index}", "t", "m", "", {})

        assert len(tg._request_context_cache) == 3
        assert "rid-0" not in tg._request_context_cache
        assert "rid-4" in tg._request_context_cache

    def test_cache_at_limit_is_kept(self, monkeypatch):
        monkeypatch.setattr(tg, "_CACHE_MAX_SIZE", 4)

        for index in range(4):
            tg._cache_request_context(f"rid-{index}", "t", "m", "", {})

        assert len(tg._request_context_cache) == 4


class TestMarkProcessed:
    def test_first_click_is_new_and_repeat_is_duplicate(self):
        assert tg._mark_processed("rid-1", "approve") is False
        assert tg._mark_processed("rid-1", "approve") is True

    def test_recorded_action_is_stored(self):
        tg._mark_processed("rid-1", "deny")

        assert tg._processed_requests["rid-1"] == "deny"

    def test_eviction_halves_the_cache(self, monkeypatch):
        monkeypatch.setattr(tg, "_PROCESSED_MAX_SIZE", 4)

        for index in range(5):
            tg._mark_processed(f"rid-{index}", "approve")

        assert len(tg._processed_requests) == 3
        assert "rid-0" not in tg._processed_requests
        assert "rid-4" in tg._processed_requests


# ---------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------


class TestBuildApprovalKeyboard:
    def test_single_row_with_two_buttons(self):
        keyboard = tg.build_approval_keyboard("rid-1")

        rows = keyboard.inline_keyboard
        assert len(rows) == 1
        assert [button.text for button in rows[0]] == [
            "✅ Approve",
            "❌ Deny",
        ]

    def test_callback_data_carries_the_prefixed_request_id(self):
        keyboard = tg.build_approval_keyboard("rid-1")

        buttons = keyboard.inline_keyboard[0]
        assert buttons[0].callback_data == "tga:rid-1"
        assert buttons[1].callback_data == "tgd:rid-1"

    def test_callback_data_stays_inside_telegrams_byte_budget(self):
        """callback_data is hard-capped at 64 bytes by the Bot API."""
        # A uuid4 request_id is the longest value seen in production.
        request_id = "0" * 36
        keyboard = tg.build_approval_keyboard(request_id)

        for button in keyboard.inline_keyboard[0]:
            assert len(button.callback_data.encode("utf-8")) <= (
                CALLBACK_DATA_BUDGET
            )


class TestBuildApprovalText:
    def test_body_is_passed_through_verbatim(self):
        assert tg.build_approval_text("raw body") == "raw body"

    @pytest.mark.parametrize("body", ["", None])
    def test_empty_body_uses_the_placeholder(self, body):
        assert tg.build_approval_text(body) == "🛡️ Tool Approval Required"


class TestBuildResolvedText:
    def test_plain_shape_keeps_the_body(self):
        text = tg.build_resolved_text(
            tool_name="shell",
            action="approve",
            operator_display="@taige",
            body_text="raw body",
        )

        assert text == ("raw body\n\n✅ Approved by @taige  |  Tool: shell")

    def test_plain_shape_without_operator(self):
        text = tg.build_resolved_text(
            tool_name="shell",
            action="deny",
            body_text="raw body",
        )

        assert text == "raw body\n\n🚫 Denied  |  Tool: shell"

    def test_plain_shape_escapes_nothing(self):
        """A body with markdown must survive untouched (parse_mode=None)."""
        text = tg.build_resolved_text(
            tool_name="a_b",
            action="approve",
            body_text="keep *this* [as is]",
        )

        assert "keep *this* [as is]" in text
        assert "Tool: a_b" in text

    def test_compact_shape_uses_markdown_v2(self):
        text = tg.build_resolved_text(
            tool_name="shell",
            action="approve",
            operator_display="@taige",
            body_text="",
        )

        assert text == "✅ *Approved* by *@taige*  \\|  Tool: `shell`"

    def test_compact_shape_denied(self):
        text = tg.build_resolved_text(
            tool_name="shell",
            action="deny",
            body_text="",
        )

        assert text == "🚫 *Denied*  \\|  Tool: `shell`"

    def test_compact_shape_escapes_specials_in_the_tool_name(self):
        text = tg.build_resolved_text(
            tool_name="rm -rf /tmp",
            action="approve",
            body_text="",
        )

        assert "`rm \\-rf /tmp`" in text

    @pytest.mark.parametrize("action", ["", "retry", "APPROVE"])
    def test_unknown_action_reports_expiry(self, action):
        text = tg.build_resolved_text(
            tool_name="shell",
            action=action,
            body_text="body",
        )

        assert "⌛ Expired" in text

    def test_compact_unknown_action_reports_expiry(self):
        text = tg.build_resolved_text(
            tool_name="shell",
            action="whatever",
            body_text="",
        )

        assert text == "⌛ *Expired*  \\|  Tool: `shell`"


class TestEscapeMdv2:
    def test_specials_are_backslashed(self):
        assert tg._escape_mdv2("a_b.c!") == "a\\_b\\.c\\!"

    def test_pipe_is_escaped(self):
        assert tg._escape_mdv2("|") == "\\|"

    def test_plain_text_is_untouched(self):
        assert tg._escape_mdv2("shell 123") == "shell 123"

    @pytest.mark.parametrize("char", ["*", "[", "]", "(", ")", "~", "`", ">"])
    def test_each_markdown_metacharacter(self, char):
        assert tg._escape_mdv2(char) == f"\\{char}"

    @pytest.mark.parametrize(
        "char",
        ["#", "+", "-", "=", "{", "}", ".", "!"],
    )
    def test_each_punctuation_metacharacter(self, char):
        assert tg._escape_mdv2(char) == f"\\{char}"

    def test_backslash_is_escaped(self):
        assert tg._escape_mdv2("\\") == "\\\\"


# ---------------------------------------------------------------------
# render
# ---------------------------------------------------------------------


class TestRender:
    async def test_missing_request_id_is_skipped(self):
        channel = _StubChannel()

        result = await tg.render(channel, "chat-1", _event(), _send_meta(), {})

        assert result is False
        assert channel._application.bot.sent == []

    async def test_disabled_channel_is_skipped(self):
        channel = _StubChannel(enabled=False)

        result = await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert result is False
        assert channel._application.bot.sent == []

    async def test_missing_application_is_skipped(self):
        channel = _StubChannel(with_application=False)

        result = await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert result is False

    async def test_missing_bot_is_skipped(self):
        channel = _StubChannel()
        channel._application.bot = None

        result = await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert result is False

    async def test_blank_chat_id_is_skipped(self):
        channel = _StubChannel()

        result = await tg.render(
            channel,
            "",
            _event(),
            {"chat_id": ""},
            {"approval_request_id": "rid-1"},
        )

        assert result is False
        assert channel._application.bot.sent == []

    async def test_message_is_sent_with_keyboard_and_cached_context(self):
        channel = _StubChannel()

        result = await tg.render(
            channel,
            "chat-1",
            _event("body text"),
            _send_meta(),
            {
                "approval_request_id": "rid-1",
                "tool_name": "shell",
                "severity": "high",
            },
        )

        assert result is True
        sent = channel._application.bot.sent[0]
        assert sent["chat_id"] == "chat-1"
        assert sent["text"] == "body text"
        assert sent["reply_markup"].inline_keyboard[0][0].callback_data == (
            "tga:rid-1"
        )
        assert tg._get_request_context("rid-1")["tool_name"] == "shell"
        assert tg._get_request_context("rid-1")["body_text"] == "body text"

    async def test_handle_is_used_when_chat_id_is_missing(self):
        channel = _StubChannel()

        await tg.render(
            channel,
            "fallback-handle",
            _event(),
            {},
            {"approval_request_id": "rid-1"},
        )

        assert channel._application.bot.sent[0]["chat_id"] == "fallback-handle"

    async def test_thread_id_is_forwarded_when_present(self):
        channel = _StubChannel()

        await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(message_thread_id=42),
            {"approval_request_id": "rid-1"},
        )

        assert channel._application.bot.sent[0]["message_thread_id"] == 42

    async def test_thread_id_is_omitted_when_absent(self):
        channel = _StubChannel()

        await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert "message_thread_id" not in channel._application.bot.sent[0]

    async def test_defaults_when_meta_is_sparse(self):
        channel = _StubChannel()

        await tg.render(
            channel,
            "chat-1",
            _event(content=""),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        cached = tg._get_request_context("rid-1")
        assert cached["tool_name"] == "tool"
        assert cached["severity"] == "medium"
        assert channel._application.bot.sent[0]["text"] == (
            "🛡️ Tool Approval Required"
        )

    async def test_session_ctx_is_cached_from_send_meta(self):
        channel = _StubChannel()

        await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(
                sender_id="sender-9",
                session_id="session-9",
                is_group=True,
                message_thread_id=7,
            ),
            {"approval_request_id": "rid-1"},
        )

        ctx = tg._get_request_context("rid-1")["session_ctx"]
        assert ctx == {
            "chat_id": "chat-1",
            "sender_id": "sender-9",
            "session_id": "session-9",
            "is_group": True,
            "message_thread_id": 7,
        }

    async def test_bad_request_is_swallowed(self):
        channel = _StubChannel(send_error=BadRequest("markdown parse"))

        result = await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert result is False

    async def test_generic_send_failure_is_swallowed(self):
        channel = _StubChannel(send_error=RuntimeError("network down"))

        result = await tg.render(
            channel,
            "chat-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert result is False
        # The context is cached before the send, so a retry can reuse it.
        assert tg._get_request_context("rid-1") is not None


# ---------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------


class TestParseCallbackData:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("tga:rid-1", {"action": "approve", "request_id": "rid-1"}),
            ("tgd:rid-1", {"action": "deny", "request_id": "rid-1"}),
            ("tga:", {"action": "approve", "request_id": ""}),
        ],
    )
    def test_known_prefixes(self, raw, expected):
        assert tg._parse_callback_data(raw) == expected

    @pytest.mark.parametrize("raw", ["", "other:rid", "TGA:rid", "tg:rid"])
    def test_foreign_or_empty_data_is_ignored(self, raw):
        assert tg._parse_callback_data(raw) is None


# ---------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------


class TestHandle:
    async def test_non_guard_callback_is_ignored(self):
        channel = _StubChannel()
        query = _StubQuery(data="other:rid-1")

        await tg.handle(channel, query)

        assert query.answers == []
        assert query.edits == []
        assert channel.enqueued == []

    async def test_first_click_answers_edits_and_enqueues(self):
        channel = _StubChannel()
        query = _StubQuery(data="tga:rid-1")

        await tg.handle(channel, query)

        assert query.answers == [
            {"text": "✅ Approved: tool", "show_alert": False},
        ]
        assert len(query.edits) == 1
        assert query.edits[0]["reply_markup"] is None
        assert channel.enqueued[0]["content_parts"][0].text == (
            "/approval approve rid-1"
        )

    async def test_deny_click_toast_and_command(self):
        channel = _StubChannel()
        query = _StubQuery(data="tgd:rid-2")

        await tg.handle(channel, query)

        assert query.answers[0]["text"] == "🚫 Denied: tool"
        assert channel.enqueued[0]["content_parts"][0].text == (
            "/approval deny rid-2"
        )

    async def test_cached_context_shapes_the_toast(self):
        channel = _StubChannel()
        tg._cache_request_context(
            "rid-1",
            "shell",
            "high",
            "raw body",
            {
                "sender_id": "ctx-sender",
                "session_id": "ctx-session",
                "chat_id": "ctx-chat",
                "is_group": True,
            },
        )
        query = _StubQuery(data="tga:rid-1")

        await tg.handle(channel, query)

        assert query.answers[0]["text"] == "✅ Approved: shell"
        # A cached body keeps the edit in plain-text mode.
        assert "parse_mode" not in query.edits[0]
        assert "raw body" in query.edits[0]["text"]
        payload = channel.enqueued[0]
        assert payload["sender_id"] == "ctx-sender"
        assert payload["session_id"] == "ctx-session"
        assert payload["meta"]["chat_id"] == "ctx-chat"
        assert payload["meta"]["is_group"] is True

    async def test_compact_edit_uses_markdown_v2(self):
        channel = _StubChannel()
        query = _StubQuery(data="tga:rid-1")

        await tg.handle(channel, query)

        assert query.edits[0]["parse_mode"] == ParseMode.MARKDOWN_V2

    async def test_duplicate_click_only_toasts(self):
        channel = _StubChannel()
        first = _StubQuery(data="tga:rid-1")
        second = _StubQuery(data="tga:rid-1")

        await tg.handle(channel, first)
        await tg.handle(channel, second)

        assert second.answers == [
            {"text": "Already processed.", "show_alert": False},
        ]
        assert second.edits == []
        assert len(channel.enqueued) == 1

    async def test_duplicate_toast_failure_is_swallowed(self):
        channel = _StubChannel()
        tg._mark_processed("rid-1", "approve")
        query = _StubQuery(data="tga:rid-1", answer_error=RuntimeError("x"))

        await tg.handle(channel, query)

        assert channel.enqueued == []

    @pytest.mark.parametrize(
        ("user", "expected"),
        [
            (_StubUser(username="taige"), "@taige"),
            (_StubUser(first_name="泰哥"), "泰哥"),
            (_StubUser(user_id=987), "987"),
        ],
    )
    async def test_operator_display_preference(self, user, expected):
        channel = _StubChannel()
        tg._cache_request_context("rid-1", "shell", "m", "body", {})
        query = _StubQuery(data="tga:rid-1", from_user=user)

        await tg.handle(channel, query)

        assert expected in query.edits[0]["text"]

    async def test_missing_from_user_yields_empty_operator(self):
        channel = _StubChannel()
        tg._cache_request_context("rid-1", "shell", "m", "body", {})
        query = _StubQuery(data="tga:rid-1", from_user=None)

        await tg.handle(channel, query)

        assert " by " not in query.edits[0]["text"]
        assert channel.enqueued[0]["sender_id"] == ""

    async def test_user_id_falls_back_to_the_operator(self):
        channel = _StubChannel()
        query = _StubQuery(
            data="tga:rid-1",
            from_user=_StubUser(user_id=555),
        )

        await tg.handle(channel, query)

        assert channel.enqueued[0]["user_id"] == "555"

    async def test_answer_failure_does_not_block_the_command(self):
        channel = _StubChannel()
        query = _StubQuery(data="tga:rid-1", answer_error=RuntimeError("x"))

        await tg.handle(channel, query)

        assert len(channel.enqueued) == 1
        assert len(query.edits) == 1

    async def test_edit_failure_does_not_block_the_command(self):
        channel = _StubChannel()
        query = _StubQuery(data="tga:rid-1", edit_error=BadRequest("boom"))

        await tg.handle(channel, query)

        assert len(channel.enqueued) == 1

    async def test_missing_data_attribute_is_ignored(self):
        channel = _StubChannel()

        class _Bare:
            pass

        await tg.handle(channel, _Bare())

        assert channel.enqueued == []


class TestUpdateMessageResolved:
    async def test_not_modified_bad_request_is_silent(self):
        query = _StubQuery(edit_error=BadRequest("Message is not modified"))

        await tg._update_message_resolved(
            query,
            tool_name="shell",
            action="approve",
            operator_display="",
            body_text="",
        )

        assert query.edits == []

    async def test_other_bad_request_is_surfaced_as_a_warning(self, caplog):
        query = _StubQuery(edit_error=BadRequest("chat not found"))

        with caplog.at_level("WARNING"):
            await tg._update_message_resolved(
                query,
                tool_name="shell",
                action="approve",
                operator_display="",
                body_text="",
            )

        assert "update failed" in caplog.text

    async def test_generic_failure_is_logged(self, caplog):
        query = _StubQuery(edit_error=RuntimeError("network"))

        with caplog.at_level("ERROR"):
            await tg._update_message_resolved(
                query,
                tool_name="shell",
                action="deny",
                operator_display="@taige",
                body_text="body",
            )

        assert "update failed" in caplog.text


class TestEnqueueApprovalCommand:
    def test_missing_enqueue_hook_drops_the_command(self, caplog):
        channel = _StubChannel(enqueue=False)

        with caplog.at_level("WARNING"):
            tg._enqueue_approval_command(
                channel,
                action="approve",
                request_id="rid-1",
                session_ctx={},
                user_id="user-1",
            )

        assert "enqueue not set" in caplog.text

    def test_payload_shape_and_defaults(self):
        channel = _StubChannel()

        tg._enqueue_approval_command(
            channel,
            action="approve",
            request_id="rid-1",
            session_ctx={},
            user_id="user-9",
        )

        payload = channel.enqueued[0]
        assert payload["channel_id"] == "telegram"
        assert payload["sender_id"] == "user-9"
        assert payload["user_id"] == "user-9"
        assert payload["session_id"] == ""
        assert payload["content_parts"][0].text == "/approval approve rid-1"
        assert payload["meta"] == {
            "chat_id": "",
            "user_id": "user-9",
            "is_group": False,
            "from_card_action": True,
        }

    def test_session_ctx_wins_over_the_operator_id(self):
        channel = _StubChannel()

        tg._enqueue_approval_command(
            channel,
            action="deny",
            request_id="rid-1",
            session_ctx={"sender_id": "ctx-sender", "chat_id": "ctx-chat"},
            user_id="user-9",
        )

        payload = channel.enqueued[0]
        assert payload["sender_id"] == "ctx-sender"
        assert payload["meta"]["chat_id"] == "ctx-chat"

    def test_thread_id_is_forwarded(self):
        channel = _StubChannel()

        tg._enqueue_approval_command(
            channel,
            action="approve",
            request_id="rid-1",
            session_ctx={"message_thread_id": 33},
            user_id="user-9",
        )

        assert channel.enqueued[0]["meta"]["message_thread_id"] == 33

    def test_thread_id_is_omitted_when_absent(self):
        channel = _StubChannel()

        tg._enqueue_approval_command(
            channel,
            action="approve",
            request_id="rid-1",
            session_ctx={},
            user_id="user-9",
        )

        assert "message_thread_id" not in channel.enqueued[0]["meta"]

    def test_is_group_is_coerced_to_bool(self):
        channel = _StubChannel()

        tg._enqueue_approval_command(
            channel,
            action="approve",
            request_id="rid-1",
            session_ctx={"is_group": 1},
            user_id="user-9",
        )

        assert channel.enqueued[0]["meta"]["is_group"] is True

    def test_enqueue_failure_is_swallowed(self, caplog):
        channel = _StubChannel()

        def boom(payload):
            raise RuntimeError("queue closed")

        channel._enqueue = boom

        with caplog.at_level("ERROR"):
            tg._enqueue_approval_command(
                channel,
                action="approve",
                request_id="rid-1",
                session_ctx={},
                user_id="user-9",
            )

        assert "enqueue failed" in caplog.text


class TestModuleMetadata:
    def test_dispatcher_metadata(self):
        assert tg.NAME == "tool_guard_approval"
        assert tg.MESSAGE_TYPE == "tool_guard_approval"
        assert tg.CALLBACK_DATA_PREFIX == "tg"
        assert (tg.APPROVE_PREFIX, tg.DENY_PREFIX) == ("tga:", "tgd:")
