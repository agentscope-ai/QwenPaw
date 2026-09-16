# -*- coding: utf-8 -*-
"""Unit tests for the Feishu tool-guard approval card.

Covers the pure builders, the inbound ``parse_action_value`` guard, the
outbound ``render`` early-exits and send path, and the synchronous
``handle`` re-injection (including the operator-name lookup).
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.app.channels.feishu.cards import tool_guard as tg

# tests/conftest.py replaces the optional Feishu SDK with a MagicMock, so
# the module-level ``P2CardActionTriggerResponse`` import fails and the
# name stays ``None``.  ``handle`` needs the real class to build its
# response, so load it here once (without disturbing the global stub).
_LARK_MODULE = "lark_oapi.event.callback.model.p2_card_action_trigger"


def _load_real_response_class():
    stubbed = {
        name: sys.modules[name]
        for name in list(sys.modules)
        if name == "lark_oapi" or name.startswith("lark_oapi.")
    }
    for name in stubbed:
        del sys.modules[name]
    try:
        module = importlib.import_module(_LARK_MODULE)
        return module.P2CardActionTriggerResponse
    except (ImportError, AttributeError):
        # The SDK is unusable on this interpreter, which happens two ways:
        #
        # * ImportError -- ``lark_oapi`` is absent, or its vendored
        #   ``ws/pb/google`` namespace shim calls ``pkg_resources`` and
        #   that module is gone entirely (setuptools without the legacy
        #   pkg_resources extra).
        # * AttributeError -- ``pkg_resources`` is importable but
        #   setuptools >= 81 removed ``declare_namespace``, so the shim
        #   raises while ``lark_oapi.ws`` loads.  Observed on the macOS
        #   runner (system Python + setuptools 84.0.0), where it aborted
        #   collection for the whole suite rather than skipping.
        #
        # Both mean "no real SDK here", so fall back to None and let the
        # fixture skip instead of taking down collection.
        return None
    finally:
        # Put the stub back so the rest of the suite sees no change.
        for name in list(sys.modules):
            if name == "lark_oapi" or name.startswith("lark_oapi."):
                del sys.modules[name]
        sys.modules.update(stubbed)


_REAL_RESPONSE = _load_real_response_class()


@pytest.fixture(name="real_response_class", autouse=True)
def _real_response_class(monkeypatch):
    """Give ``handle`` the real SDK response builder where available."""
    if _REAL_RESPONSE is None:
        pytest.skip("lark_oapi SDK not installed")
    monkeypatch.setattr(
        tg,
        "P2CardActionTriggerResponse",
        _REAL_RESPONSE,
    )
    return _REAL_RESPONSE


def _card(raw: str) -> dict:
    return json.loads(raw)


def _handle_with_running_loop(channel, event, action_value):
    """Call ``tg.handle`` while a real loop runs on another thread.

    ``handle`` is synchronous but may block on
    ``run_coroutine_threadsafe(...).result()``, which deadlocks if the
    loop lives on the calling thread.  A background loop mirrors how the
    Feishu SDK dispatches card callbacks.
    """
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        channel._loop = loop
        return tg.handle(channel, event, action_value)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
        channel._loop = None


def _markdown_blocks(card: dict) -> list[str]:
    return [
        element["content"]
        for element in card["elements"]
        if element.get("tag") == "markdown"
    ]


def _action_buttons(card: dict) -> list[dict]:
    for element in card["elements"]:
        if element.get("tag") == "action":
            return element["actions"]
    raise AssertionError("no action element in card")


class _StubChannel:
    """Minimal FeishuChannel stand-in for render/handle."""

    def __init__(
        self,
        *,
        enabled=True,
        recv=("open_id", "ou_1"),
        msg_id="om_1",
    ):
        self.enabled = enabled
        self.channel = "feishu"
        self._recv = recv
        self._msg_id = msg_id
        self.sent: list[tuple] = []
        self.enqueued: list[dict] = []
        self._loop = None

    async def _get_receive_for_send(self, to_handle, send_meta):
        return self._recv

    async def _send_message(
        self,
        receive_id_type,
        receive_id,
        msg_type,
        content,
    ):
        self.sent.append((receive_id_type, receive_id, msg_type, content))
        return self._msg_id

    def _enqueue(self, payload):
        self.enqueued.append(payload)


def _event(content="body text"):
    return SimpleNamespace(content=content, operator=None)


# ---------------------------------------------------------------------------
# Constants / metadata
# ---------------------------------------------------------------------------


class TestModuleMetadata:
    def test_dispatcher_metadata(self):
        assert tg.NAME == "tool_guard_approval"
        assert tg.MESSAGE_TYPE == "tool_guard_approval"
        assert tg.ACTION_TYPE == "tool_guard_approval"

    def test_action_keys(self):
        assert tg.APPROVE_KEY == "approve"
        assert tg.DENY_KEY == "deny"


class TestTruncate:
    @pytest.mark.parametrize("text", ["", None])
    def test_empty(self, text):
        assert tg._truncate(text, 10) == ""

    def test_short_text_untouched(self):
        assert tg._truncate("abc", 10) == "abc"

    def test_exact_limit_untouched(self):
        assert tg._truncate("abcdef", 6) == "abcdef"

    def test_long_text_is_cut_with_ellipsis(self):
        assert tg._truncate("abcdefghij", 6) == "abcde…"
        assert len(tg._truncate("abcdefghij", 6)) == 6

    def test_unicode_preserved(self):
        assert tg._truncate("泰哥你好世界", 4) == "泰哥你…"


class TestSeverityTemplate:
    @pytest.mark.parametrize(
        ("severity", "expected"),
        [
            ("critical", "red"),
            ("high", "red"),
            ("medium", "orange"),
            ("low", "yellow"),
            ("HIGH", "red"),
            (" Low ", "orange"),  # not stripped -> unknown -> default
            ("weird", "orange"),
            ("", "orange"),
            (None, "orange"),
        ],
    )
    def test_mapping(self, severity, expected):
        assert tg._severity_template(severity) == expected


# ---------------------------------------------------------------------------
# build_approval_card
# ---------------------------------------------------------------------------


class TestBuildApprovalCard:
    def test_returns_json_with_header_template(self):
        card = _card(
            tg.build_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="high",
                body_text="danger",
            ),
        )

        assert card["header"]["template"] == "red"
        assert card["header"]["title"]["content"] == (
            "🛡️ Tool Approval Required"
        )
        assert card["config"] == {"wide_screen_mode": True}

    def test_body_is_rendered_as_first_markdown_block(self):
        card = _card(
            tg.build_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="the request body",
            ),
        )

        assert _markdown_blocks(card)[0] == "the request body"

    def test_help_hint_links_to_callback_docs(self):
        card = _card(
            tg.build_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="x",
            ),
        )

        hint = _markdown_blocks(card)[1]
        assert "Buttons not working?" in hint
        assert tg._FEISHU_CALLBACK_CONFIG_DOC_URL in hint

    def test_two_buttons_carry_round_trip_values(self):
        card = _card(
            tg.build_approval_card(
                request_id="req-42",
                tool_name="shell",
                severity="medium",
                body_text="payload body",
                session_ctx={"session_id": "s1"},
            ),
        )

        approve, deny = _action_buttons(card)
        assert approve["text"]["content"] == "✅ Approve"
        assert approve["type"] == "primary"
        assert deny["text"]["content"] == "❌ Deny"
        assert deny["type"] == "danger"

        for button, action in ((approve, "approve"), (deny, "deny")):
            assert button["value"] == {
                "type": tg.ACTION_TYPE,
                "action": action,
                "request_id": "req-42",
                "tool_name": "shell",
                "severity": "medium",
                "body": "payload body",
                "session_ctx": {"session_id": "s1"},
            }

    def test_body_snapshot_is_truncated_separately_from_markdown(self):
        long_body = "x" * 2000
        card = _card(
            tg.build_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text=long_body,
            ),
        )

        # The visible markdown keeps 1800 chars; the button value 1500.
        assert len(_markdown_blocks(card)[0]) == 1800
        assert len(_action_buttons(card)[0]["value"]["body"]) == 1500

    def test_missing_severity_defaults_to_medium_in_value(self):
        card = _card(
            tg.build_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="",
                body_text="x",
            ),
        )

        assert _action_buttons(card)[0]["value"]["severity"] == "medium"
        # The header still falls back to the default template.
        assert card["header"]["template"] == "orange"

    def test_none_session_ctx_becomes_empty_dict(self):
        card = _card(
            tg.build_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="x",
                session_ctx=None,
            ),
        )

        assert _action_buttons(card)[0]["value"]["session_ctx"] == {}

    def test_session_ctx_is_copied_not_aliased(self):
        original = {"session_id": "s1"}
        tg.build_approval_card(
            request_id="r1",
            tool_name="shell",
            severity="low",
            body_text="x",
            session_ctx=original,
        )

        original["session_id"] = "mutated"

        assert original == {"session_id": "mutated"}

    def test_empty_body_text(self):
        card = _card(
            tg.build_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="",
            ),
        )

        assert _markdown_blocks(card)[0] == ""

    def test_unicode_is_not_escaped(self):
        raw = tg.build_approval_card(
            request_id="r1",
            tool_name="shell",
            severity="low",
            body_text="泰哥批准",
        )

        assert "泰哥批准" in raw


# ---------------------------------------------------------------------------
# build_resolved_card
# ---------------------------------------------------------------------------


class TestBuildResolvedCard:
    @pytest.mark.parametrize(
        ("action", "title", "template", "verb"),
        [
            ("approve", "✅ Approved", "green", "approved"),
            ("deny", "🚫 Denied", "red", "denied"),
            ("anything", "⌛ Expired", "grey", "expired"),
            ("", "⌛ Expired", "grey", "expired"),
        ],
    )
    def test_status_variants(self, action, title, template, verb):
        card = _card(
            tg.build_resolved_card(
                tool_name="shell",
                action=action,
            ),
        )

        assert card["header"]["title"]["content"] == title
        assert card["header"]["template"] == template
        blocks = _markdown_blocks(card)
        assert len(blocks) == 1  # no body -> status line only
        assert "shell" in blocks[0]
        assert verb in blocks[0]

    def test_expired_ignores_operator(self):
        card = _card(
            tg.build_resolved_card(
                tool_name="shell",
                action="expired",
                operator_display="alice",
            ),
        )

        assert "alice" not in _markdown_blocks(card)[0]

    def test_operator_is_appended_for_approve(self):
        card = _card(
            tg.build_resolved_card(
                tool_name="shell",
                action="approve",
                operator_display="alice",
            ),
        )

        assert "Tool `shell` approved by `alice`." in _markdown_blocks(card)[0]

    def test_operator_is_appended_for_deny(self):
        card = _card(
            tg.build_resolved_card(
                tool_name="shell",
                action="deny",
                operator_display="bob",
            ),
        )

        assert "denied by `bob`" in _markdown_blocks(card)[0]

    def test_body_text_prepends_a_markdown_block_and_rule(self):
        card = _card(
            tg.build_resolved_card(
                tool_name="shell",
                action="approve",
                body_text="original body",
            ),
        )

        tags = [element["tag"] for element in card["elements"]]
        assert tags == ["markdown", "hr", "markdown"]
        assert _markdown_blocks(card)[0] == "original body"

    def test_body_text_is_truncated(self):
        card = _card(
            tg.build_resolved_card(
                tool_name="shell",
                action="approve",
                body_text="y" * 2500,
            ),
        )

        assert len(_markdown_blocks(card)[0]) == 1800


class TestBuildToast:
    def test_approve(self):
        assert tg.build_toast("approve", "shell") == {
            "type": "success",
            "content": "Approved tool shell",
        }

    def test_deny(self):
        assert tg.build_toast("deny", "shell") == {
            "type": "info",
            "content": "Denied tool shell",
        }

    @pytest.mark.parametrize("action", ["expired", "", "unknown"])
    def test_other_actions(self, action):
        assert tg.build_toast(action, "shell") == {
            "type": "warning",
            "content": "Approval request has expired",
        }


# ---------------------------------------------------------------------------
# parse_action_value
# ---------------------------------------------------------------------------


def _value(**overrides) -> dict:
    data = {
        "type": tg.ACTION_TYPE,
        "action": "approve",
        "request_id": "req-1",
        "tool_name": "shell",
        "severity": "high",
        "body": "b",
        "session_ctx": {"session_id": "s1"},
    }
    data.update(overrides)
    return data


class TestParseActionValue:
    def test_full_payload(self):
        assert tg.parse_action_value(_value()) == {
            "action": "approve",
            "request_id": "req-1",
            "tool_name": "shell",
            "severity": "high",
            "body": "b",
            "session_ctx": {"session_id": "s1"},
        }

    @pytest.mark.parametrize("bad", [None, "string", 42, ["list"]])
    def test_non_dict_is_rejected(self, bad):
        assert tg.parse_action_value(bad) is None

    def test_wrong_action_type_is_rejected(self):
        assert tg.parse_action_value(_value(type="other")) is None

    def test_missing_action_type_is_rejected(self):
        value = _value()
        del value["type"]

        assert tg.parse_action_value(value) is None

    @pytest.mark.parametrize(
        "action",
        ["approve", "deny", " APPROVE ", "Deny"],
    )
    def test_action_is_normalised(self, action):
        assert tg.parse_action_value(_value(action=action))["action"] == (
            action.strip().lower()
        )

    @pytest.mark.parametrize("action", ["", None, "maybe", "approve_all"])
    def test_unknown_action_is_rejected(self, action):
        assert tg.parse_action_value(_value(action=action)) is None

    @pytest.mark.parametrize("request_id", ["", None, "   "])
    def test_blank_request_id_is_rejected(self, request_id):
        assert tg.parse_action_value(_value(request_id=request_id)) is None

    def test_request_id_is_stripped(self):
        assert (
            tg.parse_action_value(_value(request_id="  r1 "))["request_id"]
            == "r1"
        )

    def test_optional_fields_default(self):
        parsed = tg.parse_action_value(
            {
                "type": tg.ACTION_TYPE,
                "action": "deny",
                "request_id": "r1",
            },
        )

        assert parsed == {
            "action": "deny",
            "request_id": "r1",
            "tool_name": "",
            "severity": "medium",
            "body": "",
            "session_ctx": {},
        }

    @pytest.mark.parametrize("ctx", [None, "string", 42, ["list"]])
    def test_non_dict_session_ctx_becomes_empty_dict(self, ctx):
        assert (
            tg.parse_action_value(_value(session_ctx=ctx))["session_ctx"] == {}
        )

    def test_round_trip_from_built_card(self):
        raw = tg.build_approval_card(
            request_id="rt-1",
            tool_name="python",
            severity="critical",
            body_text="round trip",
            session_ctx={"session_id": "sw-1"},
        )
        approve_value = _action_buttons(_card(raw))[0]["value"]

        assert tg.parse_action_value(approve_value) == {
            "action": "approve",
            "request_id": "rt-1",
            "tool_name": "python",
            "severity": "critical",
            "body": "round trip",
            "session_ctx": {"session_id": "sw-1"},
        }


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def _meta(**overrides) -> dict:
    data = {
        "approval_request_id": "req-1",
        "tool_name": "shell",
        "severity": "high",
    }
    data.update(overrides)
    return data


class TestRender:
    @pytest.mark.parametrize(
        "meta",
        [{}, {"approval_request_id": ""}, {"approval_request_id": None}],
    )
    async def test_missing_request_id_is_skipped(self, meta):
        channel = _StubChannel()

        assert await tg.render(channel, "h", _event(), {}, meta) is False
        assert channel.sent == []

    async def test_disabled_channel_is_skipped(self):
        channel = _StubChannel(enabled=False)

        assert await tg.render(channel, "h", _event(), {}, _meta()) is False
        assert channel.sent == []

    async def test_unresolved_receive_id_is_skipped(self):
        channel = _StubChannel(recv=None)

        assert await tg.render(channel, "h", _event(), {}, _meta()) is False
        assert channel.sent == []

    async def test_sends_interactive_card(self):
        channel = _StubChannel(recv=("chat_id", "oc_9"), msg_id="om_77")
        send_meta = {"feishu_sender_id": "ou_s", "feishu_chat_id": "oc_9"}

        result = await tg.render(
            channel,
            "feishu:sw:sess-1",
            _event("please approve"),
            send_meta,
            _meta(),
        )

        assert result is True
        assert len(channel.sent) == 1
        receive_id_type, receive_id, msg_type, content = channel.sent[0]
        assert (receive_id_type, receive_id, msg_type) == (
            "chat_id",
            "oc_9",
            "interactive",
        )
        card = _card(content)
        assert card["header"]["template"] == "red"
        assert _action_buttons(card)[0]["value"]["request_id"] == "req-1"

    async def test_last_sent_message_id_is_recorded(self):
        channel = _StubChannel(msg_id="om_99")
        send_meta = {}

        await tg.render(channel, "h", _event(), send_meta, _meta())

        assert send_meta["_last_sent_message_id"] == "om_99"

    async def test_session_ctx_embeds_routing_from_to_handle(self):
        channel = _StubChannel(recv=("open_id", "ou_5"))
        send_meta = {
            "feishu_sender_id": "ou_s",
            "feishu_chat_id": "oc_c",
            "feishu_chat_type": "group",
            "is_group": True,
        }

        await tg.render(
            channel,
            "feishu:sw:sess-9",
            _event(),
            send_meta,
            _meta(),
        )

        value = _action_buttons(_card(channel.sent[0][3]))[0]["value"]
        assert value["session_ctx"] == {
            "session_id": "sess-9",
            "sender_id": "ou_s",
            "receive_id": "ou_5",
            "receive_id_type": "open_id",
            "chat_id": "oc_c",
            "chat_type": "group",
            "is_group": True,
        }

    async def test_body_text_flattened_from_content_list(self):
        channel = _StubChannel()
        event = _event(
            content=[
                {"type": "text", "text": "first "},
                {"type": "text", "text": "second"},
            ],
        )

        await tg.render(channel, "h", event, {}, _meta())

        assert _markdown_blocks(_card(channel.sent[0][3]))[0] == (
            "first second"
        )

    async def test_missing_optional_meta_falls_back(self):
        channel = _StubChannel()

        result = await tg.render(
            channel,
            "h",
            _event(),
            {},
            {"approval_request_id": "only-id"},
        )

        assert result is True
        value = _action_buttons(_card(channel.sent[0][3]))[0]["value"]
        assert value["tool_name"] == "tool"
        assert value["severity"] == "medium"

    async def test_send_failure_returns_false(self):
        channel = _StubChannel(msg_id="")
        send_meta = {}

        result = await tg.render(channel, "h", _event(), send_meta, _meta())

        assert result is False
        assert "_last_sent_message_id" not in send_meta
        assert len(channel.sent) == 1

    async def test_extra_kwargs_are_ignored(self):
        channel = _StubChannel()

        assert (
            await tg.render(
                channel,
                "h",
                _event(),
                {},
                _meta(),
                unknown="x",
            )
            is True
        )


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------


def _click_event(open_id=None):
    operator = SimpleNamespace(open_id=open_id) if open_id else None
    return SimpleNamespace(operator=operator)


class TestHandle:
    def test_unparsable_value_returns_empty_response(self):
        channel = _StubChannel()

        response = tg.handle(channel, _click_event(), {"type": "other"})

        assert response.toast is None
        assert response.card is None
        assert channel.enqueued == []

    def test_approve_enqueues_command_and_resolves_card(self):
        channel = _StubChannel()

        response = tg.handle(
            channel,
            _click_event(),
            _value(session_ctx={"session_id": "sw-1", "sender_id": "ou_s"}),
        )

        assert response.toast.type == "success"
        assert response.card.type == "raw"
        assert response.card.data["header"]["title"]["content"] == (
            "✅ Approved"
        )
        payload = channel.enqueued[0]
        assert payload["content_parts"][0].text == "/approval approve req-1"
        assert payload["channel_id"] == "feishu"
        assert payload["session_id"] == "sw-1"
        assert payload["sender_id"] == "ou_s"

    def test_deny_produces_info_toast(self):
        channel = _StubChannel()

        response = tg.handle(channel, _click_event(), _value(action="deny"))

        assert response.toast.type == "info"
        assert response.card.data["header"]["template"] == "red"
        assert channel.enqueued[0]["content_parts"][0].text == (
            "/approval deny req-1"
        )

    def test_missing_tool_name_defaults_to_tool(self):
        channel = _StubChannel()

        response = tg.handle(channel, _click_event(), _value(tool_name=""))

        assert response.toast.content == "Approved tool tool"

    def test_meta_falls_back_to_operator_open_id(self):
        channel = _StubChannel()

        tg.handle(
            channel,
            _click_event(open_id="ou_operator"),
            _value(session_ctx={}),
        )

        meta = channel.enqueued[0]["meta"]
        assert meta["feishu_sender_id"] == "ou_operator"
        assert meta["from_card_action"] is True
        assert meta["feishu_receive_id_type"] == "open_id"
        assert meta["feishu_chat_type"] == "p2p"
        assert meta["is_group"] is False

    def test_session_ctx_meta_is_forwarded(self):
        channel = _StubChannel()

        tg.handle(
            channel,
            _click_event(),
            _value(
                session_ctx={
                    "session_id": "sw-2",
                    "sender_id": "ou_s",
                    "receive_id": "oc_r",
                    "receive_id_type": "chat_id",
                    "chat_id": "oc_c",
                    "chat_type": "group",
                    "is_group": True,
                },
            ),
        )

        payload = channel.enqueued[0]
        assert payload["user_id"] == "ou_s"
        assert payload["meta"] == {
            "feishu_sender_id": "ou_s",
            "feishu_chat_id": "oc_c",
            "feishu_chat_type": "group",
            "feishu_receive_id": "oc_r",
            "feishu_receive_id_type": "chat_id",
            "is_group": True,
            "from_card_action": True,
        }

    def test_operator_display_falls_back_to_open_id_suffix(self):
        channel = _StubChannel()

        response = tg.handle(
            channel,
            _click_event(open_id="ou_abcdef1234"),
            _value(),
        )

        # No running loop: the tail of the open_id is used.
        assert "f1234" in response.card.data["elements"][-1]["content"]

    def test_event_without_operator(self):
        channel = _StubChannel()

        response = tg.handle(channel, None, _value())

        assert response.toast.type == "success"
        assert "by `" not in response.card.data["elements"][-1]["content"]

    def test_channel_without_enqueue_is_dropped(self):
        class _NoEnqueue(_StubChannel):
            _enqueue = None

        channel = _NoEnqueue()

        response = tg.handle(channel, _click_event(), _value())

        # The card response is still built.
        assert response.toast.type == "success"

    def test_running_loop_resolves_operator_name(self):
        channel = _StubChannel()

        async def lookup(open_id):
            assert open_id == "ou_1"
            return "张三"

        channel._get_user_name_by_open_id = lookup

        response = _handle_with_running_loop(
            channel,
            _click_event(open_id="ou_1"),
            _value(),
        )

        assert "张三" in response.card.data["elements"][-1]["content"]

    def test_name_lookup_failure_keeps_suffix(self):
        channel = _StubChannel()

        async def lookup(_open_id):
            raise RuntimeError("no user")

        channel._get_user_name_by_open_id = lookup

        response = _handle_with_running_loop(
            channel,
            _click_event(open_id="ou_xyz123"),
            _value(),
        )

        content = response.card.data["elements"][-1]["content"]
        assert "xyz123" in content
        assert "no user" not in content

    def test_lookup_timeout_keeps_suffix(self):
        channel = _StubChannel()

        async def lookup(_open_id):
            await asyncio.sleep(30)
            return "too late"

        channel._get_user_name_by_open_id = lookup

        response = _handle_with_running_loop(
            channel,
            _click_event(open_id="ou_slow99"),
            _value(),
        )

        assert "slow99" in response.card.data["elements"][-1]["content"]

    def test_empty_name_keeps_suffix(self):
        channel = _StubChannel()

        async def lookup(_open_id):
            return ""

        channel._get_user_name_by_open_id = lookup

        response = _handle_with_running_loop(
            channel,
            _click_event(open_id="ou_tail99"),
            _value(),
        )

        assert "tail99" in response.card.data["elements"][-1]["content"]

    def test_body_is_carried_into_resolved_card(self):
        channel = _StubChannel()

        response = tg.handle(channel, _click_event(), _value(body="the body"))

        blocks = [
            element["content"]
            for element in response.card.data["elements"]
            if element.get("tag") == "markdown"
        ]
        assert blocks[0] == "the body"
        assert "approved" in blocks[-1]

    def test_response_builder_failure_falls_back_to_toast(self):
        channel = _StubChannel()
        calls = {"n": 0}

        def flaky(payload):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("cannot build")
            return _REAL_RESPONSE(payload)

        with patch.object(tg, "P2CardActionTriggerResponse", flaky):
            response = tg.handle(channel, _click_event(), _value())

        assert response.toast.type == "success"
        assert response.card is None
        assert calls["n"] == 2
