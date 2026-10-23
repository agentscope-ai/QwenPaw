"""Remaining closed card guards and original callback chat-type matrix."""

import json

import pytest

from qwenpaw.channel_protocol.errors import ProtocolValidationError

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import ingress, send, text_frame  # noqa: E402
from wecom_card_effect_closeout_suite import approval  # noqa: E402

pytest_plugins = ["wecom_native_support"]


async def test_card_missing_request_or_callback_frame_has_zero_effect(
    wecom_native,
):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    with pytest.raises(ProtocolValidationError):
        await send(
            wecom_native,
            event["response_handle"],
            content_parts=[{"type": "text", "text": "guard details"}],
            approval={"tool_name": "shell", "severity": "high"},
        )
    assert server.rows("aibot_respond_msg") == []
    opened = await peer.methods["channel.response.open"](
        {
            **identity,
            "to_handle": "wecom:user_123",
            "meta": {"wecom_chatid": "chat_456"},
        },
        None,
    )
    result = await send(
        wecom_native,
        opened["response_handle"],
        delivery="no-callback-card",
        content_parts=[{"type": "text", "text": "guard details"}],
        approval=approval(),
    )
    assert result == {
        "delivery_id": "no-callback-card",
        "state": "failed",
        "reason_code": "APPROVAL_TARGET_UNSUPPORTED",
        "retryable": False,
    }
    assert server.rows("aibot_respond_msg") == []
    assert server.rows("aibot_send_msg") == []
    assert driver._platform._cards == driver._platform._staged_cards == {}


@pytest.mark.parametrize(
    ("chat_type", "is_group"),
    [("group", True), ("single", False), ("", False)],
)
async def test_bound_callback_chat_type_and_missing_tool_defaults(
    wecom_native, chat_type, is_group
):
    driver, peer, identity, server = wecom_native
    native = text_frame(group=is_group)
    native["body"]["chattype"] = chat_type
    event = await ingress(wecom_native, native)
    assert (
        await send(
            wecom_native,
            event["response_handle"],
            content_parts=[{"type": "text", "text": "guard details"}],
            approval=approval("rid-12345678", "tool"),
        )
    )["state"] == "acknowledged"
    card = server.rows("aibot_respond_msg")[-1]["body"]["template_card"]
    key = json.loads(card["button_list"][0]["key"])
    assert key["tool"] == "tool"
    del key["tool"]
    actor = "actual-clicker" if is_group else "sender-A"
    callback = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "final-edge-click"},
        "body": {
            "msgtype": "event",
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {
                    "event_key": json.dumps(key),
                    "task_id": card["task_id"],
                },
            },
            "from": {"userid": actor},
            "chatid": native["body"]["chatid"],
            "chattype": chat_type,
        },
    }
    click = await ingress(wecom_native, callback)
    assert click["sender_id"] == click["acl_sender_id"] == actor
    assert click["metadata"]["is_group"] is is_group
    assert click["metadata"]["wecom_chat_type"] == (chat_type or "single")
    assert click["metadata"]["session_id"] == event["metadata"]["session_id"]
    assert click["content_parts"] == [
        {"type": "text", "text": "/approval approve rid-12345678"}
    ]
    assert server.rows("aibot_respond_update_msg") == []
    assert (
        await send(
            wecom_native,
            click["response_handle"],
            delivery="final-edge-resolved",
            content_parts=[],
            approval_resolution={
                "request_id": "rid-12345678",
                "outcome": "approved",
                "actor_user_id": actor,
                "tool_name": "tool",
            },
        )
    )["state"] == "acknowledged"
    updates = server.rows("aibot_respond_update_msg")
    assert len(updates) == 1
    assert updates[0]["headers"]["req_id"] == "final-edge-click"
    assert (
        updates[0]["body"]["template_card"]["main_title"]["title"]
        == "✅ Approved"
    )
    assert "tool" in updates[0]["body"]["template_card"]["main_title"]["desc"]
