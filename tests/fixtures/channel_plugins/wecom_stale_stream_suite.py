"""Real WeCom response lifecycle and SQLite; only SDK effects are scripted."""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import pytest

from qwenpaw.channel_protocol.models import (
    IdentityParams,
    ResponseFinishParams,
    ResponseOutcome,
    SendParams,
)
from qwenpaw.channel_protocol.response_receipts import ResponseReceiptStore
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.shared_worker import DriverContext

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/wecom"))

from qwenpaw_channel_wecom.driver import WeComDriver  # noqa: E402
from qwenpaw_channel_wecom.platform import WeComPlatform  # noqa: E402


class Host:
    def __init__(self, directory):
        self.methods, self.state, self.batches, self.notifications = (
            {},
            {},
            [],
            [],
        )
        self.receipts = ResponseReceiptStore(directory / "receipts.sqlite3")
        self.fail_archive = False
        self.lose_archive_ack = False
        self.fail_removal = False
        self.archive_gate = None
        self.state_gate = None
        self.connected_gate = None

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, name, params):
        if name == "host.receipt.get":
            return {"value": self.receipts.get(params["key"])}
        if name == "host.receipt.put":
            if self.archive_gate is not None:
                entered, release = self.archive_gate
                entered.set()
                await release.wait()
            if self.fail_archive:
                raise OSError("archive unavailable")
            self.receipts.put(params["key"], params["value"])
            if self.lose_archive_ack:
                self.lose_archive_ack = False
                raise OSError("archive acknowledgement lost")
            return {"stored": True}
        if name == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if name == "host.state.put":
            if self.state_gate is not None:
                count, entered, release = self.state_gate
                self.state_gate = count - 1, entered, release
                if count == 1:
                    entered.set()
                    await release.wait()
            if self.fail_removal and not params["value"]:
                raise OSError("live checkpoint unavailable")
            self.state[params["key"]] = json.loads(json.dumps(params["value"]))
            return {}
        assert name == "event.batch", name
        self.batches.append(params)
        return {
            "batch_id": params["batch_id"],
            "accepted_event_ids": [
                event["event_id"] for event in params["events"]
            ],
        }

    async def notify(self, name, params):
        if (
            name == "shared.state"
            and params.get("platform_state") == "connected"
            and self.connected_gate is not None
        ):
            entered, release = self.connected_gate
            entered.set()
            await release.wait()
        self.notifications.append((name, params))


class External:
    def __init__(self):
        self.effects, self.actions = [], deque()

    async def call(self, method, *args, **kwargs):
        self.effects.append((method, args, kwargs))
        if self.actions:
            action = self.actions.popleft()
            if isinstance(action, BaseException):
                raise action
            if action is not None:
                return await action()
        return {}


@asynccontextmanager
async def worker(directory, *, host=None, generation=1, epoch=1):
    host = host or Host(directory)
    identity = IdentityParams("wecom", "stale-stream-A", generation)
    driver = WeComDriver()
    capabilities = json.loads(
        (ROOT / "plugins/channel/wecom/channel.json").read_text()
    )["capabilities"]
    driver.bind(DriverContext(host, identity, capabilities))
    driver._config = {"streaming_enabled": True}
    await driver._restore_responses()
    platform = WeComPlatform(
        {"workspace_dir": str(directory)},
        driver._message,
        driver._state_changed,
    )
    driver._platform = platform
    platform._epoch = epoch
    platform._ready = asyncio.get_running_loop().create_future()
    external = External()
    platform._call = external.call
    await platform._state_changed("connected", epoch)
    try:
        yield driver, platform, host, identity, external
    finally:
        await driver.stop()


async def ingress(driver, host, number=0):
    await driver._message(
        {
            "event_id": f"message-{number}",
            "frame": {"headers": {"req_id": f"callback-{number}"}, "body": {}},
            "sender_id": "sender",
            "acl_sender_id": "sender",
            "user_id": "sender",
            "session_id": "wecom:sender",
            "content_parts": [{"type": "text", "text": "hello"}],
            "meta": {
                "wecom_chatid": "sender",
                "wecom_sender_id": "sender",
                "wecom_chat_type": "single",
                "is_group": False,
            },
        }
    )
    return host.batches[-1]["events"][0]["response_handle"]


async def prepare(driver, identity, handle):
    return await driver._prepare(
        {
            **identity.to_mapping(),
            "response_handle": handle,
            "delivery_id": hashlib.sha256(
                (handle + ":prepare").encode()
            ).hexdigest(),
        },
        None,
    )


async def finish(driver, identity, handle):
    return await driver._finish(
        ResponseFinishParams(
            **identity.to_mapping(),
            response_handle=handle,
            outcome=ResponseOutcome.FAILED,
        ),
        None,
    )


async def reconnect(platform):
    platform._epoch += 1
    await platform._state_changed("disconnected", platform._epoch)
    platform._epoch += 1
    await platform._state_changed("connected", platform._epoch)


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


async def send(
    driver, identity, handle, delivery, operation="stream.start", **fields
):
    return await driver._send(
        SendParams.from_mapping(
            {
                **identity.to_mapping(),
                "to_handle": handle,
                "delivery_id": delivery,
                "operation": operation,
                "stream_type": "message",
                "sequence": 0,
                "accumulated_text": "answer",
                **fields,
            }
        ),
        None,
    )


def unknown_effect():
    from qwenpaw_channel_wecom.errors import WeComDeliveryError

    return WeComDeliveryError(
        "PLATFORM_RESULT_UNKNOWN", side_effect_possible=True
    )


def archived(host, handle):
    values = [
        row["value"]
        for row in host.receipts.list(limit=1000)
        if row["value"]["response_handle"] == handle
    ]
    assert len(values) == 1
    value = values[0]
    assert value["cleanup_state"] == "complete"
    assert value["route_refs"] == []
    # Native identity stays as immutable evidence outside the route budget.
    assert any(
        ref["attributes"].get("frame_token") == handle
        and ref["attributes"].get("connection_epoch")
        for ref in value["resource_refs"]
    )
    return value


async def test_reconnect_finish_retires_old_native_processing_without_replay(
    tmp_path,
):
    """A stale frame must not leave terminal cleanup consuming either budget."""
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        prepared = await prepare(driver, identity, handle)
        assert prepared["state"] == "acknowledged"
        effects = list(external.effects)
        await reconnect(platform)
        result = await finish(driver, identity, handle)
        assert result["outcome"] == "failed"
        assert not driver._routes.pending_cleanups()
        assert handle not in platform._frames
        assert handle not in platform._processing
        assert not platform._keepalive_tasks
        assert external.effects == effects
        archived(host, handle)
        closed = await prepare(driver, identity, handle)
        assert closed["state"] == "failed"
        assert closed["reason_code"] == "RESPONSE_CLOSED"


async def test_same_epoch_worker_replacement_does_not_finish_active_execution(
    tmp_path,
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        assert (await prepare(driver, identity, handle))[
            "state"
        ] == "acknowledged"
        old_epoch = platform._epoch
    async with worker(tmp_path, host=host, generation=2, epoch=old_epoch) as (
        replacement,
        fresh_platform,
        _,
        new_identity,
        fresh_external,
    ):
        # Startup recovery is permitted only after execution has finished.
        assert replacement._routes.snapshot(handle).kind.value == "active"
        await finish(replacement, new_identity, handle)
        assert not replacement._routes.pending_cleanups()
        assert not fresh_platform._frames
        assert fresh_external.effects == []
        archived(host, handle)


async def test_full_old_pending_budget_recovers_on_connect_without_finish_rpc(
    tmp_path,
):
    handles = []
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        for number in range(128):
            handle = await ingress(driver, host, number)
            handles.append(handle)
            assert (await prepare(driver, identity, handle))[
                "state"
            ] == "acknowledged"
            # Historical worker loss after durable finish intent, before cleanup.
            driver._routes.begin_finish(handle, ResponseOutcome.FAILED)
        await driver._checkpoint()
        assert len(driver._routes.pending_cleanups()) == 128
    async with worker(tmp_path, host=host, generation=2) as (
        replacement,
        platform,
        _,
        identity,
        external,
    ):
        await eventually(lambda: not replacement._routes.pending_cleanups())
        assert len(host.receipts.list(limit=1000)) == 128
        assert external.effects == []
        for handle in handles:
            assert replacement._routes.snapshot(handle) is None
        new_handle = await ingress(replacement, host, 128)
        assert (await prepare(replacement, identity, new_handle))[
            "state"
        ] == "acknowledged"
        await finish(replacement, identity, new_handle)


async def test_130_serial_reconnects_do_not_exhaust_native_or_response_budget(
    tmp_path,
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        for number in range(130):
            handle = await ingress(driver, host, number)
            assert (await prepare(driver, identity, handle))[
                "state"
            ] == "acknowledged"
            effects = len(external.effects)
            await reconnect(platform)
            await finish(driver, identity, handle)
            assert not driver._routes.pending_cleanups()
            assert not platform._frames
            assert not platform._keepalive_tasks
            assert len(external.effects) == effects
        assert len(host.receipts.list(limit=1000)) == 130


@pytest.mark.parametrize(
    "failure", ["unsettled_start", "unknown_end", "unknown_cleanup"]
)
async def test_stale_unknown_stream_retires_but_preserves_original_uncertainty(
    tmp_path, failure
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        if failure == "unsettled_start":
            external.actions.append(unknown_effect())
        first = await send(driver, identity, handle, "stream-A")
        unknown_params = ("stream-A", "stream.start", {})
        if failure != "unsettled_start":
            assert first["state"] == "acknowledged"
            external.actions.append(unknown_effect())
            if failure == "unknown_end":
                fields = {"target_delivery_id": "stream-A", "sequence": 1}
                first = await send(
                    driver, identity, handle, "end-A", "stream.end", **fields
                )
                unknown_params = ("end-A", "stream.end", fields)
        with pytest.raises(Exception):
            await finish(driver, identity, handle)
        before = driver._routes.snapshot(handle)
        unknown_attempts = [
            ref
            for ref in before.resource_refs
            if ref.kind == "wecom.attempt"
            and dict(ref.attributes).get("state") == "unknown"
        ]
        assert before.cleanup_state.value == "pending"
        effects = list(external.effects)
        await reconnect(platform)
        await eventually(lambda: not driver._routes.pending_cleanups())
        receipt = archived(host, handle)
        for ref in unknown_attempts:
            assert ref.to_mapping() in receipt["resource_refs"]
        if failure != "unknown_cleanup":
            delivery, operation, fields = unknown_params
            assert first["state"] == "unknown"
            assert (
                await send(
                    driver, identity, handle, delivery, operation, **fields
                )
                == first
            )
            conflict = await send(
                driver,
                identity,
                handle,
                delivery,
                operation,
                **{**fields, "accumulated_text": "different"},
            )
            assert conflict["reason_code"] == "DELIVERY_CONFLICT"
        assert not platform._frames
        assert not platform._processing
        assert external.effects == effects
        # A fresh worker sees only immutable receipts, never reactivates routes.
    async with worker(tmp_path, host=host, generation=2) as (
        driver,
        platform,
        _,
        identity,
        external,
    ):
        assert driver._routes.snapshot(handle) is None
        assert not platform._frames
        assert external.effects == []
        assert archived(host, handle) == receipt


async def test_archive_failure_keeps_live_evidence_and_retry_never_replays_sdk(
    tmp_path,
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        await prepare(driver, identity, handle)
        host.fail_archive = True
        await reconnect(platform)
        effects = list(external.effects)
        with pytest.raises(Exception):
            await finish(driver, identity, handle)
        snapshot = driver._routes.snapshot(handle)
        assert snapshot.cleanup_state.value == "pending"
        assert any(
            handle == row["response_handle"]
            for rows in host.state.values()
            for row in rows
        )
        assert host.receipts.list() == []
        host.fail_archive = False
        await finish(driver, identity, handle)
        assert driver._routes.snapshot(handle) is None
        archived(host, handle)
        assert not platform._frames
        assert external.effects == effects


@pytest.mark.parametrize("failure", ["lost_archive_ack", "live_checkpoint"])
async def test_partial_archive_commit_retry_releases_native_owners(
    tmp_path, failure
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        await prepare(driver, identity, handle)
        await reconnect(platform)
        effects = list(external.effects)
        if failure == "lost_archive_ack":
            host.lose_archive_ack = True
            await finish(driver, identity, handle)
        else:
            host.fail_removal = True
            with pytest.raises(Exception):
                await finish(driver, identity, handle)
            archived(host, handle)
            host.fail_removal = False
            await finish(driver, identity, handle)
        assert driver._routes.snapshot(handle) is None
        assert not platform._frames
        assert not platform._processing
        assert not platform._keepalive_tasks
        assert external.effects == effects


async def test_stale_retirement_waits_for_real_keepalive_owner_and_cancellation(
    tmp_path,
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        await prepare(driver, identity, handle)
        state = platform._processing[handle]
        old = platform._keepalive_tasks[state["stream_id"]]
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
        entered, release = asyncio.Event(), asyncio.Event()

        async def held_effect():
            entered.set()
            await release.wait()

        external.actions.append(held_effect)
        owner = asyncio.create_task(
            platform._keepalive_processing(
                handle,
                driver._route_attrs(handle),
                state,
                interval=0.001,
                max_duration=1,
            )
        )
        platform._keepalive_tasks[state["stream_id"]] = owner
        await asyncio.wait_for(entered.wait(), 1)
        await reconnect(platform)
        task = asyncio.create_task(finish(driver, identity, handle))
        try:
            await asyncio.sleep(0.03)
            assert not task.done()
            assert not owner.done()
            assert handle in platform._frames
            assert platform._keepalive_tasks[state["stream_id"]] is owner
            task.cancel()
            await asyncio.sleep(0.03)
            assert not owner.done()
            assert handle in platform._frames
        finally:
            release.set()
            await asyncio.gather(task, owner, return_exceptions=True)
        await finish(driver, identity, handle)
        assert not platform._frames
        assert not platform._processing
        assert not platform._keepalive_tasks


async def test_current_native_unknown_remains_pending_through_temporary_disconnect(
    tmp_path,
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        external.actions.append(unknown_effect())
        result = await send(driver, identity, handle, "current-unknown")
        assert result["state"] == "unknown"
        with pytest.raises(Exception):
            await finish(driver, identity, handle)
        await platform._state_changed("disconnected", platform._epoch)
        await platform._state_changed("connected", platform._epoch)
        await asyncio.sleep(0.03)
        assert driver._routes.snapshot(handle).cleanup_state.value == "pending"
        assert handle in platform._frames
        assert host.receipts.list() == []


@pytest.mark.parametrize(
    "shape",
    [
        "malformed_epoch",
        "native_less",
        "foreign_response_handle",
        "foreign_route_identity",
    ],
)
async def test_legacy_unknown_route_without_valid_native_proof_is_not_retired(
    tmp_path, shape
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        external.actions.append(unknown_effect())
        assert (await send(driver, identity, handle, "legacy-unknown"))[
            "state"
        ] == "unknown"
        foreign = None
        if shape.startswith("foreign_"):
            foreign = await ingress(driver, host, 1)
            await prepare(driver, identity, foreign)
            foreign_frame = platform._frames[foreign]
            foreign_state = platform._processing[foreign]
            foreign_owner = platform._keepalive_tasks[
                foreign_state["stream_id"]
            ]
        snapshot = driver._routes.snapshot(handle)

        def legacy(ref):
            attrs = dict(ref.attributes)
            resource_id = ref.resource_id
            if ref.kind in {"wecom.route", "wecom.delivery"}:
                if shape == "malformed_epoch":
                    attrs["connection_epoch"] = "not-an-epoch"
                elif shape == "native_less":
                    attrs.pop("frame_token", None)
                    attrs.pop("connection_epoch", None)
                elif ref.kind == "wecom.route":
                    attrs["connection_epoch"] = str(platform._epoch - 1)
                    if shape == "foreign_response_handle":
                        attrs["response_handle"] = foreign
                        attrs["frame_token"] = foreign
                    else:
                        resource_id = foreign
            return ResponseResourceRef.create(ref.kind, resource_id, attrs)

        driver._routes.restore(
            replace(
                snapshot,
                version=snapshot.version + 1,
                route_refs=tuple(sorted(map(legacy, snapshot.route_refs))),
                resource_refs=tuple(
                    sorted(map(legacy, snapshot.resource_refs))
                ),
            )
        )
        await driver._checkpoint()
        with pytest.raises(Exception):
            await finish(driver, identity, handle)
        if foreign is not None:
            assert platform._frames[foreign] == foreign_frame
            assert platform._processing[foreign] is foreign_state
            assert not foreign_owner.done()
        await reconnect(platform)
        await asyncio.sleep(0.03)
        assert driver._routes.snapshot(handle).cleanup_state.value == "pending"
        assert handle in platform._frames
        assert host.receipts.list() == []
        if foreign is not None:
            assert foreign in platform._frames
            assert platform._processing[foreign] is foreign_state
            assert driver._routes.snapshot(foreign).kind.value == "active"


@pytest.mark.parametrize(
    "invalidate_waiter,hold_at",
    [(False, "archive"), (True, "archive"), (False, "state_publication")],
)
async def test_native_admission_waits_for_full_recovery_and_checks_its_generation(
    tmp_path, invalidate_waiter, hold_at
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        for number in range(128):
            handle = await ingress(driver, host, number)
            await prepare(driver, identity, handle)
            driver._routes.begin_finish(handle, ResponseOutcome.FAILED)
        await driver._checkpoint()
        entered, release = asyncio.Event(), asyncio.Event()
        if hold_at == "archive":
            host.archive_gate = entered, release
        else:
            host.connected_gate = entered, release
        recovering = asyncio.create_task(reconnect(platform))
        incoming = None
        try:
            await asyncio.wait_for(entered.wait(), 3)
            before = len(host.batches)
            incoming = asyncio.create_task(ingress(driver, host, 128))
            await asyncio.sleep(0.03)
            assert not incoming.done()
            assert len(host.batches) == before
            if invalidate_waiter:
                platform._epoch += 1
                await platform._state_changed("disconnected", platform._epoch)
        finally:
            release.set()
            await asyncio.gather(recovering, return_exceptions=True)
        if invalidate_waiter:
            results = await asyncio.gather(incoming, return_exceptions=True)
            assert isinstance(results[0], Exception)
            assert len(host.batches) == before
            platform._epoch += 1
            await platform._state_changed("connected", platform._epoch)
            await eventually(lambda: not driver._routes.pending_cleanups())
            await ingress(driver, host, 129)
        else:
            handle = await incoming
            assert (await prepare(driver, identity, handle))[
                "state"
            ] == "acknowledged"


async def test_reconnect_during_cleanup_checkpoint_retires_with_uncertainty_evidence(
    tmp_path,
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        await prepare(driver, identity, handle)
        effects = list(external.effects)
        entered, release = asyncio.Event(), asyncio.Event()
        # First put records finish intent; the second records cleanup intent.
        host.state_gate = 2, entered, release
        finishing = asyncio.create_task(finish(driver, identity, handle))
        reconnecting = None
        try:
            await asyncio.wait_for(entered.wait(), 3)
            reconnecting = asyncio.create_task(reconnect(platform))
            await eventually(
                lambda: driver._connected and platform._epoch == 3
            )
        finally:
            release.set()
        await finishing
        await reconnecting
        receipt = archived(host, handle)
        assert any(
            ref["kind"] == "wecom.attempt"
            and ref["attributes"].get("state") == "unknown"
            for ref in receipt["resource_refs"]
        )
        assert not platform._frames
        assert external.effects == effects


async def test_stale_archive_preserves_settled_audit_and_closed_route_fence(
    tmp_path,
):
    async with worker(tmp_path) as active:
        driver, platform, host, identity, external = active
        handle = await ingress(driver, host)
        created = await send(driver, identity, handle, "settled-start")
        fields = {"target_delivery_id": "not-a-stream", "sequence": 1}
        rejected = await send(
            driver, identity, handle, "settled-delta", "stream.delta", **fields
        )
        assert created["state"] == "acknowledged"
        assert rejected["state"] == "failed"
        await reconnect(platform)
        effects = list(external.effects)
        await finish(driver, identity, handle)
        receipt = archived(host, handle)
        for delivery, result in (
            ("settled-start", created),
            ("settled-delta", rejected),
        ):
            assert any(
                ref["resource_id"] == delivery
                and ref["attributes"].get("state") == result["state"]
                for ref in receipt["resource_refs"]
            )
        for delivery, operation, fields in (
            ("settled-start", "stream.start", {}),
            ("settled-delta", "stream.delta", fields),
        ):
            closed = await send(
                driver, identity, handle, delivery, operation, **fields
            )
            assert closed["state"] == "failed"
            assert closed["reason_code"] == "RESPONSE_CLOSED"
        assert external.effects == effects
