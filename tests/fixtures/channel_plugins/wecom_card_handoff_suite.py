"""Private callback/keepalive/update effects; no Host authority claim."""

import pytest

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import ingress, prepare, send  # noqa: E402
from wecom_card_effect_closeout_suite import approval  # noqa: E402

pytest_plugins = ["wecom_native_support"]


@pytest.mark.parametrize(
    "frame", [{"body": {"event": {"eventtype": "enter_chat"}}}, "bad", {}]
)
async def test_original_invalid_callbacks_have_no_effect(wecom_native, frame):
    driver, peer, identity, server = wecom_native
    before = list(peer.batches)
    assert await driver._platform._handle_card(frame) is False
    assert peer.batches == before
    assert server.rows("aibot_respond_update_msg") == []
    assert server.rows("aibot_respond_msg") == []


async def test_approval_handoff_cancels_owned_keepalive_and_reuses_sid(
    wecom_native,
):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    handle = event["response_handle"]
    assert (await prepare(wecom_native, handle))["state"] == "acknowledged"
    platform = driver._platform
    sid = platform._processing[handle]["stream_id"]
    owner = platform._keepalive_tasks[sid]
    assert not owner.done()
    result = await send(
        wecom_native,
        handle,
        content_parts=[{"type": "text", "text": "body"}],
        approval=approval(),
    )
    assert result["state"] == "acknowledged"
    assert owner.cancelled()
    assert sid not in platform._keepalive_tasks
    rows = server.rows("aibot_respond_msg")
    assert len(rows) == 3
    assert rows[0]["body"]["stream"] == {
        "id": sid,
        "content": "🤔 Thinking...",
        "finish": False,
    }
    assert rows[1]["body"]["stream"] == {
        "id": sid,
        "content": "body",
        "finish": True,
    }
    assert rows[2]["body"]["template_card"]["task_id"] == "tg_approval_rid-1"
    assert platform._processing[handle]["final"] is True


async def test_update_unknown_preserves_prior_command_and_never_replays(
    wecom_native, monkeypatch
):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    assert (
        await send(
            wecom_native,
            event["response_handle"],
            content_parts=[{"type": "text", "text": ""}],
            approval=approval("rid-12345678"),
        )
    )["state"] == "acknowledged"
    card = server.rows("aibot_respond_msg")[-1]["body"]["template_card"]
    callback = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "update-error"},
        "body": {
            "msgtype": "event",
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {
                    "event_key": card["button_list"][0]["key"],
                    "task_id": card["task_id"],
                },
            },
            "from": {"userid": "sender-A"},
            "chatid": "chat-A",
            "chattype": "single",
        },
    }
    click = await ingress(wecom_native, callback)
    assert click["content_parts"] == [
        {"type": "text", "text": "/approval approve rid-12345678"}
    ]
    assert server.rows("aibot_respond_update_msg") == []
    admitted = len(peer.batches)
    calls = []

    async def sdk_error(frame, card):
        calls.append((frame, card))
        raise RuntimeError("update failed")

    monkeypatch.setattr(
        driver._platform._client, "update_template_card", sdk_error
    )
    fields = {
        "delivery": "failed-update",
        "content_parts": [],
        "approval_resolution": {
            "request_id": "rid-12345678",
            "outcome": "approved",
            "actor_user_id": "sender-A",
            "tool_name": "shell",
        },
    }
    first = await send(wecom_native, click["response_handle"], **fields)
    assert first == {
        "delivery_id": "failed-update",
        "state": "unknown",
        "reason_code": "PLATFORM_RESULT_UNKNOWN",
        "retryable": False,
    }
    assert len(peer.batches) == admitted
    assert len(calls) == 1
    assert calls[0][0]["headers"]["req_id"] == "update-error"
    assert calls[0][1]["main_title"]["title"] == "✅ Approved"
    assert server.rows("aibot_respond_update_msg") == []
    assert (
        await send(wecom_native, click["response_handle"], **fields) == first
    )
    assert len(calls) == 1
    assert server.rows("aibot_respond_update_msg") == []
