# -*- coding: utf-8 -*-
"""Unit tests for the QQ tool-guard approval card.

Covers the pure builders, the ``INTERACTION_CREATE`` parser, the
outbound keyboard render path and the inbound click handling
(ack, duplicate suppression, resolved message, command re-injection).
The channel is stubbed, so no network or token machinery is involved.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.qq import channel as qq_channel
from qwenpaw.app.channels.qq.cards import tool_guard as tg

QQ_CHANNEL_MODULE = "qwenpaw.app.channels.qq.channel"


class _StubChannel:
    """Minimal stand-in for ``QQChannel`` used by the card helpers."""

    def __init__(self, *, enabled=True, token_error=None, enqueue=True):
        self.enabled = enabled
        self._http = SimpleNamespace(name="http")
        self._markdown_enabled = True
        self.token_calls = 0
        self._token_error = token_error
        self.resolve_calls = []
        self.fallback_calls = []
        self.enqueued = []
        self._enqueue = self.enqueued.append if enqueue else None

    async def _get_access_token_async(self):
        self.token_calls += 1
        if self._token_error is not None:
            raise self._token_error
        return "token-abc"

    def _resolve_send_path(
        self,
        message_type,
        sender_id,
        channel_id,
        group_openid,
        guild_id=None,
    ):
        self.resolve_calls.append(
            {
                "message_type": message_type,
                "sender_id": sender_id,
                "channel_id": channel_id,
                "group_openid": group_openid,
                "guild_id": guild_id,
            },
        )
        return (f"/route/{message_type}", True, "seq-key")

    async def _send_text_with_fallback(self, *args, **kwargs):
        self.fallback_calls.append({"args": args, "kwargs": kwargs})
        return True


def _event(content="please approve"):
    return SimpleNamespace(content=content)


def _send_meta(**overrides):
    meta = {
        "message_type": "c2c",
        "sender_id": "user-1",
        "session_id": "session-1",
        "message_id": "msg-1",
    }
    meta.update(overrides)
    return meta


def _button_data(action="approve", request_id="rid-12345678", **extra):
    payload = {
        "p": tg.ACTION_DATA_PREFIX,
        "a": action,
        "rid": request_id,
        "tool": "shell",
        "sev": "medium",
    }
    payload.update(extra)
    return json.dumps(payload, separators=(",", ":"))


def _click_event(action="approve", ctx=None, **overrides):
    """Build an ``INTERACTION_CREATE`` event.

    ``ctx`` is merged into the button payload: in production the routing
    keys are encoded when the card is rendered, so a click carries them
    back.
    """
    event = {
        "id": "interaction-1",
        "group_member_openid": "openid-abcdef",
        "data": {
            "resolved": {
                "button_data": _button_data(action, **(ctx or {})),
            },
        },
    }
    event.update(overrides)
    return event


@pytest.fixture(name="acks", autouse=True)
def _acks(monkeypatch):
    """Record QQ API calls so no test reaches the network."""
    calls = []

    async def fake_api_request(http, token, method, path, body):
        calls.append({"method": method, "path": path, "body": body})

    monkeypatch.setattr(qq_channel, "_api_request_async", fake_api_request)
    return calls


@pytest.fixture(name="clean_processed", autouse=True)
def _clean_processed():
    """Keep the module-level dedup cache isolated per test."""
    saved = dict(tg._processed_requests)
    tg._processed_requests.clear()
    yield
    tg._processed_requests.clear()
    tg._processed_requests.update(saved)


# ---------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------


class TestBuildActionData:
    def test_payload_is_compact_and_keyed(self):
        raw = tg._build_action_data(
            "approve",
            "rid-1",
            "shell",
            "high",
            {"sid": "s1"},
        )

        assert json.loads(raw) == {
            "p": "tg_",
            "a": "approve",
            "rid": "rid-1",
            "tool": "shell",
            "sev": "high",
            "sid": "s1",
        }
        # Compact separators keep the payload inside QQ's size budget.
        assert ", " not in raw and '": "' not in raw

    def test_non_ascii_context_is_preserved(self):
        raw = tg._build_action_data("deny", "rid", "tool", "low", {"n": "泰哥"})

        assert "泰哥" in raw


class TestBuildApprovalKeyboard:
    def test_two_buttons_with_expected_render_data(self):
        keyboard = tg.build_approval_keyboard(
            request_id="rid-abcdefgh",
            tool_name="shell",
            severity="HIGH",
        )

        buttons = keyboard["content"]["rows"][0]["buttons"]
        assert [button["id"] for button in buttons] == [
            "approve_rid-abcd",
            "deny_rid-abcd",
        ]
        assert buttons[0]["render_data"]["style"] == 1
        assert buttons[1]["render_data"]["style"] == 0
        assert buttons[0]["render_data"]["visited_label"] == "✅ Approved"
        assert buttons[1]["render_data"]["visited_label"] == "🚫 Denied"

    def test_button_actions_carry_callback_data(self):
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="medium",
            session_ctx={"sid": "s1"},
        )

        buttons = keyboard["content"]["rows"][0]["buttons"]
        for button, expected_action in zip(buttons, ("approve", "deny")):
            action = button["action"]
            assert action["type"] == 1
            assert action["permission"] == {"type": 2}
            payload = json.loads(action["data"])
            assert payload["a"] == expected_action
            assert payload["sid"] == "s1"

    def test_unsupported_client_tips_are_action_specific(self):
        buttons = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="medium",
        )["content"]["rows"][0]["buttons"]

        assert buttons[0]["action"]["unsupport_tips"].endswith("approve")
        assert buttons[1]["action"]["unsupport_tips"].endswith("deny")

    @pytest.mark.parametrize("severity", ["", None])
    def test_blank_severity_falls_back_to_medium(self, severity):
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity=severity,
        )

        data = json.loads(
            keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"],
        )
        assert data["sev"] == "medium"

    def test_whitespace_severity_is_only_lowered(self):
        """``severity or "medium"`` keeps whitespace: it is truthy."""
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="  ",
        )

        data = json.loads(
            keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"],
        )
        assert data["sev"] == "  "

    def test_missing_session_ctx_yields_no_extra_keys(self):
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="medium",
        )

        data = json.loads(
            keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"],
        )
        assert set(data) == {"p", "a", "rid", "tool", "sev"}


class TestBuildResolvedText:
    def test_approved_includes_operator_and_tool(self):
        assert tg.build_resolved_text("shell", "approve", "abc123") == (
            "✅ **Approved** by **abc123**\nTool: `shell`"
        )

    def test_denied_includes_operator_and_tool(self):
        assert tg.build_resolved_text("shell", "deny", "abc123") == (
            "🚫 **Denied** by **abc123**\nTool: `shell`"
        )

    def test_missing_operator_omits_the_by_clause(self):
        text = tg.build_resolved_text("shell", "approve")

        assert text == "✅ **Approved**\nTool: `shell`"

    def test_unknown_action_reports_expiry(self):
        assert tg.build_resolved_text("shell", "whatever") == (
            "⌛ **Expired**\nApproval for `shell` has expired."
        )


# ---------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------


class TestParseInteractionEvent:
    def test_resolved_button_data_is_parsed(self):
        parsed = tg.parse_interaction_event(_click_event())

        assert parsed == {
            "action": "approve",
            "request_id": "rid-12345678",
            "tool_name": "shell",
            "severity": "medium",
            "session_ctx": {},
        }

    def test_top_level_button_data_is_accepted(self):
        parsed = tg.parse_interaction_event(
            {"button_data": _button_data(action="deny")},
        )

        assert parsed["action"] == "deny"

    def test_session_ctx_drops_guard_keys(self):
        parsed = tg.parse_interaction_event(
            {"button_data": _button_data(sid="s1", mt="group")},
        )

        assert parsed["session_ctx"] == {"sid": "s1", "mt": "group"}

    def test_missing_severity_defaults_to_medium(self):
        payload = json.loads(_button_data())
        del payload["sev"]
        parsed = tg.parse_interaction_event(
            {"button_data": json.dumps(payload)},
        )

        assert parsed["severity"] == "medium"

    @pytest.mark.parametrize(
        "event",
        [
            {},
            {"data": {}},
            {"data": {"resolved": {}}},
            {"data": {"resolved": {"button_data": ""}}, "button_data": ""},
            {"data": {"resolved": {"button_data": None}}},
        ],
    )
    def test_events_without_payload_are_ignored(self, event):
        assert tg.parse_interaction_event(event) is None

    @pytest.mark.parametrize("raw", ["not-json", "[1,2", '{"p":'])
    def test_malformed_payload_is_ignored(self, raw):
        assert tg.parse_interaction_event({"button_data": raw}) is None

    def test_foreign_button_prefix_is_ignored(self):
        foreign = json.dumps({"p": "other_", "a": "approve", "rid": "r"})

        assert tg.parse_interaction_event({"button_data": foreign}) is None

    @pytest.mark.parametrize("action", ["", "retry", "APPROVE"])
    def test_unknown_actions_are_ignored(self, action):
        raw = _button_data(action=action)

        assert tg.parse_interaction_event({"button_data": raw}) is None

    def test_non_string_payload_is_coerced(self):
        payload = json.loads(_button_data())
        payload["rid"] = 4242
        parsed = tg.parse_interaction_event(
            {"button_data": json.dumps(payload)},
        )

        assert parsed["request_id"] == "4242"


# ---------------------------------------------------------------------
# Dedup cache
# ---------------------------------------------------------------------


class TestMarkProcessed:
    def test_first_click_is_new_and_repeat_is_duplicate(self):
        assert tg._mark_processed("rid-1", "approve") is False
        assert tg._mark_processed("rid-1", "approve") is True

    def test_recorded_action_is_stored(self):
        tg._mark_processed("rid-1", "deny")

        assert tg._processed_requests["rid-1"] == "deny"

    def test_cache_evicts_half_when_over_limit(self, monkeypatch):
        monkeypatch.setattr(tg, "_PROCESSED_MAX_SIZE", 4)

        for index in range(5):
            tg._mark_processed(f"rid-{index}", "approve")

        assert len(tg._processed_requests) == 3
        # Oldest entries go first.
        assert "rid-0" not in tg._processed_requests
        assert "rid-4" in tg._processed_requests

    def test_cache_at_limit_is_not_evicted(self, monkeypatch):
        monkeypatch.setattr(tg, "_PROCESSED_MAX_SIZE", 4)

        for index in range(4):
            tg._mark_processed(f"rid-{index}", "approve")

        assert len(tg._processed_requests) == 4


# ---------------------------------------------------------------------
# render
# ---------------------------------------------------------------------


class TestRender:
    async def test_missing_request_id_is_skipped(self):
        channel = _StubChannel()

        result = await tg.render(channel, "user-1", _event(), {}, {})

        assert result is False
        assert channel.token_calls == 0

    async def test_disabled_channel_is_skipped(self):
        channel = _StubChannel(enabled=False)

        result = await tg.render(
            channel,
            "user-1",
            _event(),
            {},
            {"approval_request_id": "rid-1"},
        )

        assert result is False
        assert channel.token_calls == 0

    async def test_token_failure_is_swallowed(self):
        channel = _StubChannel(token_error=RuntimeError("no token"))

        result = await tg.render(
            channel,
            "user-1",
            _event(),
            {},
            {"approval_request_id": "rid-1"},
        )

        assert result is False

    async def test_keyboard_message_is_posted(self, monkeypatch):
        channel = _StubChannel()
        posts = []

        async def fake_api_request(http, token, method, path, body):
            posts.append(
                {"http": http, "token": token, "method": method,
                 "path": path, "body": body},
            )

        monkeypatch.setattr(
            qq_channel,
            "_api_request_async",
            fake_api_request,
        )
        monkeypatch.setattr(qq_channel, "_get_next_msg_seq", lambda key: 7)

        result = await tg.render(
            channel,
            "user-1",
            _event("approve this?"),
            _send_meta(),
            {
                "approval_request_id": "rid-12345678",
                "tool_name": "shell",
                "severity": "high",
            },
        )

        assert result is True
        assert len(posts) == 1
        post = posts[0]
        assert post["method"] == "POST"
        assert post["path"] == "/route/c2c"
        assert post["token"] == "token-abc"
        assert post["body"]["msg_type"] == 2
        assert post["body"]["markdown"] == {"content": "approve this?"}
        assert post["body"]["msg_id"] == "msg-1"
        assert post["body"]["msg_seq"] == 7
        buttons = post["body"]["keyboard"]["content"]["rows"][0]["buttons"]
        assert len(buttons) == 2

    async def test_route_receives_send_meta(self, monkeypatch):
        channel = _StubChannel()

        async def fake_api_request(*args, **kwargs):
            return None

        monkeypatch.setattr(
            qq_channel,
            "_api_request_async",
            fake_api_request,
        )
        monkeypatch.setattr(qq_channel, "_get_next_msg_seq", lambda key: 1)

        await tg.render(
            channel,
            "user-1",
            _event(),
            _send_meta(
                message_type="group",
                sender_id="user-9",
                group_openid="goid-1",
                channel_id="cid-1",
                guild_id="gid-1",
            ),
            {"approval_request_id": "rid-1"},
        )

        assert channel.resolve_calls == [
            {
                "message_type": "group",
                "sender_id": "user-9",
                "channel_id": "cid-1",
                "group_openid": "goid-1",
                "guild_id": "gid-1",
            },
        ]

    async def test_defaults_when_send_meta_is_empty(self, monkeypatch):
        channel = _StubChannel()

        async def fake_api_request(*args, **kwargs):
            return None

        monkeypatch.setattr(
            qq_channel,
            "_api_request_async",
            fake_api_request,
        )
        monkeypatch.setattr(qq_channel, "_get_next_msg_seq", lambda key: 3)

        await tg.render(
            channel,
            "handle-1",
            _event(),
            {},
            {"approval_request_id": "rid-1"},
        )

        assert channel.resolve_calls[0]["message_type"] == "c2c"
        assert channel.resolve_calls[0]["sender_id"] == "handle-1"

    async def test_empty_body_uses_placeholder(self, monkeypatch):
        channel = _StubChannel()
        bodies = []

        async def fake_api_request(http, token, method, path, body):
            bodies.append(body)

        monkeypatch.setattr(
            qq_channel,
            "_api_request_async",
            fake_api_request,
        )
        monkeypatch.setattr(qq_channel, "_get_next_msg_seq", lambda key: 1)

        await tg.render(
            channel,
            "user-1",
            _event(content=""),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert bodies[0]["markdown"]["content"] == (
            "🛡️ Tool Approval Required"
        )

    async def test_missing_tool_and_severity_use_defaults(
        self,
        monkeypatch,
    ):
        channel = _StubChannel()
        bodies = []

        async def fake_api_request(http, token, method, path, body):
            bodies.append(body)

        monkeypatch.setattr(
            qq_channel,
            "_api_request_async",
            fake_api_request,
        )
        monkeypatch.setattr(qq_channel, "_get_next_msg_seq", lambda key: 1)

        await tg.render(
            channel,
            "user-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        data = json.loads(
            bodies[0]["keyboard"]["content"]["rows"][0]["buttons"][0][
                "action"
            ]["data"],
        )
        assert data["tool"] == "tool"
        assert data["sev"] == "medium"

    async def test_send_failure_is_swallowed(self, monkeypatch):
        channel = _StubChannel()

        async def boom(*args, **kwargs):
            raise RuntimeError("api down")

        monkeypatch.setattr(qq_channel, "_api_request_async", boom)
        monkeypatch.setattr(qq_channel, "_get_next_msg_seq", lambda key: 1)

        result = await tg.render(
            channel,
            "user-1",
            _event(),
            _send_meta(),
            {"approval_request_id": "rid-1"},
        )

        assert result is False

    async def test_route_without_msg_seq_omits_the_field(self, monkeypatch):
        channel = _StubChannel()
        channel._resolve_send_path = lambda *a, **k: ("/route/x", False, "")
        bodies = []

        async def fake_api_request(http, token, method, path, body):
            bodies.append(body)

        monkeypatch.setattr(
            qq_channel,
            "_api_request_async",
            fake_api_request,
        )

        await tg.render(
            channel,
            "user-1",
            _event(),
            {"message_type": "guild"},
            {"approval_request_id": "rid-1"},
        )

        assert "msg_seq" not in bodies[0]
        assert "msg_id" not in bodies[0]


# ---------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------


class TestHandle:
    async def test_non_guard_events_are_ignored(self, acks):
        channel = _StubChannel()

        await tg.handle(channel, {"id": "interaction-1"})

        assert acks == []
        assert channel.enqueued == []
        assert channel.fallback_calls == []

    async def test_first_click_acks_sends_and_enqueues(self, acks):
        channel = _StubChannel()

        await tg.handle(channel, _click_event(ctx={"sender": "user-1"}))

        assert acks == [
            {"method": "PUT", "path": "/interactions/interaction-1",
             "body": {"code": 0}},
        ]
        assert len(channel.fallback_calls) == 1
        assert len(channel.enqueued) == 1
        text = channel.enqueued[0]["content_parts"][0].text
        assert text == "/approval approve rid-12345678"

    async def test_duplicate_click_acks_with_code_three(self, acks):
        channel = _StubChannel()
        event = _click_event(ctx={"sender": "user-1"})

        await tg.handle(channel, event)
        await tg.handle(channel, event)

        assert [entry["body"]["code"] for entry in acks] == [0, 3]
        assert len(channel.enqueued) == 1
        assert len(channel.fallback_calls) == 1

    async def test_missing_interaction_id_skips_the_ack(self, acks):
        channel = _StubChannel()

        await tg.handle(channel, _click_event(id="", ctx={"sender": "u"}))

        assert acks == []
        assert len(channel.enqueued) == 1

    async def test_ack_failure_does_not_block_the_command(self, monkeypatch):
        channel = _StubChannel()

        async def boom(*args, **kwargs):
            raise RuntimeError("ack failed")

        monkeypatch.setattr(qq_channel, "_api_request_async", boom)

        await tg.handle(channel, _click_event(ctx={"sender": "user-1"}))

        assert len(channel.enqueued) == 1

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            (
                {
                    "group_member_openid": "g-000abc",
                    "ctx": {"sender": "user-1"},
                },
                "000abc",
            ),
            (
                {
                    "group_member_openid": "",
                    "user_openid": "u-xyz987",
                    "ctx": {"sender": "user-1"},
                },
                "xyz987",
            ),
            (
                {
                    "group_member_openid": "",
                    "user_openid": "",
                    "data": {
                        "resolved": {
                            "button_data": _button_data(sender="user-1"),
                            "user_id": "r-123456",
                        },
                    },
                },
                "123456",
            ),
        ],
    )
    async def test_operator_display_uses_openid_tail(
        self,
        overrides,
        expected,
    ):
        channel = _StubChannel()

        await tg.handle(channel, _click_event(**overrides))

        call = channel.fallback_calls[0]
        assert expected in call["args"][4]

    async def test_operator_without_openid_has_no_by_clause(self):
        channel = _StubChannel()

        await tg.handle(
            channel,
            _click_event(group_member_openid="", ctx={"sender": "user-1"}),
        )

        text = channel.fallback_calls[0]["args"][4]
        assert " by " not in text

    async def test_deny_click_enqueues_deny_command(self):
        channel = _StubChannel()

        await tg.handle(
            channel,
            _click_event(action="deny", ctx={"sender": "user-1"}),
        )

        assert channel.enqueued[0]["content_parts"][0].text == (
            "/approval deny rid-12345678"
        )
        assert "🚫 **Denied**" in channel.fallback_calls[0]["args"][4]

    async def test_missing_tool_name_falls_back_to_tool(self):
        channel = _StubChannel()
        payload = json.loads(_button_data(sender="user-1"))
        del payload["tool"]

        await tg.handle(
            channel,
            {
                "id": "interaction-1",
                "group_member_openid": "openid-abcdef",
                "data": {
                    "resolved": {
                        "button_data": json.dumps(payload),
                    },
                },
            },
        )

        assert "`tool`" in channel.fallback_calls[0]["args"][4]

    async def test_click_without_routing_target_skips_the_message(self):
        """No sender/group/channel/guild in the payload -> nothing to send."""
        channel = _StubChannel()

        await tg.handle(channel, _click_event())

        assert channel.fallback_calls == []
        assert len(channel.enqueued) == 1


# ---------------------------------------------------------------------
# Resolved message + command injection
# ---------------------------------------------------------------------


class TestSendResolvedMessage:
    async def test_missing_target_is_skipped(self):
        channel = _StubChannel()

        await tg._send_resolved_message(
            channel,
            session_ctx={},
            tool_name="shell",
            action="approve",
            operator_display="",
        )

        assert channel.fallback_calls == []

    async def test_session_ctx_maps_to_positional_arguments(self):
        channel = _StubChannel()

        await tg._send_resolved_message(
            channel,
            session_ctx={
                "mt": "group",
                "sender": "user-1",
                "goid": "goid-1",
                "cid": "cid-1",
                "gid": "gid-1",
                "mid": "msg-1",
            },
            tool_name="shell",
            action="approve",
            operator_display="abc123",
        )

        call = channel.fallback_calls[0]
        assert call["args"][:6] == (
            "group",
            "user-1",
            "cid-1",
            "goid-1",
            "✅ **Approved** by **abc123**\nTool: `shell`",
            "msg-1",
        )
        assert call["args"][6] == "token-abc"
        assert call["args"][7] is True
        assert call["kwargs"] == {"guild_id": "gid-1"}

    async def test_group_openid_alone_is_enough(self):
        channel = _StubChannel()

        await tg._send_resolved_message(
            channel,
            session_ctx={"goid": "goid-1"},
            tool_name="shell",
            action="deny",
            operator_display="",
        )

        assert len(channel.fallback_calls) == 1

    async def test_send_failure_is_swallowed(self):
        channel = _StubChannel()

        async def boom(*args, **kwargs):
            raise RuntimeError("send failed")

        channel._send_text_with_fallback = boom

        await tg._send_resolved_message(
            channel,
            session_ctx={"sender": "user-1"},
            tool_name="shell",
            action="approve",
            operator_display="",
        )

        assert channel.fallback_calls == []


class TestEnqueueApprovalCommand:
    def test_missing_enqueue_hook_drops_silently(self):
        channel = _StubChannel(enqueue=False)

        tg._enqueue_approval_command(
            channel,
            action="approve",
            request_id="rid-1",
            session_ctx={},
            user_id="user-1",
        )

        assert channel.enqueued == []

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
        assert payload["channel_id"] == "qq"
        assert payload["sender_id"] == "user-9"
        assert payload["user_id"] == "user-9"
        assert payload["session_id"] == ""
        assert payload["content_parts"][0].text == "/approval approve rid-1"
        assert payload["meta"] == {
            "message_type": "c2c",
            "sender_id": "user-9",
            "group_openid": "",
            "channel_id": "",
            "guild_id": "",
            "is_group": False,
            "from_card_action": True,
        }

    def test_session_ctx_wins_over_the_operator_id(self):
        channel = _StubChannel()

        tg._enqueue_approval_command(
            channel,
            action="deny",
            request_id="rid-1",
            session_ctx={"sender": "ctx-sender", "sid": "ctx-session"},
            user_id="user-9",
        )

        payload = channel.enqueued[0]
        assert payload["sender_id"] == "ctx-sender"
        assert payload["session_id"] == "ctx-session"

    @pytest.mark.parametrize(
        ("message_type", "is_group"),
        [("group", True), ("guild", True), ("c2c", False), ("dm", False)],
    )
    def test_is_group_follows_the_message_type(self, message_type, is_group):
        channel = _StubChannel()

        tg._enqueue_approval_command(
            channel,
            action="approve",
            request_id="rid-1",
            session_ctx={"mt": message_type},
            user_id="user-9",
        )

        assert channel.enqueued[0]["meta"]["is_group"] is is_group

    def test_enqueue_failure_is_swallowed(self):
        channel = _StubChannel()

        def boom(payload):
            raise RuntimeError("queue closed")

        channel._enqueue = boom

        tg._enqueue_approval_command(
            channel,
            action="approve",
            request_id="rid-1",
            session_ctx={},
            user_id="user-9",
        )


class TestAckInteraction:
    async def test_put_uses_the_interaction_id_and_code(self, monkeypatch):
        channel = _StubChannel()
        calls = []

        async def fake_api_request(http, token, method, path, body):
            calls.append((http, token, method, path, body))

        monkeypatch.setattr(qq_channel, "_api_request_async", fake_api_request)

        await tg._ack_interaction(channel, "inter-1", code=3)

        assert calls == [
            (channel._http, "token-abc", "PUT", "/interactions/inter-1",
             {"code": 3}),
        ]

    async def test_token_failure_is_swallowed(self, monkeypatch):
        channel = _StubChannel(token_error=RuntimeError("no token"))
        calls = []

        async def fake_api_request(*args, **kwargs):
            calls.append(args)

        monkeypatch.setattr(qq_channel, "_api_request_async", fake_api_request)

        await tg._ack_interaction(channel, "inter-1")

        assert calls == []

    async def test_request_failure_is_swallowed(self, monkeypatch):
        channel = _StubChannel()

        async def boom(*args, **kwargs):
            raise RuntimeError("api down")

        monkeypatch.setattr(qq_channel, "_api_request_async", boom)

        await tg._ack_interaction(channel, "inter-1")


class TestModuleMetadata:
    def test_dispatcher_metadata(self):
        assert tg.NAME == "tool_guard_approval"
        assert tg.MESSAGE_TYPE == "tool_guard_approval"
        assert tg.ACTION_DATA_PREFIX == "tg_"
        assert (tg.APPROVE_KEY, tg.DENY_KEY) == ("approve", "deny")
