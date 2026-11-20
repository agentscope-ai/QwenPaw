# -*- coding: utf-8 -*-
"""MQTT subscriptions, native payloads and confirmed delivery."""

import json
from types import SimpleNamespace as NS

import pytest
from tests.channel_support.driver import bind, module
from qwenpaw.channel_protocol import shared_response_driver
from qwenpaw.channel_protocol.response_lifecycle import ResponseStateError
from qwenpaw.channel_protocol.response_receipts import receipt_key
from tests.channel_support.protocol import eventually, finish, open_route, send


class Client:
    def __init__(self, **options):
        self.options, self.subscriptions, self.published = options, [], []
        self._last_mid, self.closed, self.confirmed = 0, False, True
        self.waits = []

    def reconnect_delay_set(self, **kwargs):
        pass

    def connect(self, host, port, keepalive):
        self.connection = host, port, keepalive

    def loop_start(self):
        self.on_connect(self, None, {}, 0)
        return 0

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))
        return 0, 1

    def publish(self, topic, text, qos):
        self.published.append((topic, text, qos))
        self._last_mid += 1
        return NS(
            rc=0,
            mid=self._last_mid,
            wait_for_publish=lambda timeout: self.waits.append(timeout),
            is_published=lambda: self.confirmed,
        )

    def disconnect(self):
        self.closed = True

    def loop_stop(self):
        return 0


@pytest.fixture
async def mqtt(tmp_path, monkeypatch):
    native = module("mqtt", "platform")
    monkeypatch.setattr(native.mqtt, "Client", Client)
    driver = module("mqtt").MQTTDriver()
    peer, identity = bind("mqtt", driver, tmp_path)
    await driver.start(
        dict(
            host="broker.invalid",
            subscribe_topic="request/+/text",
            publish_topic="reply/{client_id}",
            qos=2,
        ),
    )
    yield driver, peer, identity, driver._platform.client
    await driver.stop()


async def inbound(value, payload, topic="request/device-A/text"):
    driver, peer, _, client = value
    client.on_message(client, None, NS(payload=payload, topic=topic))
    await eventually(lambda: bool(peer.batches))
    return peer.batches[-1]["events"][0]


async def test_start_subscribes_with_configured_qos(mqtt):
    driver, _, _, client = mqtt
    assert client.connection == ("broker.invalid", 1883, 60)
    assert client.subscriptions == [("request/+/text", 2)]
    assert driver._connected and not client.options["reconnect_on_failure"]


@pytest.mark.parametrize(
    "payload,sender,text",
    [
        (b"hello", "device-A", "hello"),
        (
            b'{"text":"structured","redirect_client_id":"device-B"}',
            "device-B",
            "structured",
        ),
    ],
)
async def test_payload_and_topic_resolve_native_reply_destination(
    mqtt,
    payload,
    sender,
    text,
):
    driver, peer, identity, client = mqtt
    event = await inbound(mqtt, payload)
    assert event["sender_id"] == event["acl_sender_id"] == sender
    assert event["conversation"] == {
        "id": sender,
        "type": "dm",
        "thread_id": None,
    }
    assert event["content_parts"] == [{"type": "text", "text": text}]
    assert event["metadata"]["topic"] == "request/device-A/text"
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    assert client.published == [("reply/" + sender, "native answer", 2)]
    assert client.waits == [3.0]


async def test_publish_confirmation_unknown_is_not_replayed(
    mqtt,
    tmp_path,
    monkeypatch,
):
    driver, peer, identity, client = mqtt
    event = await inbound(mqtt, b"hello")
    client.confirmed = False
    first = await send(peer, identity, event["response_handle"])
    assert first["state"] == "unknown"
    assert first["reason_code"] == "MQTT_CONFIRMATION_UNKNOWN"
    assert await send(peer, identity, event["response_handle"]) == first
    assert client.published == [("reply/device-A", "native answer", 2)]

    # A single slot makes capacity recovery observable without a stress loop.
    monkeypatch.setattr(shared_response_driver, "_MAX_ROUTES", 1)
    handle = event["response_handle"]
    config = dict(driver._config)
    for archived in (False, True):
        await driver.stop()
        checkpoint = json.loads(json.dumps(peer.state))
        driver = module("mqtt").MQTTDriver()
        peer, identity = bind("mqtt", driver, tmp_path)
        peer.state = checkpoint
        try:
            await driver.start(config)
            client = driver._platform.client
            assert await send(peer, identity, handle) == first
            assert client.published == []
            assert len(driver._routes.snapshots()) == (0 if archived else 1)
            if not archived:
                with pytest.raises(ResponseStateError) as error:
                    await open_route(peer, identity, "device-B")
                assert error.value.reason_code == "RESPONSE_SCOPE_LIMIT"
                assert (await finish(peer, identity, handle))[
                    "state"
                ] == "closed"
                assert driver._routes.snapshots() == ()
                assert peer.state[driver._state_key] == []
                evidence = peer.receipts.get(
                    receipt_key(driver._state_key, handle),
                )
                assert evidence["cleanup_state"] == "complete"
                assert evidence["route_refs"] == []
                assert evidence["resource_refs"][0]["attributes"]["state"] == (
                    "unknown"
                )
            else:
                replacement = await open_route(peer, identity, "device-B")
                assert replacement != handle
                assert (await send(peer, identity, replacement))["state"] == (
                    "acknowledged"
                )
                assert client.published == [
                    ("reply/device-B", "native answer", 2),
                ]
                assert await send(peer, identity, handle) == first
                assert len(client.published) == 1
        finally:
            await driver.stop()


async def test_malformed_payload_is_filtered_before_valid_barrier(mqtt):
    driver, peer, _, client = mqtt
    for payload in (b"[]", b"\xff", b'{"text":12}', b'{"text":""}'):
        client.on_message(
            client,
            None,
            NS(payload=payload, topic="request/device-A/text"),
        )
    event = await inbound(mqtt, b"barrier")
    assert len(peer.batches) == 1
    assert event["content_parts"] == [{"type": "text", "text": "barrier"}]


async def test_stop_disconnects_and_is_idempotent_without_connection(
    mqtt,
    tmp_path,
):
    driver, _, _, client = mqtt
    platform = driver._platform
    await driver.stop()
    assert client.closed and platform.client is None and not platform.connected
    await driver.stop()
    fresh = module("mqtt").MQTTDriver()
    bind("mqtt", fresh, tmp_path)
    await fresh.stop()
    await fresh.stop()
