# -*- coding: utf-8 -*-
"""DingTalk native callbacks, sends, cards and SDK cleanup."""
import asyncio
import hashlib
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import aiohttp
import pytest
import pytest_asyncio
from dingtalk_stream import CallbackMessage
from qwenpaw.app.channels.utils import split_text
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


@pytest.mark.parametrize("native", ["card"], indirect=True)
async def test_stream_card_separates_table_from_paragraph(native):
    """Card content gets a blank line before a table so DingTalk renders it."""
    rt = native
    event = await ingress(rt, message("table", group=True))
    handle = event["response_handle"]
    text = "Details:\n| k | v |\n|---|---|\n| a | 1 |"
    expected = "Details:\n\n| k | v |\n|---|---|\n| a | 1 |"
    assert (
        await send(
            rt,
            handle,
            operation="stream.start",
            stream_type="message",
            sequence=0,
            accumulated_text=text,
        )
    )["state"] == "acknowledged"
    update_count = sum(kind == "update" for kind, _ in rt.rows)
    assert (
        await send(
            rt,
            handle,
            delivery_id="same-content",
            target_delivery_id="delivery",
            operation="stream.delta",
            stream_type="message",
            sequence=1,
            accumulated_text=text,
        )
    )["state"] == "acknowledged"
    assert sum(kind == "update" for kind, _ in rt.rows) == update_count
    params = SendParams.from_mapping(
        {
            **rt.identity,
            "to_handle": handle,
            "delivery_id": "end",
            "target_delivery_id": "delivery",
            "operation": "stream.end",
            "stream_type": "message",
            "sequence": 2,
            "accumulated_text": text,
        },
    )
    assert (await rt.peer.methods["channel.send"](params, None))[
        "state"
    ] == "acknowledged"
    updates = [row for kind, row in rt.rows if kind == "update"]
    assert updates and all(row["content"] == expected for row in updates)
    assert updates[-1]["isFinalize"]


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


def _long_pipe_table(rows: int = 200) -> str:
    """GFM pipe table longer than DingTalk's markdown-safe budget."""
    header = "| metric | value |"
    separator = "| --- | --- |"
    row = "| latency | 12345 |"
    return "\n".join([header, separator, *([row] * rows)])


def _expected_markdown_chunks(text: str) -> list[str]:
    """Normalized chunks a >3500-char body should be sent as."""
    normalize = module(
        "dingtalk",
        "markdown",
    ).normalize_dingtalk_markdown
    return [normalize(chunk) for chunk in split_text(text, max_len=3000)]


async def test_markdown_chunks_keeps_short_and_splits_long_table():
    """Short bodies stay one piece; long tables split with a header."""
    transport = module("dingtalk", "transport")
    assert transport._markdown_chunks("hello") == ["hello"]
    table = _long_pipe_table()
    assert len(table) > transport._MARKDOWN_SAFE_LEN
    chunks = transport._markdown_chunks(table)
    assert chunks == split_text(table, max_len=transport._MARKDOWN_CHUNK_LEN)
    assert len(chunks) >= 2
    assert all("| --- |" in chunk for chunk in chunks)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Details:\n| k | v |\n|---|---|\n| a | 1 |",
            "Details:\n\n| k | v |\n|---|---|\n| a | 1 |",
        ),
        ("x\nk | v\n:-- | --:", "x\n\nk | v\n:-- | --:"),
        ("x\n| k |\n|---|", "x\n\n| k |\n|---|"),
        ("x\n\n| k | v |\n|---|---|", "x\n\n| k | v |\n|---|---|"),
        ("| k | v |\n|---|---|", "| k | v |\n|---|---|"),
        (
            "```\nx\n| k | v |\n|---|---|\n```",
            "```\nx\n| k | v |\n|---|---|\n```",
        ),
        ("title\n---\nbody", "title\n---\nbody"),
        ("a | b\n---", "a | b\n---"),
        (
            "| Note: results below\n| k | v |\n|---|---|",
            "| Note: results below\n\n| k | v |\n|---|---|",
        ),
        (
            "note\n    | k | v |\n    |---|---|",
            "note\n    | k | v |\n    |---|---|",
        ),
        ("note\n\t| k | v |\n\t|---|---|", "note\n\t| k | v |\n\t|---|---|"),
    ],
)
async def test_ensure_table_spacing(text, expected):
    """Only a table that directly follows a paragraph line is separated."""
    markdown = module("dingtalk", "markdown")
    assert markdown.ensure_table_spacing(text) == expected
    assert markdown.ensure_table_spacing(expected) == expected


@pytest.mark.parametrize(
    ("opening", "inner", "closing"),
    [
        ("````markdown", "```", "````"),
        ("```markdown", "~~~", "```"),
        ("~~~markdown", "```", "~~~"),
        ("~~~~markdown", "~~~", "~~~~"),
        ("```markdown", "```not a closing fence", "```"),
        ("```markdown", "  ```not a closing fence", "```"),
    ],
)
async def test_table_spacing_preserves_fences(opening, inner, closing):
    markdown = module("dingtalk", "markdown")
    table = "Details:\n| k | v |\n|---|---|"
    code = f"{opening}\n{inner}\n{table}\n{closing}"
    assert markdown.ensure_table_spacing(code) == code
    assert markdown.ensure_table_spacing(f"{code}\n{table}") == (
        f"{code}\nDetails:\n\n| k | v |\n|---|---|"
    )


@pytest.mark.parametrize("native", ["card"], indirect=True)
async def test_stream_card_preserves_non_table_code(native):
    platform = native.driver._platform
    event = await ingress(native, message("code", group=True))
    text = "```text\nx\n1. literal\n```"
    assert (
        await send(
            native,
            event["response_handle"],
            operation="stream.start",
            stream_type="message",
            sequence=0,
            accumulated_text=text,
        )
    )["state"] == "acknowledged"
    updates = [row for kind, row in native.rows if kind == "update"]
    assert updates[-1]["content"] == text
    assert any(
        card.last_streamed_content == text
        for card in platform._active_cards.values()
    )


async def test_long_markdown_table_splits_on_session_webhook(native):
    """A >3500-char pipe table is sent as several markdown messages.

    @mention / ``at`` stays on the first chunk. No chunk uses
    ``msgtype=text``.
    """
    platform = native.driver._platform
    body = _long_pipe_table()
    bot_prefix = "[Bot]"
    at_user_ids = ["staff1"]
    composed = f"@{at_user_ids[0]}\n{bot_prefix}  {body}"
    expected = _expected_markdown_chunks(composed)
    assert len(composed) > 3500
    assert len(expected) >= 2
    assert sum(chunk.count("| --- |") for chunk in expected) >= 2

    webhook = "https://oapi.dingtalk.com/robot/send?session=abc"
    send_payload = AsyncMock(return_value=True)
    platform._send_payload_via_session_webhook = send_payload

    result = await platform._send_via_session_webhook(
        session_webhook=webhook,
        body=body,
        bot_prefix=bot_prefix,
        at_user_ids=at_user_ids,
    )

    assert result is True
    calls = send_payload.await_args_list
    assert len(calls) == len(expected)
    for index, (call, norm) in enumerate(zip(calls, expected)):
        assert call.args[0] == webhook
        payload = call.args[1]
        assert payload["msgtype"] == "markdown"
        assert "text" not in payload
        assert payload["markdown"]["text"] == norm
        title = payload["markdown"]["title"]
        assert title == f"💬{norm[:10]}..."
        assert len(norm) <= 3500
        if index == 0:
            assert payload["at"] == {"atUserIds": at_user_ids}
            assert norm.startswith("@staff1")
        else:
            assert "at" not in payload
    sent_text = [call.args[1]["markdown"]["text"] for call in calls]
    assert any("[Bot]" in text for text in sent_text)
    table_chunks = [text for text in sent_text if "| --- |" in text]
    assert len(table_chunks) >= 2


async def test_long_markdown_table_splits_on_open_api(native):
    """Open API sends the same long table as sampleMarkdown chunks."""
    platform = native.driver._platform
    body = _long_pipe_table()
    bot_prefix = "[Bot]"
    composed = f"{bot_prefix}  {body}"
    expected = _expected_markdown_chunks(composed)
    assert len(composed) > 3500
    assert len(expected) >= 2

    send_robot = AsyncMock(return_value=True)
    platform._send_robot_message = send_robot

    result = await platform._send_via_open_api(
        body=body,
        conversation_id="cid_group_123",
        conversation_type="group",
        sender_staff_id="",
        bot_prefix=bot_prefix,
    )

    assert result is True
    assert send_robot.await_count == len(expected)
    for call, norm in zip(send_robot.await_args_list, expected):
        assert call.kwargs["msg_key"] == "sampleMarkdown"
        param = json.loads(call.kwargs["msg_param"])
        assert "content" not in param
        assert param["text"] == norm
        assert param["title"] == f"💬{norm[:10]}..."
        assert "| --- |" in param["text"]
        assert len(param["text"]) <= 3500
        assert call.kwargs["conversation_id"] == "cid_group_123"
        assert call.kwargs["is_group"] is True


async def test_long_markdown_fails_when_a_later_chunk_fails(native):
    """Success is returned only when every markdown chunk is sent."""
    platform = native.driver._platform
    body = "y" * 9000
    send_payload = AsyncMock(side_effect=[True, False, True])
    platform._send_payload_via_session_webhook = send_payload

    result = await platform._send_via_session_webhook(
        session_webhook="https://oapi.dingtalk.com/robot/send?session=abc",
        body=body,
        bot_prefix="",
    )

    assert result is False
    assert send_payload.await_count == 2
    for call in send_payload.await_args_list:
        payload = call.args[1]
        assert payload["msgtype"] == "markdown"
        assert "text" not in payload
