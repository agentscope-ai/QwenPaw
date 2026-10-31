# -*- coding: utf-8 -*-
"""DingTalk native callbacks, sends, cards and SDK cleanup."""
import asyncio
import hashlib
import json
from types import SimpleNamespace as NS
import aiohttp
import pytest
import pytest_asyncio
from dingtalk_stream import CallbackMessage
from qwenpaw.channel_protocol.models import ResponseFinishParams, SendParams
from qwenpaw.channel_protocol.response_receipts import receipt_key
from tests.channel_support.driver import bind, module

pytestmark = pytest.mark.asyncio
WEBHOOK = "https://webhook.test/send?session=original"


class Socket:
    closed = False

    async def close(self):
        self.closed = True

    async def ping(self):
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        return done


class Stream:
    def __init__(self, *args):
        self.websocket, self.connection_error = None, None
        self.callback_handler_map = {}

    def register_callback_handler(self, topic, handler):
        self.callback_handler_map[topic] = handler

    async def start(self):
        self.websocket = Socket()
        await asyncio.Event().wait()


class Reply:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def text(self):
        return json.dumps({"errcode": 0})

    async def json(self, **kwargs):
        return {"errcode": 0}

    def release(self):
        pass

    async def wait_for_close(self):
        pass


@pytest_asyncio.fixture
async def native(tmp_path, monkeypatch, request):
    sdk = module("dingtalk", "sdk")
    rows = []
    monkeypatch.setattr(sdk, "StreamClient", Stream)

    async def token(self, request):
        rows.append(("token", request.to_map()))
        return sdk.dingtalk_oauth_models.GetAccessTokenResponse(
            body=sdk.dingtalk_oauth_models.GetAccessTokenResponseBody(
                access_token="api-token",
                expire_in=7200,
            ),
        )

    monkeypatch.setattr(
        sdk.dingtalk_oauth_client.Client,
        "get_access_token_async",
        token,
    )

    def endpoint(kind):
        async def call(self, request, headers, options):
            rows.append((kind, request.to_map()))
            if kind == "deliver":
                return sdk.dingtalk_card_models.DeliverCardResponse(
                    body=sdk.dingtalk_card_models.DeliverCardResponseBody(),
                )

        return call

    for cls, method, kind in [
        (
            sdk.dingtalk_robot_client.Client,
            "org_group_send_with_options_async",
            "group",
        ),
        (
            sdk.dingtalk_robot_client.Client,
            "batch_send_otowith_options_async",
            "dm",
        ),
        (
            sdk.dingtalk_robot_client.Client,
            "robot_reply_emotion_with_options_async",
            "emotion",
        ),
        (
            sdk.dingtalk_robot_client.Client,
            "robot_recall_emotion_with_options_async",
            "recall",
        ),
        (
            sdk.dingtalk_card_client.Client,
            "create_card_with_options_async",
            "create",
        ),
        (
            sdk.dingtalk_card_client.Client,
            "deliver_card_with_options_async",
            "deliver",
        ),
        (
            sdk.dingtalk_card_client.Client,
            "streaming_update_with_options_async",
            "update",
        ),
    ]:
        monkeypatch.setattr(cls, method, endpoint(kind))

    async def network_request(self, method, url, **kwargs):
        rows.append(("webhook", {"url": str(url), "body": kwargs.get("json")}))
        return Reply()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", network_request)
    driver = module("dingtalk").DingTalkDriver()
    peer, identity = bind("dingtalk", driver, tmp_path)
    await driver.start(
        {
            "enabled": True,
            "client_id": "client-one",
            "client_secret": "secret",
            "workspace_dir": str(tmp_path),
            "require_mention": True,
            "message_type": getattr(request, "param", "markdown"),
            "card_template_id": "template",
            "streaming_enabled": True,
        },
    )
    async with asyncio.timeout(2):
        while not driver._connected:
            await asyncio.sleep(0.005)
    try:
        yield NS(
            driver=driver,
            peer=peer,
            identity=identity.to_mapping(),
            rows=rows,
        )
    finally:
        await driver.stop()


def message(mid, *, group=False, mentioned=True, content=None, **fields):
    body = {
        "msgId": mid,
        "msgtype": "text",
        "text": {"content": "hello"},
        "senderId": "ding1234",
        "senderNick": "Alice",
        "senderStaffId": "staff-one",
        "conversationId": "cid-original",
        "conversationType": "2" if group else "1",
        "sessionWebhook": WEBHOOK,
        "sessionWebhookExpiredTime": 9999999999999,
        "isInAtList": mentioned,
        "robotCode": "client-one",
        "chatbotUserId": "robot-user",
        **fields,
    }
    if content is not None:
        body.update(content)
    return {
        "specVersion": "1.0",
        "type": "CALLBACK",
        "headers": {
            "appId": "client-one",
            "messageId": mid,
            "time": "1700000000000",
            "topic": "/v1.0/im/bot/messages/get",
            "contentType": "application/json",
        },
        "data": json.dumps(body),
    }


async def ingress(rt, value):
    callback = CallbackMessage.from_dict(value)
    handler = next(
        iter(rt.driver._platform._client.callback_handler_map.values()),
    )
    status, _ = await handler.process(callback)
    assert status == 200
    return rt.peer.batches[-1]["events"][0] if rt.peer.batches else None


async def send(rt, handle, text="answer", **fields):
    params = SendParams.from_mapping(
        {
            **rt.identity,
            "to_handle": handle,
            "delivery_id": "delivery",
            "operation": "message.create",
            **(
                {"content_parts": [{"type": "text", "text": text}]}
                if not fields.get("operation", "").startswith("stream.")
                else {}
            ),
            **fields,
        },
    )
    return await rt.peer.methods["channel.send"](params, None)


@pytest.mark.parametrize("group", [False, True])
async def test_dm_and_group_mention_parse_and_reply_webhook(native, group):
    rt = native
    if group:
        await ingress(rt, message("ignored", group=True, mentioned=False))
        assert not rt.peer.batches
    event = await ingress(rt, message("accepted", group=group))
    assert event["acl_sender_id"] == "ding1234"
    assert event["conversation"]["type"] == ("group" if group else "dm")
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert (await send(rt, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    assert (await send(rt, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    conflict = await send(rt, event["response_handle"], "changed")
    assert conflict["reason_code"] == "DELIVERY_CONFLICT"
    assert len([row for kind, row in rt.rows if kind == "webhook"]) == 1
    row = next(row for kind, row in rt.rows if kind == "webhook")
    assert row["url"] == WEBHOOK
    assert "answer" in json.dumps(row["body"])


@pytest.mark.parametrize("group", [False, True])
async def test_proactive_openapi_preserves_recipient(native, group):
    rt = native
    opened = await rt.peer.methods["channel.response.open"](
        {
            **rt.identity,
            "to_handle": "dingtalk:sw:missing",
            "meta": {
                "conversation_id": "cid-target",
                "sender_staff_id": "staff-one",
                "is_group": group,
                "conversation_type": "group" if group else "dm",
            },
        },
        None,
    )
    assert (await send(rt, opened["response_handle"]))[
        "state"
    ] == "acknowledged"
    request = next(
        row for kind, row in rt.rows if kind == ("group" if group else "dm")
    )
    assert request["robotCode"] == "client-one"
    assert json.loads(request["msgParam"])["text"].strip() == "answer"
    assert (
        request["openConversationId"] == "cid-target"
        if group
        else request["userIds"] == ["staff-one"]
    )


@pytest.mark.parametrize("native", ["card"], indirect=True)
async def test_stream_card_final_reply_uses_original_card(native):
    rt = native
    event = await ingress(rt, message("stream", group=True))
    handle = event["response_handle"]
    prepare = {
        **rt.identity,
        "response_handle": handle,
        "delivery_id": hashlib.sha256(
            (handle + ":prepare").encode(),
        ).hexdigest(),
    }
    for _ in range(2):
        assert (
            await rt.peer.methods["channel.response.prepare"](prepare, None)
        )["state"] == "acknowledged"
    assert len([row for kind, row in rt.rows if kind == "create"]) == 1
    assert (
        await send(
            rt,
            handle,
            operation="stream.start",
            stream_type="message",
            sequence=0,
            accumulated_text="first",
        )
    )["state"] == "acknowledged"
    params = SendParams.from_mapping(
        {
            **rt.identity,
            "to_handle": handle,
            "delivery_id": "end",
            "target_delivery_id": "delivery",
            "operation": "stream.end",
            "stream_type": "message",
            "sequence": 1,
            "accumulated_text": "final answer",
        },
    )
    assert (await rt.peer.methods["channel.send"](params, None))[
        "state"
    ] == "acknowledged"
    created = next(row for kind, row in rt.rows if kind == "create")
    updates = [row for kind, row in rt.rows if kind == "update"]
    assert updates[-1]["outTrackId"] == created["outTrackId"]
    assert (
        updates[-1]["content"] == "final answer" and updates[-1]["isFinalize"]
    )
    assert len([row for kind, row in rt.rows if kind == "deliver"]) == 1


async def test_failed_feedback_archives_current_receipt_and_replays(
    native,
    monkeypatch,
):
    rt = native
    calls = []

    async def fail_emotion(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("emotion result lost")

    monkeypatch.setattr(rt.driver._platform, "_send_emotion", fail_emotion)
    event = await ingress(rt, message("feedback"))
    handle = event["response_handle"]
    prepare = {
        **rt.identity,
        "response_handle": handle,
        "delivery_id": hashlib.sha256(
            (handle + ":prepare").encode(),
        ).hexdigest(),
    }
    assert (await rt.peer.methods["channel.response.prepare"](prepare, None))[
        "state"
    ] == "acknowledged"
    assert (await send(rt, handle))["state"] == "acknowledged"
    finish = ResponseFinishParams.from_mapping(
        {**rt.identity, "response_handle": handle, "outcome": "completed"},
    )
    await rt.peer.methods["channel.response.finish"](finish, None)
    stored = rt.peer.receipts.get(receipt_key(rt.driver._state_key, handle))
    assert stored is not None
    archived = await rt.driver._archived(handle)
    assert archived.to_mapping() == stored
    assert rt.driver._routes.snapshot(handle) is None
    assert len(archived.resource_refs) == 3
    for ref in archived.resource_refs:
        attrs = dict(ref.attributes)
        assert attrs["state"] == "unknown"
        assert (
            attrs["fingerprint"]
            == hashlib.sha256(
                ("dingtalk.feedback:" + ref.resource_id).encode(),
            ).hexdigest()
        )
    assert len(calls) == 3
    restored = await rt.driver._feedback(
        archived,
        {"message_id": "feedback", "conversation_id": "cid-original"},
        "🤔Thinking",
    )
    assert restored == archived
    assert len(calls) == 3
    assert len([row for kind, row in rt.rows if kind == "webhook"]) == 1


async def test_legal_approval_command_uses_authenticated_native_sender(native):
    event = await ingress(
        native,
        message(
            "approval",
            group=True,
            text={"content": "/approval approve rid-A"},
        ),
    )
    assert event["acl_sender_id"] == "ding1234"
    assert event["content_parts"] == [
        {"type": "text", "text": "/approval approve rid-A"},
    ]
    assert event["metadata"]["sender_staff_id"] == "staff-one"


async def test_stop_joins_sdk_thread_and_closes_http(native):
    platform = native.driver._platform
    thread, client = platform._stream_thread, platform._http
    await native.driver.stop()
    assert not thread.is_alive() and client.closed
    assert native.driver._platform is None
