# -*- coding: utf-8 -*-
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for the Feishu interactive-card handler.

``FeishuCardHandler`` keeps no business state of its own: it is a
registry that maps an outgoing ``metadata.message_type`` to a render
coroutine and an incoming button ``value.type`` to a sync handler, and
it piggybacks on the owning channel's primitives.

These tests cover:

* registry installation and the duplicate-key override warnings
* ``try_send_card_for_event`` dispatch (no metadata / unknown type /
  matching kind / render raising)
* ``handle_card_action`` dispatch, including the cross-instance app_id
  guard and the non-dict action-value guard
* the tool-guard outbound card (disabled channel, missing receive id,
  send failure, success recording the sent message id)
* the tool-guard inbound action (enqueueing ``/approval`` into the
  channel queue, operator display-name fallbacks, card response shape)
* the pure helpers ``_build_session_ctx`` / ``_extract_meta`` /
  ``_extract_body_text``
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from qwenpaw.app.channels.feishu import card_handler as ch
from qwenpaw.app.channels.feishu.card_handler import (
    CardKind,
    FeishuCardHandler,
)
from qwenpaw.app.channels.feishu.card_templates import (
    TOOL_GUARD_ACTION_TYPE,
)


# ---------------------------------------------------------------------
# Real Feishu SDK response class
# ---------------------------------------------------------------------
# ``tests/conftest.py`` stubs ``lark_oapi`` with a MagicMock, so the
# module-level import of ``P2CardActionTriggerResponse`` in
# ``card_handler`` raises and the name stays ``None``.  Every early exit
# of ``handle_card_action`` builds ``P2CardActionTriggerResponse({})``,
# which would then fail with "'NoneType' object is not callable".
# Load the real class once (mirroring the existing
# ``test_cards_tool_guard.py`` approach) without disturbing the global
# stub, so the handler can build genuine responses.
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
    except ImportError:  # SDK genuinely absent -> skip those tests
        return None
    finally:
        for name in list(sys.modules):
            if name == "lark_oapi" or name.startswith("lark_oapi."):
                del sys.modules[name]
        sys.modules.update(stubbed)


_REAL_RESPONSE = _load_real_response_class()


@pytest.fixture(name="real_response_class", autouse=True)
def _real_response_class(monkeypatch):
    """Give the handler the real SDK response builder where available."""
    if _REAL_RESPONSE is None:
        pytest.skip("lark_oapi SDK not installed")
    monkeypatch.setattr(ch, "P2CardActionTriggerResponse", _REAL_RESPONSE)
    return _REAL_RESPONSE


# ---------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------


class _StubChannel:
    """Minimal FeishuChannel stand-in.

    Records every card send and every enqueued command payload so the
    tests can assert on observable side effects instead of internals.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        recv: Optional[Tuple[str, str]] = ("open_id", "ou_recv_1"),
        msg_id: Optional[str] = "om_sent_1",
        app_id: str = "cli_app_1",
    ) -> None:
        self.enabled = enabled
        self.channel = "feishu"
        self.app_id = app_id
        self._recv = recv
        self._msg_id = msg_id
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.sent: List[Tuple[str, str, str, str]] = []
        self.enqueued: List[Dict[str, Any]] = []
        self.recv_calls: List[Tuple[str, Dict[str, Any]]] = []
        self.name_lookups: List[str] = []

    def _enqueue(self, payload: Dict[str, Any]) -> None:
        self.enqueued.append(payload)

    async def _get_receive_for_send(
        self,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> Optional[Tuple[str, str]]:
        self.recv_calls.append((to_handle, send_meta))
        return self._recv

    async def _send_message(
        self,
        receive_id_type: str,
        receive_id: str,
        msg_type: str,
        content: str,
    ) -> Optional[str]:
        self.sent.append((receive_id_type, receive_id, msg_type, content))
        return self._msg_id

    async def _get_user_name_by_open_id(self, open_id: str) -> Optional[str]:
        self.name_lookups.append(open_id)
        return None


def _event(
    *,
    metadata: Any = None,
    content: Any = None,
    operator_open_id: Optional[str] = None,
) -> SimpleNamespace:
    """Build a stand-in for the Runner ``Message`` object."""
    event = SimpleNamespace()
    if metadata is not None:
        event.metadata = metadata
    if content is not None:
        event.content = content
    if operator_open_id is not None:
        event.operator = SimpleNamespace(open_id=operator_open_id)
    else:
        event.operator = None
    return event


def _approval_meta(
    *,
    request_id: str = "req_12345678",
    tool_name: str = "shell",
    severity: str = "high",
) -> Dict[str, Any]:
    """Metadata for a tool-guard approval card, wrapped like Runner does."""
    return {
        "metadata": {
            "message_type": "tool_guard_approval",
            "approval_request_id": request_id,
            "tool_name": tool_name,
            "severity": severity,
        },
    }


def _action_trigger(
    *,
    action_value: Any,
    app_id: str = "cli_app_1",
    operator_open_id: Optional[str] = "ou_op_1",
) -> SimpleNamespace:
    """Build a stand-in for ``P2CardActionTrigger``."""
    return SimpleNamespace(
        header=SimpleNamespace(app_id=app_id),
        event=SimpleNamespace(
            action=SimpleNamespace(value=action_value),
            operator=(
                SimpleNamespace(open_id=operator_open_id)
                if operator_open_id
                else None
            ),
        ),
    )


def _tool_guard_value(
    *,
    action: str = "approve",
    request_id: str = "req_12345678",
    session_ctx: Optional[Dict[str, Any]] = None,
    tool_name: str = "shell",
    body: str = "run it",
) -> Dict[str, Any]:
    """A well-formed tool-guard button ``value`` payload."""
    return {
        "type": TOOL_GUARD_ACTION_TYPE,
        "action": action,
        "request_id": request_id,
        "session_ctx": session_ctx
        if session_ctx is not None
        else {
            "session_id": "sess_1",
            "sender_id": "ou_sender_1",
            "receive_id": "ou_recv_1",
            "receive_id_type": "open_id",
            "chat_id": "oc_chat_1",
            "chat_type": "group",
            "is_group": True,
        },
        "tool_name": tool_name,
        "body": body,
    }


# ---------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------


class TestRegistry:
    def test_builtin_tool_guard_kind_is_registered(self):
        handler = FeishuCardHandler(_StubChannel())

        assert "tool_guard_approval" in handler._by_message_type
        assert TOOL_GUARD_ACTION_TYPE in handler._by_action_type

        kind = handler._by_message_type["tool_guard_approval"]
        assert kind.name == "tool_guard_approval"
        assert kind.message_type == "tool_guard_approval"
        assert kind.action_type == TOOL_GUARD_ACTION_TYPE

    def test_same_kind_object_in_both_tables(self):
        handler = FeishuCardHandler(_StubChannel())

        assert (
            handler._by_message_type["tool_guard_approval"]
            is handler._by_action_type[TOOL_GUARD_ACTION_TYPE]
        )

    def test_register_installs_into_both_tables(self):
        handler = FeishuCardHandler(_StubChannel())

        async def _render(*_args: Any, **_kwargs: Any) -> bool:
            return True

        def _handle(_event: Any, _value: Dict[str, Any]) -> Any:
            return None

        kind = CardKind(
            name="extra",
            message_type="extra_msg",
            action_type="extra_action",
            render=_render,
            handle=_handle,
        )
        handler._register(kind)

        assert handler._by_message_type["extra_msg"] is kind
        assert handler._by_action_type["extra_action"] is kind

    def test_duplicate_message_type_warns_and_overrides(self, caplog):
        handler = FeishuCardHandler(_StubChannel())

        async def _render_a(*_args: Any, **_kwargs: Any) -> bool:
            return True

        async def _render_b(*_args: Any, **_kwargs: Any) -> bool:
            return False

        def _handle(_event: Any, _value: Dict[str, Any]) -> Any:
            return None

        first = CardKind(
            name="a",
            message_type="dup_msg",
            action_type="action_a",
            render=_render_a,
            handle=_handle,
        )
        second = CardKind(
            name="b",
            message_type="dup_msg",
            action_type="action_b",
            render=_render_b,
            handle=_handle,
        )

        with caplog.at_level("WARNING"):
            handler._register(first)
            handler._register(second)

        assert handler._by_message_type["dup_msg"] is second
        assert "dup_msg" in caplog.text
        assert "already registered" in caplog.text

    def test_duplicate_action_type_warns_and_overrides(self, caplog):
        handler = FeishuCardHandler(_StubChannel())

        async def _render(*_args: Any, **_kwargs: Any) -> bool:
            return True

        def _handle(_event: Any, _value: Dict[str, Any]) -> Any:
            return None

        first = CardKind(
            name="a",
            message_type="msg_a",
            action_type="dup_action",
            render=_render,
            handle=_handle,
        )
        second = CardKind(
            name="b",
            message_type="msg_b",
            action_type="dup_action",
            render=_render,
            handle=_handle,
        )

        with caplog.at_level("WARNING"):
            handler._register(first)
            handler._register(second)

        assert handler._by_action_type["dup_action"] is second
        assert "dup_action" in caplog.text

    def test_card_kind_is_frozen(self):
        handler = FeishuCardHandler(_StubChannel())
        kind = handler._by_message_type["tool_guard_approval"]

        with pytest.raises(Exception):
            kind.name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------
# try_send_card_for_event
# ---------------------------------------------------------------------


class TestTrySendCardForEvent:
    async def test_returns_false_without_metadata(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        assert (
            await handler.try_send_card_for_event(
                "feishu:sw:sess_1",
                _event(),
                {},
            )
            is False
        )
        assert channel.sent == []

    async def test_returns_false_when_metadata_not_a_dict(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata="not-a-dict"),
            {},
        )

        assert result is False
        assert channel.sent == []

    async def test_returns_false_for_unknown_message_type(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata={"message_type": "no_such_kind"}),
            {},
        )

        assert result is False
        assert channel.sent == []

    async def test_returns_false_when_message_type_is_empty(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata={"message_type": ""}),
            {},
        )

        assert result is False
        assert channel.sent == []

    async def test_treats_missing_message_type_as_empty(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata={"other": 1}),
            {},
        )

        assert result is False

    async def test_dispatches_matching_kind(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)
        calls: List[Tuple[Any, ...]] = []

        async def _render(*args: Any, **_kwargs: Any) -> bool:
            calls.append(args)
            return True

        handler._register(
            CardKind(
                name="probe",
                message_type="probe_msg",
                action_type="probe_action",
                render=_render,
                handle=lambda _e, _v: None,
            ),
        )

        event = _event(metadata={"message_type": "probe_msg"})
        send_meta = {"feishu_sender_id": "ou_sender_1"}

        assert (
            await handler.try_send_card_for_event(
                "feishu:sw:sess_1",
                event,
                send_meta,
            )
            is True
        )
        assert len(calls) == 1
        assert calls[0][0] == "feishu:sw:sess_1"
        assert calls[0][1] is event
        assert calls[0][2] is send_meta
        assert calls[0][3] == {"message_type": "probe_msg"}

    async def test_unwraps_nested_metadata_before_dispatch(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(
                metadata={
                    "metadata": {"message_type": "no_such_kind"},
                },
            ),
            {},
        )

        # The inner dict was unwrapped, so the lookup ran and missed.
        assert result is False

    async def test_render_returning_false_propagates(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        async def _render(*_args: Any, **_kwargs: Any) -> bool:
            return False

        handler._register(
            CardKind(
                name="declines",
                message_type="declines_msg",
                action_type="declines_action",
                render=_render,
                handle=lambda _e, _v: None,
            ),
        )

        assert (
            await handler.try_send_card_for_event(
                "feishu:sw:sess_1",
                _event(metadata={"message_type": "declines_msg"}),
                {},
            )
            is False
        )


# ---------------------------------------------------------------------
# handle_card_action
# ---------------------------------------------------------------------


class TestHandleCardAction:
    def test_rejects_foreign_app_id(self):
        channel = _StubChannel(app_id="cli_mine")
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(
                action_value=_tool_guard_value(),
                app_id="cli_other",
            ),
        )

        assert response.toast is None
        assert channel.enqueued == []

    def test_accepts_missing_app_id_header(self):
        channel = _StubChannel(app_id="cli_mine")
        handler = FeishuCardHandler(channel)
        data = _action_trigger(action_value=_tool_guard_value())
        data.header = None

        response = handler.handle_card_action(data)

        # Not rejected by the guard: the action was dispatched.
        assert len(channel.enqueued) == 1
        assert response.toast is not None

    def test_rejects_missing_event(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)
        data = SimpleNamespace(header=None, event=None)

        response = handler.handle_card_action(data)

        assert response.toast is None
        assert channel.enqueued == []

    def test_rejects_missing_action(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)
        data = SimpleNamespace(
            header=None,
            event=SimpleNamespace(action=None, operator=None),
        )

        response = handler.handle_card_action(data)

        assert response.toast is None
        assert channel.enqueued == []

    def test_rejects_non_dict_action_value(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(action_value="not-a-dict"),
        )

        assert response.toast is None
        assert channel.enqueued == []

    def test_rejects_none_action_value(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(action_value=None),
        )

        assert response.toast is None
        assert channel.enqueued == []

    def test_rejects_unknown_action_type(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(action_value={"type": "no_such_action"}),
        )

        assert response.toast is None
        assert channel.enqueued == []

    def test_treats_missing_action_type_as_unknown(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(action_value={"action": "allow_once"}),
        )

        assert response.toast is None
        assert channel.enqueued == []


# ---------------------------------------------------------------------
# tool-guard: outbound
# ---------------------------------------------------------------------


class TestToolGuardApprovalCard:
    async def test_returns_false_without_request_id(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)
        meta = _approval_meta()
        meta["metadata"]["approval_request_id"] = ""

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata=meta),
            {},
        )

        assert result is False
        assert channel.sent == []

    async def test_returns_false_when_channel_disabled(self):
        channel = _StubChannel(enabled=False)
        handler = FeishuCardHandler(channel)

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata=_approval_meta()),
            {},
        )

        assert result is False
        assert channel.recv_calls == []
        assert channel.sent == []

    async def test_returns_false_without_receive_id(self, caplog):
        channel = _StubChannel(recv=None)
        handler = FeishuCardHandler(channel)

        with caplog.at_level("WARNING"):
            result = await handler.try_send_card_for_event(
                "feishu:sw:sess_1",
                _event(metadata=_approval_meta()),
                {},
            )

        assert result is False
        assert channel.sent == []
        assert "no receive_id" in caplog.text

    async def test_sends_interactive_card(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)
        send_meta = {
            "feishu_sender_id": "ou_sender_1",
            "feishu_chat_id": "oc_chat_1",
            "feishu_chat_type": "group",
            "is_group": True,
        }

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(
                metadata=_approval_meta(),
                content=[SimpleNamespace(text="rm -rf /tmp/x")],
            ),
            send_meta,
        )

        assert result is True
        assert len(channel.sent) == 1
        receive_id_type, receive_id, msg_type, content = channel.sent[0]
        assert receive_id_type == "open_id"
        assert receive_id == "ou_recv_1"
        assert msg_type == "interactive"

        card = json.loads(content)
        assert card["config"]["wide_screen_mode"] is True
        assert (
            card["header"]["title"]["content"] == "🛡️ Tool Approval Required"
        )
        assert "rm -rf /tmp/x" in json.dumps(card)

    async def test_records_sent_message_id_on_send_meta(self):
        channel = _StubChannel(msg_id="om_recorded")
        handler = FeishuCardHandler(channel)
        send_meta: Dict[str, Any] = {}

        await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata=_approval_meta()),
            send_meta,
        )

        assert send_meta["_last_sent_message_id"] == "om_recorded"

    async def test_embeds_session_ctx_in_the_card(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)
        send_meta = {
            "feishu_sender_id": "ou_sender_1",
            "feishu_chat_id": "oc_chat_1",
            "feishu_chat_type": "group",
            "is_group": True,
        }

        await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata=_approval_meta()),
            send_meta,
        )

        content = channel.sent[0][3]
        card = json.loads(content)
        blob = json.dumps(card)
        assert "sess_1" in blob
        assert "ou_sender_1" in blob
        assert "oc_chat_1" in blob

    async def test_returns_false_when_send_fails(self, caplog):
        channel = _StubChannel(msg_id=None)
        handler = FeishuCardHandler(channel)
        send_meta: Dict[str, Any] = {}

        with caplog.at_level("WARNING"):
            result = await handler.try_send_card_for_event(
                "feishu:sw:sess_1",
                _event(metadata=_approval_meta()),
                send_meta,
            )

        assert result is False
        assert "_last_sent_message_id" not in send_meta
        assert "send failed" in caplog.text

    async def test_falls_back_to_default_tool_name_and_severity(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)
        meta = _approval_meta()
        del meta["metadata"]["tool_name"]
        del meta["metadata"]["severity"]

        result = await handler.try_send_card_for_event(
            "feishu:sw:sess_1",
            _event(metadata=meta),
            {},
        )

        assert result is True
        card = json.loads(channel.sent[0][3])
        blob = json.dumps(card)
        assert "tool" in blob
        assert "medium" in blob.lower()


# ---------------------------------------------------------------------
# tool-guard: inbound
# ---------------------------------------------------------------------


class TestToolGuardAction:
    def test_enqueues_approval_command(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(action_value=_tool_guard_value()),
        )

        assert len(channel.enqueued) == 1
        payload = channel.enqueued[0]
        assert payload["channel_id"] == "feishu"
        assert payload["sender_id"] == "ou_sender_1"
        assert payload["user_id"] == "ou_sender_1"
        assert payload["session_id"] == "sess_1"

        text = payload["content_parts"][0].text
        assert text == "/approval approve req_12345678"
        assert response.toast is not None

    def test_enqueued_meta_carries_routing_info(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        handler.handle_card_action(
            _action_trigger(action_value=_tool_guard_value()),
        )

        meta = channel.enqueued[0]["meta"]
        assert meta["feishu_sender_id"] == "ou_sender_1"
        assert meta["feishu_chat_id"] == "oc_chat_1"
        assert meta["feishu_chat_type"] == "group"
        assert meta["feishu_receive_id"] == "ou_recv_1"
        assert meta["feishu_receive_id_type"] == "open_id"
        assert meta["is_group"] is True
        assert meta["from_card_action"] is True

    def test_response_contains_resolved_card(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(action_value=_tool_guard_value()),
        )

        assert response.card.type == "raw"
        blob = json.dumps(response.card.data)
        assert "shell" in blob

    def test_deny_action_is_enqueued_verbatim(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        handler.handle_card_action(
            _action_trigger(
                action_value=_tool_guard_value(action="deny"),
            ),
        )

        assert (
            channel.enqueued[0]["content_parts"][0].text
            == "/approval deny req_12345678"
        )

    def test_missing_session_ctx_falls_back_to_operator(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        handler.handle_card_action(
            _action_trigger(
                action_value=_tool_guard_value(session_ctx={}),
            ),
        )

        payload = channel.enqueued[0]
        assert payload["sender_id"] == "ou_op_1"
        assert payload["session_id"] == ""
        meta = payload["meta"]
        assert meta["feishu_receive_id_type"] == "open_id"
        assert meta["feishu_chat_type"] == "p2p"
        assert meta["is_group"] is False

    def test_no_operator_and_no_session_ctx_sender_is_empty(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        handler.handle_card_action(
            _action_trigger(
                action_value=_tool_guard_value(session_ctx={}),
                operator_open_id=None,
            ),
        )

        assert channel.enqueued[0]["sender_id"] == ""

    def test_operator_display_falls_back_to_open_id_suffix(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(
                action_value=_tool_guard_value(),
                operator_open_id="ou_operator_999",
            ),
        )

        blob = json.dumps(response.card.data)
        assert "_999" in blob

    def test_running_loop_resolves_operator_name(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        async def _named(open_id: str) -> str:
            channel.name_lookups.append(open_id)
            return "Alice"

        channel._get_user_name_by_open_id = _named

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            channel._loop = loop
            response = handler.handle_card_action(
                _action_trigger(
                    action_value=_tool_guard_value(),
                    operator_open_id="ou_named_1",
                ),
            )
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()
            channel._loop = None

        assert channel.name_lookups == ["ou_named_1"]
        blob = json.dumps(response.card.data)
        assert "Alice" in blob

    def test_name_lookup_failure_keeps_fallback(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        async def _boom(_open_id: str) -> str:
            raise RuntimeError("lookup down")

        channel._get_user_name_by_open_id = _boom

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            channel._loop = loop
            response = handler.handle_card_action(
                _action_trigger(
                    action_value=_tool_guard_value(),
                    operator_open_id="ou_fallback_7",
                ),
            )
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()
            channel._loop = None

        blob = json.dumps(response.card.data)
        assert "ck_7" in blob or "ut_7" in blob

    def test_empty_operator_name_keeps_fallback(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        async def _empty(_open_id: str) -> str:
            return ""

        channel._get_user_name_by_open_id = _empty

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            channel._loop = loop
            response = handler.handle_card_action(
                _action_trigger(
                    action_value=_tool_guard_value(),
                    operator_open_id="ou_blank_1",
                ),
            )
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()
            channel._loop = None

        blob = json.dumps(response.card.data)
        assert "nk_1" in blob

    def test_missing_enqueue_drops_command_but_builds_response(
        self,
        caplog,
    ):
        class _NoEnqueue(_StubChannel):
            _enqueue = None  # type: ignore[assignment]

        no_enqueue = _NoEnqueue()
        handler = FeishuCardHandler(no_enqueue)

        with caplog.at_level("WARNING"):
            response = handler.handle_card_action(
                _action_trigger(action_value=_tool_guard_value()),
            )

        assert no_enqueue.enqueued == []
        assert "enqueue not set" in caplog.text
        assert response.toast is not None

    def test_enqueue_failure_is_swallowed(self, caplog):
        class _BadEnqueue(_StubChannel):
            def _enqueue(self, _payload: Dict[str, Any]) -> None:
                raise RuntimeError("queue full")

        channel = _BadEnqueue()
        handler = FeishuCardHandler(channel)

        with caplog.at_level("ERROR"):
            response = handler.handle_card_action(
                _action_trigger(action_value=_tool_guard_value()),
            )

        assert "enqueue command failed" in caplog.text
        assert response.toast is not None

    def test_unparsable_action_value_returns_empty_response(self):
        channel = _StubChannel()
        handler = FeishuCardHandler(channel)

        response = handler.handle_card_action(
            _action_trigger(
                action_value={
                    "type": TOOL_GUARD_ACTION_TYPE,
                    "action": "",
                    "request_id": "",
                },
            ),
        )

        assert channel.enqueued == []
        assert response.toast is None


# ---------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------


class TestBuildSessionCtx:
    def test_extracts_short_session_id(self):
        ctx = FeishuCardHandler._build_session_ctx(
            to_handle="feishu:sw:sess_abc",
            send_meta={
                "feishu_sender_id": "ou_sender_1",
                "feishu_chat_id": "oc_chat_1",
                "feishu_chat_type": "group",
                "is_group": True,
            },
            receive_id="ou_recv_1",
            receive_id_type="open_id",
        )

        assert ctx == {
            "session_id": "sess_abc",
            "sender_id": "ou_sender_1",
            "receive_id": "ou_recv_1",
            "receive_id_type": "open_id",
            "chat_id": "oc_chat_1",
            "chat_type": "group",
            "is_group": True,
        }

    def test_non_matching_handle_yields_empty_session_id(self):
        ctx = FeishuCardHandler._build_session_ctx(
            to_handle="feishu:other:xyz",
            send_meta={},
            receive_id="ou_recv_1",
            receive_id_type="open_id",
        )

        assert ctx["session_id"] == ""

    def test_prefix_match_is_case_sensitive(self):
        ctx = FeishuCardHandler._build_session_ctx(
            to_handle="FEISHU:SW:sess_1",
            send_meta={},
            receive_id="ou_recv_1",
            receive_id_type="open_id",
        )

        assert ctx["session_id"] == ""

    def test_handle_is_stripped(self):
        ctx = FeishuCardHandler._build_session_ctx(
            to_handle="  feishu:sw:sess_pad  ",
            send_meta={},
            receive_id="ou_recv_1",
            receive_id_type="open_id",
        )

        assert ctx["session_id"] == "sess_pad"

    def test_empty_and_none_handles(self):
        for handle in ("", None):
            ctx = FeishuCardHandler._build_session_ctx(
                to_handle=handle,  # type: ignore[arg-type]
                send_meta={},
                receive_id="",
                receive_id_type="",
            )
            assert ctx["session_id"] == ""

    def test_defaults_for_missing_send_meta(self):
        ctx = FeishuCardHandler._build_session_ctx(
            to_handle="feishu:sw:sess_1",
            send_meta={},
            receive_id="ou_recv_1",
            receive_id_type="open_id",
        )

        assert ctx["sender_id"] == ""
        assert ctx["chat_id"] == ""
        assert ctx["chat_type"] == "p2p"
        assert ctx["is_group"] is False

    def test_falsy_chat_type_falls_back_to_p2p(self):
        ctx = FeishuCardHandler._build_session_ctx(
            to_handle="feishu:sw:sess_1",
            send_meta={"feishu_chat_type": ""},
            receive_id="ou_recv_1",
            receive_id_type="open_id",
        )

        assert ctx["chat_type"] == "p2p"

    def test_is_group_coerced_to_bool(self):
        ctx = FeishuCardHandler._build_session_ctx(
            to_handle="feishu:sw:sess_1",
            send_meta={"is_group": "yes"},
            receive_id="ou_recv_1",
            receive_id_type="open_id",
        )

        assert ctx["is_group"] is True


class TestExtractMeta:
    def test_unwraps_nested_metadata(self):
        meta = FeishuCardHandler._extract_meta(
            _event(metadata={"metadata": {"message_type": "inner"}}),
        )

        assert meta == {"message_type": "inner"}

    def test_returns_flat_metadata_when_no_inner(self):
        meta = FeishuCardHandler._extract_meta(
            _event(metadata={"message_type": "flat"}),
        )

        assert meta == {"message_type": "flat"}

    def test_returns_flat_metadata_when_inner_is_not_a_dict(self):
        meta = FeishuCardHandler._extract_meta(
            _event(metadata={"metadata": "oops", "message_type": "flat"}),
        )

        assert meta == {"metadata": "oops", "message_type": "flat"}

    def test_returns_empty_dict_without_metadata(self):
        # ``getattr(event, "metadata", None) or {}`` normalises a missing
        # attribute to an empty dict, so callers always get a mapping.
        assert FeishuCardHandler._extract_meta(_event()) == {}

    def test_returns_empty_dict_for_empty_metadata(self):
        assert FeishuCardHandler._extract_meta(_event(metadata={})) == {}

    def test_returns_none_for_non_dict_metadata(self):
        assert FeishuCardHandler._extract_meta(_event(metadata=[1, 2])) is None

    def test_returns_empty_dict_for_none_metadata(self):
        # ``None or {}`` also normalises to an empty dict.
        assert FeishuCardHandler._extract_meta(_event(metadata=None)) == {}


class TestExtractBodyText:
    def test_empty_content(self):
        assert FeishuCardHandler._extract_body_text(None) == ""
        assert FeishuCardHandler._extract_body_text("") == ""
        assert FeishuCardHandler._extract_body_text([]) == ""

    def test_plain_string_content(self):
        assert FeishuCardHandler._extract_body_text("hello") == "hello"

    def test_non_list_non_string_content(self):
        assert FeishuCardHandler._extract_body_text(12345) == ""
        assert FeishuCardHandler._extract_body_text({"a": 1}) == ""

    def test_objects_with_text_attribute(self):
        content = [
            SimpleNamespace(text="first "),
            SimpleNamespace(text="second"),
        ]

        assert FeishuCardHandler._extract_body_text(content) == (
            "first second"
        )

    def test_text_dicts(self):
        content = [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]

        assert FeishuCardHandler._extract_body_text(content) == "ab"

    def test_dict_without_text_type_is_skipped(self):
        content = [{"type": "image", "text": "ignored"}]

        assert FeishuCardHandler._extract_body_text(content) == ""

    def test_text_dict_missing_text_key(self):
        content = [{"type": "text"}]

        assert FeishuCardHandler._extract_body_text(content) == ""

    def test_mixed_content(self):
        content = [
            SimpleNamespace(text="obj "),
            {"type": "text", "text": "dict "},
            {"type": "image", "text": "skip"},
            SimpleNamespace(text=None),
            "bare-string-not-collected",
        ]

        assert FeishuCardHandler._extract_body_text(content) == "obj dict "

    def test_object_with_empty_text_is_skipped(self):
        content = [SimpleNamespace(text=""), SimpleNamespace(text="kept")]

        assert FeishuCardHandler._extract_body_text(content) == "kept"

    def test_object_without_text_attribute_is_skipped(self):
        content = [SimpleNamespace(other=1), SimpleNamespace(text="kept")]

        assert FeishuCardHandler._extract_body_text(content) == "kept"
