# -*- coding: utf-8 -*-
"""Slack native callbacks and sends through an SDK boundary."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import eventually, send


class WebClient:
    def __init__(self, **kwargs):
        self.calls, self.session = [], None

    async def auth_test(self):
        return {"user_id": "UBOT"}

    async def users_info(self, **kwargs):
        return {"user": {"profile": {"display_name": "Human"}}}

    async def conversations_replies(self, **kwargs):
        return {
            "messages": [
                {
                    "user": "U1",
                    "text": "earlier question",
                    "ts": "1000000000.000001",
                },
            ],
        }

    async def chat_postMessage(self, **kwargs):
        self.calls.append(("post", kwargs))
        return {"ok": True, "ts": str(len(self.calls)) + ".0"}

    async def chat_update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return {"ok": True, "ts": kwargs["ts"]}


class App:
    def __init__(self, **kwargs):
        self.handlers = {}

    def event(self, name):
        def register(callback):
            self.handlers[name] = callback
            return callback

        return register

    def command(self, expression):
        return lambda callback: callback


class Socket:
    def __init__(self, *args, **kwargs):
        self.connected, self.closed = False, False
        self.client = NS(
            process_messages=self.idle,
            monitor_current_session=self.idle,
            receive_messages=self.idle,
            is_connected=self.is_connected,
        )

    async def idle(self):
        await asyncio.Event().wait()

    async def is_connected(self):
        return self.connected

    async def start_async(self):
        self.connected = True
        await asyncio.Event().wait()

    async def close_async(self):
        self.closed, self.connected = True, False


@pytest.fixture
async def slack(tmp_path, monkeypatch):
    native = module("slack", "platform")
    monkeypatch.setattr(native, "AsyncApp", App)
    monkeypatch.setattr(native, "AsyncWebClient", WebClient)
    monkeypatch.setattr(native, "AsyncSocketModeHandler", Socket)
    driver = module("slack").SlackDriver()
    peer, identity = bind("slack", driver, tmp_path)
    await driver.start(
        dict(
            bot_token="xoxb-test",
            app_token="xapp-test",
            workspace_dir=str(tmp_path),
            media_dir=str(tmp_path / "media"),
            streaming_enabled=True,
        ),
    )
    await eventually(lambda: driver._connected)
    yield driver, peer, identity, driver._platform
    await driver.stop()


async def receive(
    value,
    channel="D123",
    thread="",
    text="hello",
    ident="2.0",
    callback="message",
):
    _, peer, _, platform = value
    acks = []

    async def ack():
        acks.append(True)

    await platform._app.handlers[callback](
        {
            "channel": channel,
            "user": "U1",
            "ts": ident,
            "thread_ts": thread,
            "text": text,
        },
        platform._client,
        {},
        ack,
    )
    assert acks == [True]
    return peer.batches[-1]["events"][0] if peer.batches else None


@pytest.mark.parametrize(
    "channel,thread,text",
    [
        ("D123", "", "hello"),
        ("C123", "", "<@UBOT> hello"),
        ("C123", "1000000000.000001", "<@UBOT> hello"),
    ],
)
async def test_dm_group_and_thread_route_to_exact_slack_target(
    slack,
    channel,
    thread,
    text,
):
    _, peer, identity, platform = slack
    event = await receive(slack, channel, thread, text)
    assert event["conversation"] == {
        "id": channel,
        "type": "dm" if channel[0] == "D" else "group",
        "thread_id": thread or None,
    }
    assert event["sender_id"] == event["acl_sender_id"] == "U1"
    assert event["sender_name"] == "Human"
    assert "hello" in event["content_parts"][0]["text"]
    if thread:
        assert "earlier question" in event["content_parts"][0]["text"]
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    call = platform._client.calls[-1]
    assert call[0] == "post" and call[1]["channel"] == channel
    assert call[1].get("thread_ts") == (thread or None)
    assert call[1]["text"] == "native answer"


async def test_unmentioned_group_is_filtered_and_app_mention_is_admitted_once(
    slack,
):
    _, peer, _, _ = slack
    assert await receive(slack, "C123", text="hello") is None
    event = await receive(
        slack,
        "C123",
        text="<@UBOT> hello",
        callback="app_mention",
    )
    await receive(slack, "C123", text="<@UBOT> hello", callback="message")
    assert (
        len(peer.batches) == 1 and event["metadata"]["bot_mentioned"] is True
    )


async def test_stream_final_edits_native_placeholder_with_final_formatting(
    slack,
):
    _, peer, identity, platform = slack
    handle = (
        await receive(slack, "C123", "1000000000.000001", "<@UBOT> hello")
    )["response_handle"]
    assert (
        await send(
            peer,
            identity,
            handle,
            delivery="stream",
            operation="stream.start",
            stream_type="message",
        )
    )["state"] == "acknowledged"
    assert (
        await send(
            peer,
            identity,
            handle,
            delivery="end",
            operation="stream.end",
            stream_type="message",
            target_delivery_id="stream",
            sequence=1,
            accumulated_text="**complete** answer",
        )
    )["state"] == "acknowledged"
    assert platform._client.calls[0][1]["thread_ts"] == "1000000000.000001"
    assert platform._client.calls[-1] == (
        "update",
        {
            "channel": "C123",
            "ts": "1.0",
            "text": "*complete* answer",
            "mrkdwn": True,
        },
    )


async def test_stop_closes_socket_and_owned_connection_tasks(slack):
    driver, _, _, platform = slack
    handler, task, watch = (
        platform._handler,
        platform._socket_mode_task,
        platform._connection_task,
    )
    await driver.stop()
    assert handler.closed and not handler.connected
    assert task.done() and watch.done() and not platform._sdk_tasks
    assert driver._platform is None
    await driver.stop()


@pytest.mark.parametrize("unknown_at", ["end", "cleanup"])
async def test_unknown_stream_retires_to_durable_receipt(
    tmp_path,
    monkeypatch,
    unknown_at,
):
    import json
    import qwenpaw.channel_protocol.shared_response_driver as shared
    from tests.channel_support.protocol import finish, open_route
    from qwenpaw.plugins.execution.errors import RpcError

    monkeypatch.setattr(shared, "_MAX_ROUTES", 1)
    driver = module("slack").SlackDriver()
    error = module("slack", "utils").SlackDeliveryError
    updates = []

    class Platform:
        async def start_stream(self, route, kind):
            return {"ts": "1.0", "channel_id": "D123", "final": "false"}

        async def update_stream(self, resource, text, *, final):
            updates.append(dict(resource))
            raise error("UPDATE_UNKNOWN", side_effect_possible=True)

    peer, identity = bind("slack", driver, tmp_path)
    driver._platform = Platform()
    driver._connected = True
    driver._config = {"streaming_enabled": True}
    handle = await open_route(peer, identity, "D123")
    await send(
        peer,
        identity,
        handle,
        delivery="start",
        operation="stream.start",
        stream_type="message",
    )
    ending = dict(
        delivery="end",
        operation="stream.end",
        stream_type="message",
        target_delivery_id="start",
        sequence=1,
        accumulated_text="hello",
    )
    if unknown_at == "end":
        assert (await send(peer, identity, handle, **ending))[
            "state"
        ] == "unknown"

    def unavailable(*args):
        raise OSError("receipt storage unavailable")

    # Failure to archive must retain the live terminal checkpoint.
    monkeypatch.setattr(peer.receipts, "put", unavailable)
    with pytest.raises(RpcError) as failure:
        await finish(peer, identity, handle)
    assert failure.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    assert driver._routes.snapshots()
    assert not peer.receipts.list()
    stale = json.loads(json.dumps(peer.state))
    original = driver._routes.snapshot(handle)
    unknown_refs = {
        ref.resource_id: dict(ref.attributes)
        for ref in original.resource_refs
        if dict(ref.attributes).get("state") == "unknown"
    }
    assert len(updates) == 1
    replacement = module("slack").SlackDriver()
    replacement._platform = driver._platform
    restored, _ = bind("slack", replacement, tmp_path)
    restored.state = stale
    await replacement._restore_responses()
    await replacement._state_changed("connected")
    assert not replacement._routes.snapshots()
    refs = restored.receipts.list()[0]["value"]["resource_refs"]
    delivery = next(row for row in refs if row["kind"] == "slack.delivery")
    assert delivery["attributes"].get("final") != "true"
    assert delivery["attributes"].get("cleanup") != "complete"
    assert any(
        row["kind"] == "slack.attempt"
        and row["attributes"]["state"] == "unknown"
        and len(row["attributes"]["fingerprint"]) == 64
        for row in refs
    )
    if unknown_at == "end":
        assert unknown_refs
    for key, attrs in unknown_refs.items():
        assert (
            next(row for row in refs if row["resource_id"] == key)[
                "attributes"
            ]
            == attrs
        )
    # SQLite fences a duplicate finish and an old live checkpoint.
    await finish(restored, identity, handle)
    restored.state = stale
    await replacement._restore_responses()
    assert not replacement._routes.snapshots()
    if unknown_at == "end":
        assert (await send(restored, identity, handle, **ending))[
            "state"
        ] == "unknown"
    assert len(updates) == 1
    await open_route(restored, identity, "D123")
