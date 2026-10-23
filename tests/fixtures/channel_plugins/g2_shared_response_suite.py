"""Public reply RPC contracts with a minimal non-card/editable platform."""

import hashlib
import tempfile
from pathlib import Path

import pytest

from qwenpaw.channel_protocol.models import (
    EventBatchAck,
    IdentityParams,
    InboundEvent,
    ResponseFinishParams,
    ResponseOutcome,
    SendParams,
)
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseCleanupState,
    ResponseResourceRef,
    ResponseRouteKind,
)
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext


def test_send_format_policy_keeps_legacy_three_field_wire_and_detached_flags():
    from qwenpaw.channel_protocol.response_policy import (
        ResponsePolicy,
        SendFormatPolicy,
    )

    legacy = {
        "streaming": False,
        "prepare": False,
        "completion_reaction": False,
    }
    assert ResponsePolicy.from_mapping(legacy).to_mapping() == legacy
    assert SendFormatPolicy().to_mapping() == {
        "direct_prefix": True,
        "parts_configured_prefix": True,
    }
    source = {
        **legacy,
        "send_format": {
            "direct_prefix": False,
            "parts_configured_prefix": False,
        },
    }
    policy = ResponsePolicy.from_mapping(source)
    source["send_format"]["direct_prefix"] = True
    assert policy.send_format.to_mapping() == {
        "direct_prefix": False,
        "parts_configured_prefix": False,
    }
    assert policy.to_mapping() == {
        **legacy,
        "send_format": {
            "direct_prefix": False,
            "parts_configured_prefix": False,
        },
    }


@pytest.mark.parametrize(
    "formatting",
    [
        None,
        True,
        {},
        {"direct_prefix": False},
        {
            "direct_prefix": False,
            "parts_configured_prefix": False,
            "unknown": False,
        },
        {"direct_prefix": 0, "parts_configured_prefix": False},
        {"direct_prefix": False, "parts_configured_prefix": "false"},
    ],
)
def test_send_format_policy_rejects_null_unknown_missing_and_nonboolean_fields(
    formatting,
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.response_policy import ResponsePolicy

    with pytest.raises(ProtocolValidationError):
        ResponsePolicy.from_mapping(
            {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
                "send_format": formatting,
            }
        )


class DeliveryError(Exception):
    def __init__(
        self, reason_code, *, side_effect_possible=False, retryable=False
    ):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable


class Peer:
    """The host state/admission boundary; Driver logic is never replaced."""

    def __init__(self):
        self.methods, self.state, self.diagnostics = {}, {}, []
        self.batches, self.admissions = [], []
        self._receipt_dir = tempfile.TemporaryDirectory()

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, name, params):
        if name.startswith("host.receipt."):
            from qwenpaw.channel_protocol.response_receipts import (
                ResponseReceiptStore,
            )

            store = ResponseReceiptStore(
                Path(self._receipt_dir.name) / "receipts.sqlite3"
            )
            if name == "host.receipt.get":
                return {"value": store.get(params["key"])}
            store.put(params["key"], params["value"])
            return {"stored": True}
        if name == "host.state.put":
            self.state[params["key"]] = params["value"]
            return {}
        if name == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if name == "event.batch":
            self.batches.append(params)
            result = self.admissions.pop(0)
            if isinstance(result, Exception):
                raise result
            return {**result.to_mapping(), "batch_id": params["batch_id"]}
        raise AssertionError(name)

    async def notify(self, name, params):
        self.diagnostics.append((name, params))


class NonCardDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__("plain", "responses", DeliveryError)
        self.effects, self.typing = [], set()
        self.prepare_unknown = False
        self.cleanup_unknown = False
        self._connected = True

    def _require_connected(self):
        if not self._connected:
            raise ValueError("NOT_CONNECTED")
        return self

    def _check_connection(self, generation):
        if self._stopping or generation != self._connection_generation:
            raise RuntimeError("STALE_CONNECTION_CALLBACK")

    async def _open(self, params, request):
        self._identity(params)
        handle = params["to_handle"]
        await self._persist_route(handle, {"room": "same-room"})
        return {"response_handle": handle}

    async def _perform_send(self, params):
        self.effects.append(("send", params.delivery_id))
        return ResponseResourceRef.create(
            "plain.delivery",
            params.delivery_id,
            {
                "message_id": "native-message",
                "sequence": "2",
                "text": "answer",
            },
        )

    async def _perform_reaction(self, params):
        raise AssertionError("No reaction capability")

    async def _perform_prepare(self, params):
        assert params.operation.value == "response.prepare"
        self.effects.append(("prepare", params.to_handle))
        self.typing.add(params.to_handle)
        if self.prepare_unknown:
            raise DeliveryError("TYPING_UNKNOWN", side_effect_possible=True)

    def _needs_stream_cleanup(self, ref):
        return bool(dict(ref.attributes).get("message_id"))

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        self.effects.append(("final-edit", sequence))
        if self.cleanup_unknown:
            raise DeliveryError("EDIT_UNKNOWN", side_effect_possible=True)

    async def _before_cleanup_complete(self, snapshot):
        self.typing.discard(snapshot.response_handle)
        return snapshot


def bound_driver():
    driver, peer = NonCardDriver(), Peer()
    identity = IdentityParams("plain", "workspace-A", 1)
    driver.bind(DriverContext(peer, identity))
    return driver, peer, identity.to_mapping()


async def open_route(peer, identity, handle="plain:reply:one"):
    result = await peer.methods["channel.response.open"](
        {**identity, "to_handle": handle, "meta": {}},
        None,
    )
    assert result == {"response_handle": handle}
    return handle


async def finish(peer, identity, handle):
    return await peer.methods["channel.response.finish"](
        ResponseFinishParams(
            **identity,
            response_handle=handle,
            outcome=ResponseOutcome.COMPLETED,
        ),
        None,
    )


async def prepare(peer, identity, handle):
    assert "channel.response.prepare" in peer.methods
    return await peer.methods["channel.response.prepare"](
        {
            **identity,
            "response_handle": handle,
            "delivery_id": hashlib.sha256(
                (handle + ":prepare").encode()
            ).hexdigest(),
        },
        None,
    )


def send_params(identity, handle, delivery_id="delivery-one", text="answer"):
    return SendParams.from_mapping(
        {
            **identity,
            "delivery_id": delivery_id,
            "to_handle": handle,
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": text}],
        }
    )


@pytest.mark.asyncio
async def test_completed_unknown_receipts_do_not_exhaust_new_response_quota():
    driver, peer, identity = bound_driver()

    async def uncertain_send(params):
        driver.effects.append(("send", params.delivery_id))
        raise TimeoutError("platform acknowledgement lost")

    driver._perform_send = uncertain_send
    for index in range(160):
        handle = await open_route(peer, identity, f"plain:reply:{index}")
        result = await peer.methods["channel.send"](
            send_params(identity, handle, f"delivery-{index}"), None
        )
        assert result["state"] == "unknown"
        await finish(peer, identity, handle)
    assert len(driver.effects) == 160
    assert await open_route(peer, identity, "plain:reply:next")


@pytest.mark.asyncio
async def test_noncard_finish_completes_after_disconnect_without_platform_effect():
    driver, peer, identity = bound_driver()
    handle = await open_route(peer, identity)
    driver._connected = False
    await finish(peer, identity, handle)
    assert (
        driver._routes.snapshot(handle).cleanup_state
        is ResponseCleanupState.COMPLETE
    )
    assert peer.state["responses"][0]["cleanup_state"] == "complete"
    assert driver.effects == []


@pytest.mark.asyncio
async def test_public_prepare_is_idempotent_and_finish_owns_only_its_typing():
    driver, peer, identity = bound_driver()
    first = await open_route(peer, identity)
    second = await open_route(peer, identity, "plain:reply:two")
    for handle in (first, first, second):
        assert (await prepare(peer, identity, handle))[
            "state"
        ] == "acknowledged"
    assert driver.effects == [("prepare", first), ("prepare", second)]
    driver._connected = False
    await finish(peer, identity, first)
    assert driver.typing == {second}
    await finish(peer, identity, second)
    assert driver.typing == set()


@pytest.mark.asyncio
async def test_prepare_unknown_is_not_replayed_and_receipt_survives_finish():
    driver, peer, identity = bound_driver()
    handle = await open_route(peer, identity)
    driver.prepare_unknown = True
    for _ in range(2):
        result = await prepare(peer, identity, handle)
        assert (
            result["state"] == "unknown"
            and result["reason_code"] == "TYPING_UNKNOWN"
        )
    assert driver.effects == [("prepare", handle)]
    await finish(peer, identity, handle)
    from qwenpaw.channel_protocol.response_receipts import receipt_key

    snapshot = (
        await peer.call(
            "host.receipt.get", {"key": receipt_key("responses", handle)}
        )
    )["value"]
    assert snapshot["cleanup_state"] == "complete"
    assert len(snapshot["resource_refs"]) == 1
    assert snapshot["resource_refs"][0]["attributes"]["state"] == "unknown"
    assert (await prepare(peer, identity, handle))["state"] == "unknown"
    assert driver.effects == [("prepare", handle)]


@pytest.mark.asyncio
async def test_editable_noncard_message_receives_final_edit():
    driver, peer, identity = bound_driver()
    handle = await open_route(peer, identity)
    params = SendParams.from_mapping(
        {
            **identity,
            "delivery_id": "delivery-one",
            "to_handle": handle,
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "answer"}],
        },
    )
    assert (await peer.methods["channel.send"](params, None))[
        "state"
    ] == "acknowledged"
    await finish(peer, identity, handle)
    assert driver.effects == [("send", "delivery-one"), ("final-edit", 3)]


@pytest.mark.asyncio
async def test_unknown_final_edit_is_never_repeated():
    from qwenpaw.channel_protocol.errors import RpcError

    driver, peer, identity = bound_driver()
    handle = await open_route(peer, identity)
    driver._routes.record_delivery(
        handle,
        [
            ResponseResourceRef.create(
                "plain.delivery",
                "delivery-one",
                {"message_id": "native-message", "sequence": "2"},
            )
        ],
    )
    driver.cleanup_unknown = True
    for _ in range(2):
        with pytest.raises(RpcError):
            await finish(peer, identity, handle)
    assert driver.effects == [("final-edit", 3)]
    assert (
        driver._routes.snapshot(handle).cleanup_state
        is not ResponseCleanupState.COMPLETE
    )


def inbound(identity, handle):
    return InboundEvent.from_mapping(
        {
            **identity,
            "event_id": "native-one",
            "event_kind": "message",
            "conversation": {"id": "room", "type": "dm", "thread_id": None},
            "sender_id": "human",
            "acl_sender_id": "human",
            "sender_name": "Human",
            "content_parts": [{"type": "text", "text": "hello"}],
            "metadata": {
                "session_id": "historic",
                "user_id": "human",
                "debounce_key": "historic",
            },
            "response_handle": handle,
        }
    )


@pytest.mark.asyncio
async def test_duplicate_ack_cleans_new_orphan_route_without_touching_live_route():
    driver, peer, identity = bound_driver()
    live = await open_route(peer, identity)
    orphan = await open_route(peer, identity, "plain:reply:orphan")
    driver.typing.update((live, orphan))
    peer.admissions = [EventBatchAck(duplicate_event_ids=("native-one",))]
    ack, uncertain = await driver._admit_event(
        inbound(identity, orphan), created=True
    )
    assert ack.duplicate_event_ids == ("native-one",) and not uncertain
    assert (
        driver._routes.snapshot(orphan) is None
        or driver._routes.snapshot(orphan).cleanup_state
        is ResponseCleanupState.COMPLETE
    )
    assert driver._routes.snapshot(live).kind is ResponseRouteKind.ACTIVE
    assert driver.typing == {live}


@pytest.mark.asyncio
async def test_lost_ack_reuses_identical_event_and_keeps_possibly_live_route():
    driver, peer, identity = bound_driver()
    handle = await open_route(peer, identity)
    peer.admissions = [
        ConnectionError("ACK lost"),
        EventBatchAck(duplicate_event_ids=("native-one",)),
    ]
    ack, uncertain = await driver._admit_event(
        inbound(identity, handle), created=True
    )
    assert ack.duplicate_event_ids == ("native-one",) and uncertain
    assert len(peer.batches) == 2 and peer.batches[0] == peer.batches[1]
    assert driver._routes.snapshot(handle).kind is ResponseRouteKind.ACTIVE


@pytest.mark.asyncio
async def test_prepare_rejects_stale_identity_and_wrong_delivery_before_effect():
    from qwenpaw.channel_protocol.errors import RpcError

    driver, peer, identity = bound_driver()
    handle = await open_route(peer, identity)
    assert "channel.response.prepare" in peer.methods
    with pytest.raises(RpcError):
        await prepare(peer, {**identity, "generation": 2}, handle)
    with pytest.raises(ValueError):
        await peer.methods["channel.response.prepare"](
            {**identity, "response_handle": handle, "delivery_id": "wrong"},
            None,
        )
    assert driver.effects == []
