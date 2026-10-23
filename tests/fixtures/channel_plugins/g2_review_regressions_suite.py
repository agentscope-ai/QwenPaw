"""Independent F1/F2/F3 regressions on real Drivers/platform, SDK boundaries only.

These are in-process contracts, not worker/process lifecycle evidence.
"""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest
from g2_shared_response_suite import Peer

ROOT = Path(__file__).resolve().parents[3]
for source in ("feishu", "dingtalk", "mqtt"):
    sys.path.insert(0, str(ROOT / "plugins/channel" / source))

from feishu.driver import FeishuDriver
from dingtalk.driver import DingTalkDriver
import paho.mqtt.client as mqtt
from qwenpaw_channel_mqtt.platform import MQTTPlatform
from qwenpaw.channel_protocol.errors import RpcError
from qwenpaw.channel_protocol.models import (
    IdentityParams,
    ResponseFinishParams,
    ResponseOutcome,
    SendParams,
)
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseCleanupState,
    ResponseResourceRef,
    ResponseRouteSnapshot,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext


class HostStateBoundary(Peer):
    """JSON-copy host state; the route aggregate and journal remain production."""

    def __init__(self):
        super().__init__()
        self.methods, self.state, self.diagnostics = {}, {}, []

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, name, params):
        if name.startswith("host.receipt."):
            return await super().call(name, params)
        if name == "host.state.put":
            # Require real typed restore compatibility on every checkpoint.
            for row in params["value"]:
                ResponseRouteSnapshot.from_mapping(row)
            self.state[params["key"]] = deepcopy(params["value"])
            return {}
        if name == "host.state.get":
            return {"value": deepcopy(self.state.get(params["key"]))}
        raise AssertionError(name)

    async def notify(self, name, params):
        self.diagnostics.append((name, deepcopy(params)))


class CardSDKBoundary:
    at_sender_on_reply = False

    def __init__(self):
        self.starts, self.edits = [], []
        self.update_failure = None

    async def start_stream(self, *args, **kwargs):
        self.starts.append((args, kwargs))
        return {"card_id": "native-card", "conversation_id": "native-room"}

    async def update_stream(self, resource, text, sequence, *, final):
        self.edits.append((resource["card_id"], text, sequence, final))
        if self.update_failure:
            raise self.update_failure
        return True


def bind_driver(driver_type, peer=None, *, generation=1):
    driver = driver_type()
    peer = peer or HostStateBoundary()
    identity = IdentityParams(driver._kind, "review-workspace", generation)
    driver.bind(DriverContext(peer, identity))
    driver._platform = CardSDKBoundary()
    driver._connected = True
    return driver, peer, identity.to_mapping()


async def card_route(driver, identity):
    handle = driver._kind + ":reply:review"
    attrs = {"session_ctx": "{}", "bot_prefix": "", "to_handle": "native-room"}
    if driver._kind == "feishu":
        attrs.update(
            receive_id_type="chat_id", receive_id="native-room", reply_message_id=""
        )
    await driver._persist_route(handle, attrs)
    params = SendParams.from_mapping(
        {
            **identity,
            "delivery_id": "card-start",
            "to_handle": handle,
            "operation": "stream.start",
            "stream_type": "message",
            "sequence": 0,
            "accumulated_text": "answer",
        }
    )
    result = await driver._context.peer.methods["channel.send"](params, None)
    assert result["state"] == "acknowledged", result
    assert len(driver._platform.starts) == 1
    return handle


async def finish(driver, identity, handle, outcome):
    return await driver._context.peer.methods["channel.response.finish"](
        ResponseFinishParams(**identity, response_handle=handle, outcome=outcome),
        None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("driver_type", [FeishuDriver, DingTalkDriver])
@pytest.mark.parametrize(
    "outcome", [ResponseOutcome.COMPLETED, ResponseOutcome.CANCELLED]
)
@pytest.mark.parametrize("restore", [False, True], ids=["reconnect", "journal-restore"])
async def test_f1_offline_card_finish_retries_one_final_edit(
    driver_type, outcome, restore
):
    driver, peer, identity = bind_driver(driver_type)
    handle = await card_route(driver, identity)
    platform = driver._platform
    driver._connected = False
    with pytest.raises(RpcError):
        await finish(driver, identity, handle, outcome)
    assert platform.edits == []
    if restore:
        driver, _, identity = bind_driver(driver_type, peer, generation=2)
        driver._platform = platform
        await driver._restore_responses()
    else:
        driver._connected = True
    # A known pre-effect disconnect must not freeze the resource as unknown.
    await finish(driver, identity, handle, outcome)
    await finish(driver, identity, handle, outcome)
    assert len(platform.edits) == 1
    assert platform.edits[0][0:2] == ("native-card", "answer")
    assert platform.edits[0][2] > 0 and platform.edits[0][3] is True
    assert (
        driver._routes.snapshot(handle).cleanup_state is ResponseCleanupState.COMPLETE
    )
    stored = ResponseRouteSnapshot.from_mapping(peer.state[driver._state_key][0])
    assert stored.cleanup_state is ResponseCleanupState.COMPLETE


@pytest.mark.asyncio
@pytest.mark.parametrize("driver_type", [FeishuDriver, DingTalkDriver])
async def test_f1_truly_unknown_final_edit_is_preserved_across_restore(driver_type):
    driver, peer, identity = bind_driver(driver_type)
    handle = await card_route(driver, identity)
    platform = driver._platform
    platform.update_failure = driver.delivery_error(
        "EDIT_ACK_LOST", side_effect_possible=True
    )
    with pytest.raises(RpcError):
        await finish(driver, identity, handle, ResponseOutcome.COMPLETED)
    assert len(platform.edits) == 1
    restored, _, identity = bind_driver(driver_type, peer, generation=2)
    restored._platform = platform
    await restored._restore_responses()
    platform.update_failure = None
    for _ in range(2):
        with pytest.raises(RpcError):
            await finish(restored, identity, handle, ResponseOutcome.COMPLETED)
    assert len(platform.edits) == 1
    assert (
        restored._routes.snapshot(handle).cleanup_state
        is not ResponseCleanupState.COMPLETE
    )


def legacy_ding_prepare(identity, handle, *, text="...", stream_type="message"):
    """HEAD DingTalkDriver._prepare SendParams, not a hand-written hash.

    HEAD builds stream.start/message/sequence=0/accumulated_text='...';
    HEAD SharedResponseDriver fingerprints JSON(to_mapping minus generation).
    """
    operation = SendParams.from_mapping(
        {
            **identity,
            "delivery_id": hashlib.sha256((handle + ":prepare").encode()).hexdigest(),
            "to_handle": handle,
            "operation": "stream.start",
            "stream_type": stream_type,
            "sequence": 0,
            "accumulated_text": text,
        }
    )
    encoded = operation.to_mapping()
    assert encoded == {
        **identity,
        "delivery_id": operation.delivery_id,
        "to_handle": handle,
        "operation": "stream.start",
        "stream_type": stream_type,
        "sequence": 0,
        "accumulated_text": text,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {key: value for key, value in encoded.items() if key != "generation"},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return operation, fingerprint


async def restore_old_ding_prepare(state, *, text="...", stream_type="message"):
    old, peer, identity = bind_driver(DingTalkDriver)
    handle = "dingtalk:reply:legacy-prepare"
    await old._persist_route(
        handle, {"session_ctx": "{}", "bot_prefix": "", "to_handle": "native-room"}
    )
    operation, fingerprint = legacy_ding_prepare(
        identity, handle, text=text, stream_type=stream_type
    )
    reason = (
        "OLD_PREPARE_UNKNOWN"
        if state == "unknown"
        else "OLD_PREPARE_FAILED" if state == "failed" else ""
    )
    old._routes.record_delivery(
        handle,
        [
            ResponseResourceRef.create(
                "dingtalk.attempt",
                operation.delivery_id,
                {
                    "fingerprint": fingerprint,
                    "operation": "stream.start",
                    "state": state,
                    "reason_code": reason,
                    "target_delivery_id": "",
                    "sequence": "0",
                },
            )
        ],
    )
    await old._checkpoint()
    restored, _, identity = bind_driver(DingTalkDriver, peer, generation=2)
    await restored._restore_responses()
    return restored, peer, identity, handle, operation.delivery_id, reason


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unknown", "acknowledged", "failed"])
async def test_f2_old_prepare_receipt_survives_internal_dto_upgrade(state):
    driver, peer, identity, handle, delivery_id, reason = (
        await restore_old_ding_prepare(state)
    )
    before = deepcopy(peer.state[driver._state_key])
    for _ in range(2):
        result = await peer.methods["channel.response.prepare"](
            {
                **identity,
                "response_handle": handle,
                "delivery_id": delivery_id,
            },
            None,
        )
        assert result["state"] == state, result
        assert result.get("reason_code", "") == reason, result
    assert driver._platform.starts == driver._platform.edits == []
    assert peer.state[driver._state_key] == before


def mqtt_message(text):
    message = mqtt.MQTTMessage(mid=17)
    message.topic = b"in/human"
    message.payload = json.dumps({"text": text}).encode()
    return message


async def drain_callbacks(platform):
    # Flush call_soon_threadsafe dispatch, then actual platform-owned tasks.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    if platform._tasks:
        await asyncio.gather(*tuple(platform._tasks))


async def mqtt_platform(monkeypatch, *, on_state=None):
    events, states, subscriptions, stopped = [], [], [], []

    async def event(value):
        events.append(value)

    async def state(value):
        states.append(value)
        if on_state:
            await on_state(value)

    # Keep genuine paho Client and MQTTMessage; replace only network/loop I/O.
    monkeypatch.setattr(
        mqtt.Client, "connect", lambda self, *args: mqtt.MQTT_ERR_SUCCESS
    )

    def loop_start(client):
        client.on_connect(client, None, {}, 0)
        return mqtt.MQTT_ERR_SUCCESS

    monkeypatch.setattr(mqtt.Client, "loop_start", loop_start)
    monkeypatch.setattr(
        mqtt.Client,
        "loop_stop",
        lambda self: stopped.append(self) or mqtt.MQTT_ERR_SUCCESS,
    )
    monkeypatch.setattr(mqtt.Client, "disconnect", lambda self: mqtt.MQTT_ERR_SUCCESS)
    monkeypatch.setattr(
        mqtt.Client,
        "subscribe",
        lambda self, topic, qos=0: subscriptions.append((self, topic, qos))
        or (mqtt.MQTT_ERR_SUCCESS, 1),
    )
    platform = MQTTPlatform(
        {
            "host": "localhost",
            "subscribe_topic": "in/+",
            "publish_topic": "out/{client_id}",
            "qos": 1,
        },
        event,
        state,
    )
    return platform, events, states, subscriptions, stopped


@pytest.mark.asyncio
@pytest.mark.parametrize("callback", ["message", "connect", "disconnect"])
async def test_f3_replaced_paho_client_callbacks_do_not_touch_current_owner(
    monkeypatch, callback
):
    platform, events, states, subscriptions, stopped = await mqtt_platform(monkeypatch)
    try:
        await platform.start()
        old = platform.client
        platform._ready.clear()
        await platform.start()
        current = platform.client
        await drain_callbacks(platform)
        assert (
            isinstance(old, mqtt.Client)
            and isinstance(current, mqtt.Client)
            and old is not current
        )
        epoch, before_states, before_subscriptions = (
            platform._epoch,
            list(states),
            list(subscriptions),
        )
        if callback == "message":
            old.on_message(old, None, mqtt_message("stale"))
        elif callback == "connect":
            old.on_connect(old, None, {}, 0)
        else:
            old.on_disconnect(old, None, {}, 1)
        # Flush dispatch without waiting for a buggy reconnect's retry sleep.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert platform.client is current and platform.connected
        assert platform._epoch == epoch
        assert states == before_states and subscriptions == before_subscriptions
        assert stopped == [] and events == []
        current.on_message(current, None, mqtt_message("fresh"))
        await drain_callbacks(platform)
        assert [event["text"] for event in events] == ["fresh"]
    finally:
        await platform.stop()


@pytest.mark.asyncio
async def test_f3_old_message_queued_before_replacement_is_fenced_at_execution(
    monkeypatch,
):
    platform, events, _, _, _ = await mqtt_platform(monkeypatch)
    try:
        await platform.start()
        old = platform.client
        old.on_message(old, None, mqtt_message("queued-old"))
        # start replaces self.client before its first network await, while the
        # old message is already queued on the production callback scheduler.
        platform._ready.clear()
        await platform.start()
        current = platform.client
        assert current is not old
        await drain_callbacks(platform)
        assert events == []
        current.on_message(current, None, mqtt_message("fresh"))
        await drain_callbacks(platform)
        assert [event["text"] for event in events] == ["fresh"]
    finally:
        await platform.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("callback", ["connect", "disconnect"])
async def test_f3_old_state_callback_queued_before_replacement_is_fenced(
    monkeypatch, callback
):
    platform, events, states, subscriptions, stopped = await mqtt_platform(monkeypatch)
    try:
        await platform.start()
        await drain_callbacks(platform)
        old = platform.client
        states.clear()
        if callback == "connect":
            old.on_connect(old, None, {}, 0)
        else:
            old.on_disconnect(old, None, {}, 1)
        platform._ready.clear()
        await platform.start()
        current = subscriptions[-1][0]
        # Old _connected/_reconnect were queued while old still owned the
        # connection; their execution must recheck ownership after replacement.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert platform.client is current and current is not old and platform.connected
        assert stopped == []
        assert states == ["connected"]
        current.on_message(current, None, mqtt_message("fresh"))
        await drain_callbacks(platform)
        assert [event["text"] for event in events] == ["fresh"]
    finally:
        await platform.stop()


@pytest.mark.asyncio
async def test_f3_old_connected_task_cannot_set_replacement_ready_after_await(
    monkeypatch,
):
    entered, release = asyncio.Event(), asyncio.Event()
    connected_calls = 0

    async def state(value):
        nonlocal connected_calls
        if value == "connected":
            connected_calls += 1
            if connected_calls == 1:
                entered.set()
                await release.wait()

    platform, events, _, _, _ = await mqtt_platform(monkeypatch, on_state=state)
    first = asyncio.create_task(platform.start())
    try:
        await entered.wait()
        old = platform.client
        platform._ready.clear()
        await platform.start()
        current = platform.client
        assert current is not old and platform.connected and platform._ready.is_set()
        # The first startup may finish or reject after losing its owner; the
        # contract here is its already-running connected task's ready effect.
        await asyncio.gather(first, return_exceptions=True)
        # Isolate completion of the old connected task after its state await.
        platform._ready.clear()
        release.set()
        await drain_callbacks(platform)
        assert not platform._ready.is_set()
        current.on_connect(current, None, {}, 0)
        await drain_callbacks(platform)
        assert platform._ready.is_set()
        current.on_message(current, None, mqtt_message("fresh"))
        await drain_callbacks(platform)
        assert [event["text"] for event in events] == ["fresh"]
    finally:
        release.set()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        await platform.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,stream_type", [("different", "message"), ("...", "reasoning")]
)
async def test_f2_genuinely_different_old_prepare_fingerprint_stays_conflict(
    text, stream_type
):
    driver, peer, identity, handle, delivery_id, _ = await restore_old_ding_prepare(
        "unknown", text=text, stream_type=stream_type
    )
    before = deepcopy(peer.state[driver._state_key])
    result = await peer.methods["channel.response.prepare"](
        {
            **identity,
            "response_handle": handle,
            "delivery_id": delivery_id,
        },
        None,
    )
    assert result["state"] == "failed" and result["reason_code"] == "DELIVERY_CONFLICT"
    assert driver._platform.starts == driver._platform.edits == []
    assert peer.state[driver._state_key] == before
