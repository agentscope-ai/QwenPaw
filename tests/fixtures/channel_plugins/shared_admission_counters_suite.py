"""Legacy admission counters on real private Drivers; only host RPC doubled."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

from g2_shared_response_suite import inbound
from onebot_native_suite import HostBoundary, OneBotDriver
from qwenpaw.channel_protocol.errors import RpcError, RpcTimeoutError
from qwenpaw.channel_protocol.models import IdentityParams
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext


@pytest.mark.asyncio
async def test_real_onebot_pressure_retry_preserves_legacy_core_counters():
    driver, peer = OneBotDriver(), HostBoundary()
    assert isinstance(driver, SharedResponseDriver)
    identity = IdentityParams("onebot", "onebot-counter-A", 1)
    driver.bind(DriverContext(peer, identity))
    call = peer.call
    batches = []

    async def pressure_once(method, params):
        if method == "event.batch":
            batches.append(deepcopy(params))
            if len(batches) == 1:
                raise RpcError(
                    -32010,
                    "INGRESS_BACKPRESSURE",
                    data={"reason_code": "INGRESS_BACKPRESSURE"},
                )
        return await call(method, params)

    peer.call = pressure_once
    event = inbound(identity.to_mapping(), "onebot:reply:counter-A")
    ack, uncertain = await driver._admit_event(event, created=False)
    assert ack.accepted_event_ids == (event.event_id,)
    assert uncertain is True
    assert len(batches) == 2
    assert batches[0] == batches[1]
    assert batches[0]["events"][0]["event_id"] == event.event_id
    assert driver.diagnostics() == {
        "core_batch_backpressure_total": 1,
        "core_batch_timeout_total": 0,
        "core_batch_retry_total": 1,
    }


def bound_private_driver(kind, outcomes):
    """Use actual private initialization; script only host event.batch RPC."""
    if kind == "onebot":
        driver = OneBotDriver()
    else:
        sys.path.insert(
            0,
            str(Path(__file__).resolve().parents[3] / "plugins/channel/voice"),
        )
        from qwenpaw_channel_voice.driver import VoiceDriver

        driver = VoiceDriver()
    assert isinstance(driver, SharedResponseDriver)
    identity = IdentityParams(kind, kind + "-counter-control", 1)
    peer = HostBoundary()
    driver.bind(DriverContext(peer, identity))
    original = peer.call
    remaining, batches = list(outcomes), []

    async def host_admission(method, params):
        if method != "event.batch":
            return await original(method, params)
        batches.append(deepcopy(params))
        result = remaining.pop(0)
        if isinstance(result, Exception):
            raise result
        event_id = params["events"][0]["event_id"]
        ack = {"batch_id": params["batch_id"]}
        if result == "accepted":
            return {**ack, "accepted_event_ids": [event_id]}
        if result == "duplicate":
            return {**ack, "duplicate_event_ids": [event_id]}
        return {
            **ack,
            "rejected_events": [{"event_id": event_id, **result}],
        }

    peer.call = host_admission
    event = inbound(identity.to_mapping(), kind + ":reply:counter-control")
    return driver, peer, event, batches


def assert_counters(driver, *, pressure=0, timeout=0, retry=0):
    snapshot = driver.diagnostics()
    assert snapshot == {
        "core_batch_backpressure_total": pressure,
        "core_batch_timeout_total": timeout,
        "core_batch_retry_total": retry,
    }
    assert all(
        type(value) is int and value >= 0 for value in snapshot.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,retryable,pressure",
    [
        ("INGRESS_BACKPRESSURE", True, 1),
        ("INGRESS_BACKPRESSURE", False, 1),
        ("CORE_QUEUE_FULL", True, 0),
        ("PERMISSION_DENIED", False, 0),
    ],
)
async def test_ack_counts_only_exact_ingress_pressure_reason(
    reason, retryable, pressure
):
    outcomes = [{"reason_code": reason, "retryable": retryable}]
    if retryable:
        outcomes.append("accepted")
    driver, _peer, event, batches = bound_private_driver("onebot", outcomes)
    result = await driver._admit_event(event, created=False)
    if retryable:
        ack, uncertain = result
        assert ack.accepted_event_ids == (event.event_id,)
        assert uncertain is False
        assert len(batches) == 2 and batches[0] == batches[1]
    else:
        assert result is None
        assert len(batches) == 1
    assert_counters(driver, pressure=pressure, retry=int(retryable))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,reason,pressure",
    [
        ("onebot", "RPC_BACKPRESSURE", 1),
        ("voice", "TEMPORARY_UNAVAILABLE", 1),
        ("onebot", "TEMPORARY_UNAVAILABLE", 0),
    ],
)
async def test_actual_driver_rpc_pressure_policy_preserves_legacy_difference(
    kind, reason, pressure
):
    driver, _peer, event, batches = bound_private_driver(
        kind,
        [RpcError(-32010, reason, data={"reason_code": reason}), "accepted"],
    )
    ack, uncertain = await driver._admit_event(event, created=False)
    assert ack.accepted_event_ids == (event.event_id,)
    assert uncertain is True
    assert len(batches) == 2 and batches[0] == batches[1]
    assert_counters(driver, pressure=pressure, retry=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("rpc_timeout", [True, False])
async def test_only_typed_rpc_timeout_increments_timeout_counter(rpc_timeout):
    error = (
        RpcTimeoutError("typed host timeout")
        if rpc_timeout
        else TimeoutError("unclassified boundary failure")
    )
    driver, _peer, event, batches = bound_private_driver(
        "onebot", [error, "accepted"]
    )
    ack, uncertain = await driver._admit_event(event, created=False)
    assert ack.accepted_event_ids == (event.event_id,)
    assert uncertain is True
    assert len(batches) == 2 and batches[0] == batches[1]
    assert_counters(driver, timeout=int(rpc_timeout), retry=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("classification", ["accepted", "duplicate"])
async def test_success_and_duplicate_do_not_increment_admission_counters(
    classification,
):
    driver, _peer, event, batches = bound_private_driver(
        "onebot", [classification]
    )
    ack, uncertain = await driver._admit_event(event, created=False)
    ids = (
        ack.accepted_event_ids
        if classification == "accepted"
        else ack.duplicate_event_ids
    )
    assert ids == (event.event_id,)
    assert uncertain is False
    assert len(batches) == 1
    assert_counters(driver)


@pytest.mark.asyncio
async def test_exhausted_timeouts_count_five_attempts_and_only_four_retries():
    driver, peer, event, batches = bound_private_driver(
        "onebot", [RpcTimeoutError("host ACK timeout") for _ in range(5)]
    )
    with pytest.raises(RuntimeError, match="^HOST_ADMISSION_EXHAUSTED$"):
        await driver._admit_event(event, created=False)
    assert len(batches) == 5
    assert all(batch == batches[0] for batch in batches)
    assert any(
        params["reason_code"] == "HOST_ADMISSION_EXHAUSTED"
        for method, params in peer.notifications
        if method == "channel.diagnostic"
    )
    assert_counters(driver, timeout=5, retry=4)


@pytest.mark.asyncio
async def test_counter_instances_and_returned_snapshots_are_independent():
    driver, _peer, event, _batches = bound_private_driver(
        "onebot",
        [
            RpcError(
                -32010,
                "INGRESS_BACKPRESSURE",
                data={"reason_code": "INGRESS_BACKPRESSURE"},
            ),
            "accepted",
        ],
    )
    other = OneBotDriver()
    initial = driver.diagnostics()
    assert_counters(driver)
    await driver._admit_event(event, created=False)
    assert_counters(driver, pressure=1, retry=1)
    assert_counters(other)
    assert initial == other.diagnostics()
    exposed = driver.diagnostics()
    exposed["core_batch_backpressure_total"] = -100
    exposed["arbitrary_metric"] = 900
    del exposed["core_batch_retry_total"]
    assert_counters(driver, pressure=1, retry=1)
