# -*- coding: utf-8 -*-
"""Public driver callbacks against the actual durable host response engine."""

import asyncio
import json
import re
import threading
from dataclasses import replace

import pytest

from qwenpaw.channel_protocol.models import (
    IdentityParams,
    SendParams,
    ResponseFinishParams,
    ResponseOutcome,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext
from qwenpaw.plugins._channel_worker import prepare_driver
from qwenpaw.plugins.channel_workers import (
    ChannelDriver,
    ChannelSendResult,
    ChannelDeliveryError,
    ReplyTarget,
    ResponsePolicy,
)
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import Attachment, ContentBlock
from qwenpaw.plugins.errors import ResourceError, StaleContextError
from qwenpaw.plugins.errors import SDKAccessError
from tests.channel_support.driver import HostPeer


class Driver(ChannelDriver):
    def __init__(self):
        self.sent, self.finished = [], []

    async def start(self, ch):
        await ch.report_status("connected")

    async def send(self, ch, response):
        self.sent.append(response)
        assert ch.deadline is not None and ch.remaining_timeout() > 0
        if response.text == "never":
            await asyncio.Future()
        return ChannelSendResult("platform-message", {"sent": True})

    async def finish_response(self, ch, target, outcome):
        self.finished.append((target, outcome))


async def setup(
    tmp_path,
    cls=Driver,
    *,
    peer=None,
    capabilities=("channel.generic.v1",),
    generation=1,
):
    peer = peer or HostPeer(tmp_path)
    identity = IdentityParams("example", "worker", generation)
    adapter = prepare_driver(
        cls,
        {
            "plugin_id": "sdk-channel",
            "workspace_id": "trusted-workspace",
            "config": {"workspace_id": "forged"},
            "sdk_storage_root": str(tmp_path / "storage"),
            "sdk_media_root": str(tmp_path / "media"),
        },
    )()
    adapter.bind(DriverContext(peer, identity, capabilities))
    await adapter.start({})
    return adapter, peer, identity


class DeduplicatingPeer(HostPeer):
    def __init__(self, root):
        super().__init__(root)
        self.queued = {}

    async def call(self, name, params):
        if name != "event.batch":
            return await super().call(name, params)
        self.batches.append(params)
        event = params["events"][0]
        key = event["event_id"]
        duplicate = key in self.queued
        if not duplicate:
            self.queued[key] = event
        return {
            "batch_id": params["batch_id"],
            "duplicate_event_ids"
            if duplicate
            else "accepted_event_ids": [
                key,
            ],
        }


@pytest.mark.parametrize(
    "messages",
    [
        (("chat-A", "42"), ("chat-B", "42")),
        (("chat:A", "42"), ("chat", "A:42")),
    ],
)
async def test_message_identity_is_session_scoped_and_restart_stable(
    tmp_path,
    messages,
):
    peer = DeduplicatingPeer(tmp_path)
    adapter, _, _ = await setup(tmp_path, peer=peer)
    handles = []
    try:
        for session, message_id in messages:
            result = await adapter.ch.receive(
                ChannelMessage(
                    "alice",
                    (ContentBlock(text="hello"),),
                    session_id=session,
                    message_id=message_id,
                ),
            )
            assert result.status == "accepted"
            handles.append(result.response_handle)
        assert len(set(handles)) == 2
        assert [
            (event["conversation"]["id"], event["metadata"]["message_id"])
            for event in peer.queued.values()
        ] == list(messages)
        await adapter.stop()
        adapter, _, _ = await setup(tmp_path, peer=peer, generation=2)
        for (session, message_id), handle in zip(messages, handles):
            result = await adapter.ch.receive(
                ChannelMessage(
                    "alice",
                    (ContentBlock(text="hello"),),
                    session_id=session,
                    message_id=message_id,
                ),
            )
            assert (result.status, result.response_handle) == (
                "duplicate",
                handle,
            )
        assert len(peer.queued) == 2
    finally:
        await adapter.stop()


async def test_reply_thread_survives_target_resolution_and_worker_restart(
    tmp_path,
):
    class ThreadDriver(Driver):
        async def resolve_target(self, ch, target):
            return replace(target, key="platform-room")

    adapter, peer, identity = await setup(tmp_path, ThreadDriver)
    try:
        received = await adapter.ch.receive(
            ChannelMessage(
                "alice",
                (ContentBlock(text="hello"),),
                session_id="room",
                message_id="42",
                thread_id="thread-7",
                metadata={"thread_id": "untrusted", "route": "original"},
            ),
        )
        expected = ReplyTarget(
            "platform-room",
            "alice",
            "room",
            {
                "route": "original",
                "thread_id": "thread-7",
                "session_id": "room",
                "user_id": "alice",
                "is_group": False,
                "bot_mentioned": False,
                "debounce_key": "room:alice",
                "message_id": "42",
            },
        )
        for attempt in range(2):
            await adapter._send(
                send_params(
                    identity,
                    received.response_handle,
                    f"send-{attempt}",
                ),
                None,
            )
            assert adapter.driver.sent[-1].target == expected
            if attempt == 0:
                await adapter.stop()
                adapter, _, identity = await setup(
                    tmp_path,
                    ThreadDriver,
                    peer=peer,
                    generation=2,
                )
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_auth_requires_capability_valid_url_and_live_generation(
    tmp_path,
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    adapter, peer, _ = await setup(tmp_path)
    with pytest.raises(ProtocolValidationError):
        await adapter.ch.auth.required("https://example.test/scan")
    await adapter.stop()
    adapter, peer, identity = await setup(
        tmp_path,
        capabilities=("channel.auth.qrcode.v1", "channel.generic.v1"),
    )
    for url in (
        "file:///secret",
        "https://user:password@example.test/scan",
        "javascript:alert(1)",
    ):
        with pytest.raises(ProtocolValidationError):
            await adapter.ch.auth.required(url)
    await adapter.ch.auth.required("https://example.test/scan")
    assert peer.notifications[-1] == (
        "channel.auth.required",
        {**identity.to_mapping(), "scan_url": "https://example.test/scan"},
    )
    await adapter.stop()
    with pytest.raises(StaleContextError):
        await adapter.ch.auth.required("https://example.test/scan")


@pytest.mark.asyncio
async def test_approval_action_uses_host_control_admission_and_typed_results(
    tmp_path,
):
    from qwenpaw.plugins.channel_workers import ChannelApprovalAction

    adapter, peer, identity = await setup(
        tmp_path,
        capabilities=("channel.generic.v1", "send.approval_resolution.v1"),
    )
    message = ChannelMessage(
        "display-user",
        (),
        session_id="group-session",
        message_id="button-one",
        is_group=True,
        mentioned=False,
        acl_sender_id="actual-actor",
        session_scope="group",
    )
    result = await adapter.ch.approvals.resolve(
        ChannelApprovalAction("approval-123", "deny", message),
    )
    assert (
        result.status == "accepted"
    )  # No assertion that an approval was resolved.
    event = peer.batches[-1]["events"][0]
    assert event["acl_sender_id"] == "actual-actor"
    assert event["conversation"]["id"] == "group-session"
    assert event["content_parts"] == [
        {"type": "text", "text": "/deny approval-123"},
    ]
    assert event["metadata"]["has_bot_command"] is True
    assert event["metadata"]["bot_mentioned"] is False
    for request_id in ("--all", "id\n/approve other", "id other"):
        with pytest.raises(ValueError):
            await adapter.ch.approvals.resolve(
                ChannelApprovalAction(request_id, "approve", message),
            )
    from dataclasses import replace

    with pytest.raises(ValueError):
        await adapter.ch.approvals.resolve(
            ChannelApprovalAction(
                "approval-123",
                "approve",
                replace(message, actor_unknown=True),
            ),
        )

    handle = await open_response(peer, identity)
    card = send_params(
        identity,
        handle,
        "card",
        approval={
            "request_id": "approval-123",
            "tool_name": "shell",
            "severity": "high",
        },
    )
    await adapter._send(card, None)
    assert adapter.driver.sent[-1].approval.tool_name == "shell"
    outcome = send_params(
        identity,
        handle,
        "decision",
        approval_resolution={
            "request_id": "approval-123",
            "outcome": "denied",
            "actor_user_id": "actual-actor",
            "tool_name": "shell",
        },
    )
    await adapter._send(outcome, None)
    assert adapter.driver.sent[-1].approval_resolution.outcome == "denied"
    await adapter.stop()
    with pytest.raises(StaleContextError):
        await adapter.ch.approvals.resolve(
            ChannelApprovalAction("approval-123", "deny", message),
        )


async def open_response(peer, identity):
    return (
        await peer.methods["channel.response.open"](
            {
                **identity.to_mapping(),
                "to_handle": "room",
                "meta": {"route": "secret"},
                "session_id": "session",
            },
            None,
        )
    )["response_handle"]


def send_params(identity, handle, delivery="one", **values):
    return SendParams.from_mapping(
        {
            **identity.to_mapping(),
            "delivery_id": delivery,
            "to_handle": handle,
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "hello"}],
            **values,
        },
    )


async def test_concurrent_duplicate_keeps_accepted_reply_open(tmp_path):
    resolving = asyncio.Event()
    release = asyncio.Event()

    class PausedTarget(Driver):
        async def resolve_target(self, ch, target):
            resolving.set()
            await release.wait()
            return target

    adapter, peer, identity = await setup(
        tmp_path,
        PausedTarget,
        peer=DeduplicatingPeer(tmp_path),
    )
    try:
        message = ChannelMessage(
            "alice",
            (ContentBlock(text="hello"),),
            session_id="room",
            message_id="redelivered",
        )
        first = asyncio.create_task(adapter.ch.receive(message))
        await resolving.wait()
        second = asyncio.create_task(adapter.ch.receive(message))
        await asyncio.sleep(0)
        release.set()
        accepted, duplicate = await asyncio.gather(first, second)
        assert accepted.status == "accepted"
        assert duplicate.status == "duplicate"
        assert accepted.response_handle == duplicate.response_handle
        params = send_params(identity, accepted.response_handle)
        result = await peer.methods["channel.send"](params, None)
        assert result["state"] == "acknowledged"
        assert len(adapter.driver.sent) == 1
    finally:
        release.set()
        await adapter.stop()


@pytest.mark.asyncio
async def test_receive_and_send_preserve_identity_media_and_durable_replay(
    tmp_path,
):
    adapter, peer, identity = await setup(tmp_path)
    try:
        assert adapter.ch.workspace_id == "trusted-workspace"
        assert adapter.ch.config["workspace_id"] == "forged"
        result = await adapter.ch.receive(
            ChannelMessage(
                "alice",
                (
                    ContentBlock(text="hello"),
                    ContentBlock(
                        "file",
                        attachment=Attachment(
                            "https://example.invalid/file",
                            "text/plain",
                            "file.txt",
                        ),
                    ),
                ),
                session_id="room",
                message_id="incoming",
                sender_name="Alice",
                thread_id="thread",
            ),
        )
        assert result.status == "accepted"
        event = peer.batches[0]["events"][0]
        assert event["conversation"]["thread_id"] == "thread"
        assert (
            event["sender_name"] == "Alice"
            and event["acl_sender_id"] == "alice"
        )
        assert event["content_parts"][1]["filename"] == "file.txt"
        handle = await open_response(peer, identity)
        params = send_params(identity, handle)
        assert (await peer.methods["channel.send"](params, None))[
            "state"
        ] == "acknowledged"
        assert (await peer.methods["channel.send"](params, None))[
            "state"
        ] == "acknowledged"
        assert len(adapter.driver.sent) == 1
        assert adapter.driver.sent[0].content[0].text == "hello"
        assert adapter.driver.sent[0].target.metadata["route"] == "secret"
        await peer.methods["channel.response.finish"](
            ResponseFinishParams(
                identity.channel_key,
                identity.instance_id,
                identity.generation,
                handle,
                ResponseOutcome.COMPLETED,
            ),
            None,
        )
        assert adapter.driver.finished[0][1] == "completed"
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_stream_previous_resource_and_final_cleanup_are_host_owned(
    tmp_path,
):
    cleanup_resources = []

    class Streaming(Driver):
        async def on_stream(self, ch, response):
            step = await ch.delivery.prepare_step(response.operation)
            self.sent.append(response)
            if response.operation != "stream.start":
                assert response.previous.message_id == "card-1"
            result = ChannelSendResult("card-1")
            await ch.delivery.record_progress(step, result)
            if response.operation == "stream.end":
                await ch.delivery.record_resource("final-card", result)
            return result

        async def finish_response(self, ch, target, outcome):
            cleanup_resources.append(dict(ch.delivery.resources()))
            with pytest.raises(SDKAccessError):
                await ch.delivery.record_resource("late", ChannelSendResult())
            await super().finish_response(ch, target, outcome)

    adapter, peer, identity = await setup(tmp_path, Streaming)
    handle = await open_response(peer, identity)
    try:
        for delivery, operation, sequence, text in (
            ("start", "stream.start", 0, "a"),
            ("delta", "stream.delta", 1, "answer"),
        ):
            values = {
                **identity.to_mapping(),
                "delivery_id": delivery,
                "to_handle": handle,
                "operation": operation,
                "stream_type": "message",
                "sequence": sequence,
                "accumulated_text": text,
            }
            if sequence:
                values["target_delivery_id"] = "start"
            result = await peer.methods["channel.send"](
                SendParams.from_mapping(values),
                None,
            )
            assert result["state"] == "acknowledged"
        finish = ResponseFinishParams(
            identity.channel_key,
            identity.instance_id,
            identity.generation,
            handle,
            ResponseOutcome.CANCELLED,
        )
        for _ in range(2):
            result = await peer.methods["channel.response.finish"](
                finish,
                None,
            )
            assert result["state"] == "closed"
        assert [r.operation for r in adapter.driver.sent] == [
            "stream.start",
            "stream.delta",
            "stream.end",
        ]
        assert (
            adapter.driver.sent[-1].text == "answer"
            and adapter.driver.sent[-1].sequence == 2
        )
        assert adapter.driver.finished[0][1] == "cancelled"
        assert cleanup_resources == [
            {"final-card": ChannelSendResult("card-1")},
        ]
    finally:
        await adapter.stop()
    with pytest.raises((asyncio.CancelledError, StaleContextError)):
        await adapter.ch.receive(
            ChannelMessage("alice", (), session_id="s", message_id="late"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_failure_has_durable_determinate_or_unknown_receipt(
    tmp_path,
    uncertain,
):
    class Failing(Driver):
        async def send(self, ch, response):
            self.sent.append(response)
            raise ChannelDeliveryError(
                "PLATFORM_FAILURE",
                side_effect_possible=uncertain,
            )

    adapter, peer, identity = await setup(tmp_path, Failing)
    handle = await open_response(peer, identity)
    params = send_params(identity, handle)
    try:
        result = await peer.methods["channel.send"](params, None)
        assert result["state"] == ("unknown" if uncertain else "failed")
        # A worker restart must not repeat an uncertain platform effect.
        await adapter.stop()
        adapter, _, _ = await setup(tmp_path, Failing, peer=peer)
        replay = await peer.methods["channel.send"](params, None)
        assert replay["state"] == result["state"]
        assert adapter.driver.sent == []
    finally:
        await adapter.stop()


def test_sdk_driver_probe_validates_without_constructing():
    class Unconstructable(Driver):
        def __init__(self):
            raise AssertionError("Probe must not construct")

    prepare_driver(Unconstructable, {"mode": "probe"})

    class Invalid(Driver):
        def send(self, ch, response):
            return ChannelSendResult()

    with pytest.raises(ValueError, match="send"):
        prepare_driver(Invalid, {"mode": "probe"})
    with pytest.raises(ValueError, match="identity"):
        prepare_driver(Driver, {"config": {"workspace_id": "forged"}})

    for policy, missing in (
        (ResponsePolicy(text_merge_delay_ms=0), "channel.text_merge.v1"),
        (
            ResponsePolicy(content_source="semantic"),
            "send.structured_parts.v1",
        ),
    ):
        Unconstructable.response_policy = policy
        with pytest.raises(ValueError, match=re.escape(missing)):
            prepare_driver(
                Unconstructable,
                {"mode": "probe"},
                capabilities=("channel.generic.v1",),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    ["rejected", "backpressure", "unknown", "duplicate"],
)
async def test_channel_admission_reports_host_result_without_false_acceptance(
    tmp_path,
    state,
):
    class AdmissionPeer(HostPeer):
        async def call(self, name, params):
            if name != "event.batch":
                return await super().call(name, params)
            self.batches.append(params)
            if state == "unknown":
                raise TimeoutError("lost host acknowledgment")
            event = params["events"][0]
            if state == "duplicate":
                return {
                    "batch_id": params["batch_id"],
                    "duplicate_event_ids": [event["event_id"]],
                }
            return {
                "batch_id": params["batch_id"],
                "rejected_events": [
                    {
                        "event_id": event["event_id"],
                        "reason_code": (
                            "INGRESS_BACKPRESSURE"
                            if state == "backpressure"
                            else "ACCESS_DENIED"
                        ),
                        "retryable": state == "backpressure",
                    },
                ],
            }

    peer = AdmissionPeer(tmp_path)
    adapter, _, _ = await setup(tmp_path, peer=peer)
    try:
        result = await adapter.ch.receive(
            ChannelMessage(
                "alice",
                (ContentBlock(text="x"),),
                session_id="s",
                message_id="m",
            ),
        )
        assert result.status == state
        assert result.retryable == (state in {"backpressure", "unknown"})
        assert len(peer.batches) == (5 if result.retryable else 1)
    finally:
        await adapter.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("window", ["resolve", "retry"])
@pytest.mark.parametrize("reconnect", [False, True])
async def test_channel_stops_old_inbound_work_on_disconnect(
    tmp_path,
    window,
    reconnect,
):
    async def disconnect(ch):
        await ch.report_status("disconnected")
        if reconnect:
            await ch.report_status("connected")

    class DisconnectingDriver(Driver):
        async def resolve_target(self, ch, target):
            if window == "resolve" and target.session_id == "old-session":
                await disconnect(ch)
            return target

    class DisconnectingPeer(HostPeer):
        transition = None

        async def call(self, name, params):
            if (
                name == "event.batch"
                and window == "retry"
                and not self.batches
            ):
                self.batches.append(params)
                # Run the transition when the admission loop waits to retry.
                self.transition = asyncio.create_task(disconnect(adapter.ch))
                event_id = params["events"][0]["event_id"]
                return {
                    "batch_id": params["batch_id"],
                    "rejected_events": [
                        {
                            "event_id": event_id,
                            "reason_code": "INGRESS_BACKPRESSURE",
                            "retryable": True,
                        },
                    ],
                }
            return await super().call(name, params)

    peer = DisconnectingPeer(tmp_path)
    adapter, _, _ = await setup(tmp_path, DisconnectingDriver, peer=peer)
    old = ChannelMessage(
        "alice",
        (ContentBlock(text="old message"),),
        session_id="old-session",
        message_id="old",
    )
    try:
        with pytest.raises(RuntimeError, match="STALE_CONNECTION_CALLBACK"):
            await adapter.ch.receive(old)
        attempts = 0 if window == "resolve" else 1
        assert len(peer.batches) == attempts
        if window == "resolve":
            assert not adapter._routes.snapshots()
        if not reconnect:
            with pytest.raises(ValueError, match="NOT_CONNECTED"):
                await adapter.ch.receive(old)
            await adapter.ch.report_status("connected")
        new = replace(old, session_id="new-session", message_id="new")
        result = await adapter.ch.receive(new)
        assert result.status == "accepted"
        assert len(peer.batches) == attempts + 1
        assert peer.batches[-1]["events"][0]["metadata"]["message_id"] == "new"
        if window == "retry":
            first = peer.batches[0]["events"][0]
            assert (await adapter.ch.receive(old)).status == "accepted"
            retried = peer.batches[-1]["events"][0]
            assert retried["event_id"] == first["event_id"]
            assert retried["response_handle"] == first["response_handle"]
    finally:
        if peer.transition is not None:
            await peer.transition
        await adapter.stop()


@pytest.mark.asyncio
async def test_disconnect_invalidates_locally_before_notifying_host(tmp_path):
    notifying, release = asyncio.Event(), asyncio.Event()

    class SlowStatusPeer(HostPeer):
        async def notify(self, name, params):
            if params.get("platform_state") == "disconnected":
                notifying.set()
                await release.wait()
            await super().notify(name, params)

    adapter, peer, _ = await setup(tmp_path, peer=SlowStatusPeer(tmp_path))
    disconnect = asyncio.create_task(adapter.ch.report_status("disconnected"))
    try:
        await asyncio.wait_for(notifying.wait(), 5)
        with pytest.raises(ValueError, match="NOT_CONNECTED"):
            await adapter.ch.receive(
                ChannelMessage(
                    "alice",
                    (),
                    session_id="one",
                    message_id="old",
                ),
            )
        assert not peer.batches
    finally:
        release.set()
        await disconnect
        await adapter.stop()


@pytest.mark.asyncio
async def test_stop_cancels_inflight_effect_and_retains_unknown_receipt(
    tmp_path,
):
    started, exited = asyncio.Event(), asyncio.Event()

    class Pending(Driver):
        async def send(self, ch, response):
            self.sent.append(response)
            started.set()
            try:
                await asyncio.Future()
            finally:
                exited.set()

    adapter, peer, identity = await setup(tmp_path, Pending)
    handle = await open_response(peer, identity)
    params = send_params(identity, handle)
    sending = asyncio.create_task(peer.methods["channel.send"](params, None))
    await asyncio.wait_for(started.wait(), 2)
    await adapter.stop()
    assert exited.is_set() and adapter.ch.resources.closed
    with pytest.raises(asyncio.CancelledError):
        await sending
    adapter, _, _ = await setup(tmp_path, Pending, peer=peer)
    try:
        replay = await peer.methods["channel.send"](params, None)
        assert replay["state"] == "unknown"
        assert adapter.driver.sent == []
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_delivery_steps_persist_before_effect_and_resources_reach_cleanup(
    tmp_path,
):
    effects, cleanup, steps = [], [], []
    peer = HostPeer(tmp_path)

    class MultiStep(Driver):
        async def send(self, ch, response):
            step = await ch.delivery.prepare_step("create-card")
            steps.append(step)
            assert not step.completed
            assert any(
                ref["kind"] == "sdk.step"
                and dict(ref["attributes"])["state"] == "unknown"
                for row in peer.state["sdk.responses.v1"]
                for ref in row["resource_refs"]
            )
            effects.append(step.id)
            result = ChannelSendResult("card-1", {"platform": "example"})
            await ch.delivery.record_progress(step, result)
            await ch.delivery.record_resource("card", result)
            completed = await ch.delivery.prepare_step("create-card")
            assert completed.id == step.id and completed.completed
            assert completed.result.message_id == "card-1"
            with pytest.raises(
                SDKAccessError,
                match="current channel callback",
            ):
                await asyncio.create_task(
                    ch.delivery.prepare_step("background"),
                )
            return result

        async def finish_response(self, ch, target, outcome):
            cleanup.append(ch.delivery.resources()["card"].message_id)

    adapter, _, identity = await setup(tmp_path, MultiStep, peer=peer)
    handle = await open_response(peer, identity)
    try:
        with pytest.raises(SDKAccessError):
            await adapter.ch.delivery.record_progress(
                steps[0] if steps else None,
                ChannelSendResult(),
            )
        result = await peer.methods["channel.send"](
            send_params(identity, handle),
            None,
        )
        assert result["state"] == "acknowledged" and len(effects) == 1
        await peer.methods["channel.response.finish"](
            ResponseFinishParams(
                identity.channel_key,
                identity.instance_id,
                identity.generation,
                handle,
                ResponseOutcome.COMPLETED,
            ),
            None,
        )
        assert cleanup == ["card-1"]
    finally:
        await adapter.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("broken_journal", [False, True])
async def test_unconfirmed_step_cannot_be_reported_as_confirmed(
    tmp_path,
    broken_journal,
):
    effects = []

    class JournalPeer(HostPeer):
        async def call(self, name, params):
            if (
                broken_journal
                and name == "host.state.put"
                and any(
                    ref["kind"] == "sdk.step"
                    for row in params["value"]
                    for ref in row["resource_refs"]
                )
            ):
                raise OSError("journal unavailable")
            return await super().call(name, params)

    class Incomplete(Driver):
        async def send(self, ch, response):
            await ch.delivery.prepare_step("send")
            effects.append("effect")
            # Returning success cannot erase an unfinished durable step.
            return ChannelSendResult("message")

    peer = JournalPeer(tmp_path)
    adapter, _, identity = await setup(tmp_path, Incomplete, peer=peer)
    handle = await open_response(peer, identity)
    try:
        result = await peer.methods["channel.send"](
            send_params(identity, handle),
            None,
        )
        assert result["state"] == "unknown"
        assert effects == ([] if broken_journal else ["effect"])
        if not broken_journal:
            await peer.methods["channel.response.finish"](
                ResponseFinishParams(
                    identity.channel_key,
                    identity.instance_id,
                    identity.generation,
                    handle,
                    ResponseOutcome.FAILED,
                ),
                None,
            )
            from qwenpaw.channel_protocol.response_receipts import receipt_key

            receipt = peer.receipts.get(
                receipt_key("sdk.responses.v1", handle),
            )
            assert any(
                ref["kind"] == "sdk.step" for ref in receipt["resource_refs"]
            )
    finally:
        if broken_journal:
            # The host journal really is unavailable; stop must not claim a completed write.
            with pytest.raises(OSError):
                await adapter.stop()
            assert adapter.ch.resources.closed
        else:
            await adapter.stop()


@pytest.mark.asyncio
async def test_worker_cannot_report_closed_while_cancelled_storage_write_is_running(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import custody

    monkeypatch.setattr(custody, "THREAD_STOP_SECONDS", 0.02)
    entered, release = threading.Event(), threading.Event()
    adapter, _, _ = await setup(tmp_path)
    original = adapter.ch.storage.write_bytes

    def slow_write(name, data):
        entered.set()
        release.wait()
        original(name, data)

    monkeypatch.setattr(adapter.ch.storage, "write_bytes", slow_write)
    writing = asyncio.create_task(
        adapter.ch.storage.awrite_bytes("pending", b"saved"),
    )
    while not entered.is_set():
        await asyncio.sleep(0.01)
    writing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await writing
    try:
        with pytest.raises(ResourceError):
            await adapter.stop()
        assert not adapter.ch.resources.closed
    finally:
        release.set()
        async with asyncio.timeout(2):
            while not (tmp_path / "storage/pending").exists():
                await asyncio.sleep(0.01)
        await adapter.stop()
    assert (tmp_path / "storage/pending").read_bytes() == b"saved"
    with pytest.raises(StaleContextError):
        adapter.ch.storage.read_bytes("pending")
