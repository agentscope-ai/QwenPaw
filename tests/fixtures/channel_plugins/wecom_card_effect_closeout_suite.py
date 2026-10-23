"""Actual private Driver/SDK card effects; external SDK error boundary only."""

import pytest

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import ingress, send, text_frame  # noqa: E402

pytest_plugins = ["wecom_native_support"]


def approval(request_id="rid-1", tool_name="shell"):
    return {
        "request_id": request_id,
        "tool_name": tool_name,
        "severity": "high",
    }


async def test_original_detail_precedes_card_exact_effects(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    result = await send(
        wecom_native,
        event["response_handle"],
        content_parts=[{"type": "text", "text": "guard details"}],
        approval=approval(),
    )
    assert result["state"] == "acknowledged"
    rows = server.rows("aibot_respond_msg")
    assert len(rows) == 2
    assert [r["body"]["msgtype"] for r in rows] == [
        "stream",
        "template_card",
    ]
    assert rows[0]["body"]["stream"]["content"] == "guard details"
    assert rows[0]["body"]["stream"]["finish"] is True
    card = rows[1]["body"]["template_card"]
    assert card["task_id"] == "tg_approval_rid-1"
    assert card["main_title"]["desc"] == "shell | high"
    assert [r["headers"]["req_id"] for r in rows] == [
        "cb-native-msg",
        "cb-native-msg",
    ]
    assert driver._platform._staged_cards == {}
    assert len(driver._platform._cards) == 1


async def test_original_oversized_key_has_only_text_fallback(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    result = await send(
        wecom_native,
        event["response_handle"],
        content_parts=[{"type": "text", "text": "please approve"}],
        approval=approval(tool_name="x" * 2000),
    )
    assert result["state"] == "acknowledged"
    rows = server.rows("aibot_respond_msg")
    assert len(rows) == 1
    assert rows[0]["body"]["msgtype"] == "stream"
    assert rows[0]["body"]["stream"]["content"] == "please approve"
    assert rows[0]["body"]["stream"]["finish"] is True
    assert driver._platform._cards == driver._platform._staged_cards == {}
    # Old card renderer returned False before any native effect; its caller
    # performed ordinary text fallback. This checks that complete operation:
    # exactly one fallback, no extra detail stream or native card.


@pytest.mark.parametrize(
    "failure",
    ["known_detail_rejection", "unknown_detail", "unknown_card"],
)
async def test_composite_card_failure_keeps_precise_effect_and_no_replay(
    wecom_native, monkeypatch, failure
):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    calls = []
    target = (
        "reply_template_card" if failure == "unknown_card" else "reply_stream"
    )

    async def sdk_failure(*args, **kwargs):
        calls.append((args, kwargs))
        if failure == "known_detail_rejection":
            raise RuntimeError("Reply ack error: errcode=400, detail rejected")
        raise RuntimeError(
            "api down" if failure == "unknown_card" else "stream down"
        )

    monkeypatch.setattr(driver._platform._client, target, sdk_failure)
    fields = {
        "content_parts": [{"type": "text", "text": "please approve"}],
        "approval": approval(),
    }
    first = await send(wecom_native, event["response_handle"], **fields)
    rows = server.rows("aibot_respond_msg")
    if failure == "known_detail_rejection":
        assert first["state"] == "acknowledged"
        assert len(rows) == 1
        assert rows[0]["body"]["msgtype"] == "template_card"
        assert len(driver._platform._cards) == 1
    else:
        assert first == {
            "delivery_id": "delivery-A",
            "state": "unknown",
            "reason_code": "PLATFORM_RESULT_UNKNOWN",
            "retryable": False,
        }
        if failure == "unknown_card":
            assert len(rows) == 1
            assert rows[0]["body"]["stream"]["content"] == "please approve"
            assert rows[0]["body"]["stream"]["finish"] is True
        else:
            assert rows == []
        assert driver._platform._cards == {}
    assert len(calls) == 1
    second = await send(wecom_native, event["response_handle"], **fields)
    assert second == first
    assert len(calls) == 1
    assert server.rows("aibot_respond_msg") == rows
    assert driver._platform._staged_cards == {}


async def test_deny_click_then_typed_outcome_exact_frame_and_command(
    wecom_native,
):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native, text_frame(group=True))
    result = await send(
        wecom_native,
        event["response_handle"],
        content_parts=[{"type": "text", "text": "please approve"}],
        approval=approval("rid-12345678"),
    )
    assert result["state"] == "acknowledged"
    card = server.rows("aibot_respond_msg")[-1]["body"]["template_card"]
    callback = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "deny-click"},
        "body": {
            "msgtype": "event",
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {
                    "event_key": card["button_list"][1]["key"],
                    "task_id": card["task_id"],
                },
            },
            "from": {"userid": "user-abc"},
            "chatid": "group-A",
            "chattype": "group",
        },
    }
    click = await ingress(wecom_native, callback)
    assert click["content_parts"] == [
        {"type": "text", "text": "/approval deny rid-12345678"}
    ]
    assert click["acl_sender_id"] == click["sender_id"] == "user-abc"
    assert click["metadata"]["session_id"] == "wecom:group:group-A"
    assert server.rows("aibot_respond_update_msg") == []
    resolution = {
        "request_id": "rid-12345678",
        "outcome": "denied",
        "actor_user_id": "user-abc",
        "tool_name": "shell",
    }
    result = await send(
        wecom_native,
        click["response_handle"],
        delivery="deny-resolution",
        content_parts=[],
        approval_resolution=resolution,
    )
    assert result["state"] == "acknowledged"
    updates = server.rows("aibot_respond_update_msg")
    assert len(updates) == 1
    assert updates[0]["headers"]["req_id"] == "deny-click"
    resolved = updates[0]["body"]["template_card"]
    assert resolved["task_id"] == "tg_approval_rid-12345678"
    assert resolved["main_title"]["title"] == "🚫 Denied"
    assert "user-abc" in resolved["main_title"]["desc"]
    assert "shell" in resolved["main_title"]["desc"]
