# -*- coding: utf-8 -*-
"""Native worker boundary checks supplement the real Runtime/channel scenarios."""

import asyncio
import json
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels import isolated_proxy
from qwenpaw.channel_protocol.errors import RpcError
from qwenpaw.channel_protocol.models import (
    ResponseFinishParams,
    ResponseOutcome,
)
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.errors import ResourceError, SDKAccessError
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.channel_workers import ChannelDefinition, ReplyTarget
from qwenpaw.plugins.testing import PluginTestHost
from tests.channel_support.sdk import make_channel, workspace_store
from tests.channel_support.process import alive, eventually
from .sdk_author_fixture import make_plugin
from .test_sdk_channel_policy import MODEL, DRIVER
from .test_sdk_channel_worker import Driver, send_params, setup


class Observer(Driver):
    def __init__(self):
        super().__init__()
        self.events = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.wait_start = False
        self.stopped = False
        self.remap_target = False
        self.fail_notifications = False

    async def resolve_target(self, ch, target):
        return ReplyTarget("platform-address") if self.remap_target else target

    async def on_run(self, ch, event):
        with pytest.raises(SDKAccessError):
            await ch.delivery.prepare_step("not-a-delivery")
        self.events.append(event)
        if event.phase == "start" and self.wait_start:
            self.entered.set()
            await self.release.wait()
        if self.fail_notifications:
            raise RuntimeError("Expected notification failure")

    async def stop(self, ch):
        self.stopped = True


@pytest.mark.parametrize("cancel_request", [False, True])
async def test_pending_end_has_total_deadline_and_retains_cleanup(
    tmp_path,
    monkeypatch,
    cancel_request,
):
    class HungEnd(Observer):
        async def on_run(self, ch, event):
            self.events.append(event)
            if event.phase == "end":
                self.entered.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    await self.release.wait()
                    raise

    adapter, peer, identity = await setup(
        tmp_path,
        HungEnd,
        capabilities=("channel.generic.v1", "channel.run_events.v1"),
    )
    params = await run_params(adapter, identity)
    assert await peer.methods["channel.run.event"](params, None) == {
        "status": "complete",
    }
    outcome = "cancelled" if cancel_request else "completed"
    ending = asyncio.create_task(
        peer.methods["channel.run.event"](
            {**params, "phase": "end", "status": outcome},
            None,
        ),
    )
    await asyncio.wait_for(adapter.driver.entered.wait(), 2)
    end = adapter.runs.runs[params["response_handle"]]["end"]
    end.cancel()
    await asyncio.sleep(0)

    diagnostics, polls = [], []

    async def rpc(method, values, **kwargs):
        if method == "channel.run.event" and not end.done():
            polls.append(values)
            return {"status": "pending"}
        if method == "channel.response.finish":
            values = ResponseFinishParams.from_mapping(values)
        return await peer.methods[method](values, None)

    proxy = object.__new__(isolated_proxy.IsolatedChannelProxy)
    proxy.channel_process = SimpleNamespace(call=rpc)
    proxy._identity = lambda: identity
    proxy._record_diagnostic = diagnostics.append
    proxy._text_merge = {}
    proxy._response_context = ContextVar("test_response_scope", default=None)
    monkeypatch.setattr(isolated_proxy, "_RUN_NOTIFICATION_TIMEOUT", 0.12)
    cycle = {
        key: value
        for key, value in params.items()
        if key not in {*identity.to_mapping(), "phase", "status"}
    }
    meta = {"response_handle": params["response_handle"]}

    async def request():
        async with proxy._response_scope(meta):
            proxy._response_context.get()["run"] = cycle
            if cancel_request:
                raise asyncio.CancelledError

    running = asyncio.create_task(request())
    try:
        async with asyncio.timeout(1):
            while not polls:
                await asyncio.sleep(0)
            if cancel_request:
                running.cancel()
                await asyncio.sleep(0.02)
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.shield(running)
            else:
                await asyncio.shield(running)
        assert diagnostics == [
            "RUN_NOTIFICATION_PENDING",
            "RESPONSE_FINISH_FAILED",
        ]
        assert not end.done()
        assert (
            adapter._routes.snapshot(
                params["response_handle"],
            ).cleanup_state
            == "pending"
        )
        assert adapter.driver.finished == []

        adapter.driver.release.set()
        await ending
        await proxy._finish_cycle(meta, outcome)
        assert adapter.runs.runs == {}
        assert [
            (event.phase, event.status) for event in adapter.driver.events
        ] == [
            ("start", "running"),
            ("end", outcome),
        ]
        assert [
            (target.key, status) for target, status in adapter.driver.finished
        ] == [("room", outcome)]
    finally:
        adapter.driver.release.set()
        await asyncio.gather(running, ending, return_exceptions=True)
        await adapter.stop()


async def run_params(adapter, identity):
    received = await adapter.ch.receive(
        ChannelMessage(
            "alice",
            (ContentBlock(text="hello"),),
            session_id="room",
            message_id="one",
        ),
    )
    return {
        **identity.to_mapping(),
        "response_handle": received.response_handle,
        "phase": "start",
        "status": "running",
        "run_id": "cycle-one",
        "session_id": "room",
        "user_id": "alice",
        "sender_id": "alice",
        "acl_sender_id": "alice",
        "message_ids": ["one"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("remap_target", [False, True])
async def test_event_validation_identity_and_idempotent_callbacks(
    tmp_path,
    remap_target,
):
    adapter, peer, identity = await setup(
        tmp_path,
        Observer,
        capabilities=("channel.generic.v1", "channel.run_events.v1"),
    )
    call = peer.methods["channel.run.event"]
    adapter.driver.remap_target = remap_target
    adapter.driver.fail_notifications = remap_target
    accepted = {"status": "failed" if remap_target else "complete"}
    params = await run_params(adapter, identity)
    try:
        for change in (
            {"phase": "end", "status": "completed"},
            {"message_ids": [7]},
            {"phase": "finish"},
            {"status": "cancelled"},
            {"user_id": "bob"},
            {"session_id": "other"},
            {"extra": True},
        ):
            with pytest.raises(ValueError):
                await call({**params, **change}, None)
        with pytest.raises(RpcError):
            await call({**params, "generation": identity.generation + 1}, None)
        assert not adapter.driver.events
        assert await call(params, None) == accepted
        assert await call(params, None) == accepted
        with pytest.raises(ValueError, match="RUN_IDENTITY_MISMATCH"):
            await call({**params, "sender_id": "bob"}, None)
        delivery = await peer.methods["channel.send"](
            send_params(identity, params["response_handle"]),
            None,
        )
        assert delivery["state"] == "acknowledged"
        end = {**params, "phase": "end", "status": "completed"}
        assert await call(end, None) == accepted
        assert await call(end, None) == accepted
        with pytest.raises(ValueError, match="RUN_OUTCOME_CONFLICT"):
            await call({**end, "status": "failed"}, None)
        assert [event.phase for event in adapter.driver.events] == [
            "start",
            "end",
        ]
        assert all(
            event.target == ("platform-address" if remap_target else "room")
            and event.user_id == "alice"
            for event in adapter.driver.events
        )
        await adapter._finish(
            ResponseFinishParams(
                identity.channel_key,
                identity.instance_id,
                identity.generation,
                params["response_handle"],
                ResponseOutcome.COMPLETED,
            ),
            None,
        )
        assert [
            (target.key, outcome)
            for target, outcome in adapter.driver.finished
        ] == [
            ("platform-address" if remap_target else "room", "completed"),
        ]
        assert not adapter.runs.runs
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_no_capability_does_not_deliver_run_notification(tmp_path):
    adapter, peer, identity = await setup(tmp_path, Observer)
    try:
        with pytest.raises(ValueError, match="RUN_EVENTS_CAPABILITY_REQUIRED"):
            await peer.methods["channel.run.event"](
                await run_params(adapter, identity),
                None,
            )
        assert not adapter.driver.events
    finally:
        await adapter.stop()


async def test_cancelled_end_notification_retires_without_duplicate_callback(
    tmp_path,
):
    class CancelledEnd(Observer):
        async def on_run(self, ch, event):
            await super().on_run(ch, event)
            if event.phase == "end":
                raise asyncio.CancelledError

    adapter, peer, identity = await setup(
        tmp_path,
        CancelledEnd,
        capabilities=("channel.generic.v1", "channel.run_events.v1"),
    )
    try:
        call = peer.methods["channel.run.event"]
        params = await run_params(adapter, identity)
        assert await call(params, None) == {"status": "complete"}
        end = {**params, "phase": "end", "status": "completed"}
        assert await call(end, None) == {"status": "failed"}
        assert await call(end, None) == {"status": "failed"}
        await adapter._finish(
            ResponseFinishParams(
                identity.channel_key,
                identity.instance_id,
                identity.generation,
                params["response_handle"],
                ResponseOutcome.COMPLETED,
            ),
            None,
        )
        assert [event.phase for event in adapter.driver.events] == [
            "start",
            "end",
        ]
        assert [
            (target.key, outcome)
            for target, outcome in adapter.driver.finished
        ] == [("room", "completed")]
        assert adapter.runs.runs == {}
    finally:
        await adapter.stop()


async def test_cancelled_end_keeps_live_start_notification_owned(tmp_path):
    adapter, peer, identity = await setup(
        tmp_path,
        Observer,
        capabilities=("channel.generic.v1", "channel.run_events.v1"),
    )
    adapter.driver.wait_start = True
    params = await run_params(adapter, identity)
    call = peer.methods["channel.run.event"]
    starting = asyncio.create_task(call(params, None))
    ending = None
    try:
        await asyncio.wait_for(adapter.driver.entered.wait(), 2)
        ending = asyncio.create_task(
            call({**params, "phase": "end", "status": "completed"}, None),
        )
        state = adapter.runs.runs[params["response_handle"]]
        async with asyncio.timeout(2):
            while "end" not in state:
                await asyncio.sleep(0)
        state["end"].cancel()
        assert await ending == {"status": "failed"}
        with pytest.raises(ResourceError, match="RUN_NOTIFICATION_PENDING"):
            adapter.runs.require_finished(params["response_handle"])
        adapter.driver.release.set()
        assert await starting == {"status": "complete"}
        adapter.runs.release(params["response_handle"])
        assert adapter.runs.runs == {}
    finally:
        adapter.driver.release.set()
        await asyncio.gather(
            *(task for task in (starting, ending) if task),
            return_exceptions=True,
        )
        await adapter.stop()


@pytest.mark.asyncio
async def test_cancelled_rpc_keeps_start_owned_and_end_before_transport_stop(
    tmp_path,
):
    adapter, peer, identity = await setup(
        tmp_path,
        Observer,
        capabilities=("channel.generic.v1", "channel.run_events.v1"),
    )
    adapter.driver.wait_start = True
    params = await run_params(adapter, identity)
    call = peer.methods["channel.run.event"]
    starting = asyncio.create_task(call(params, None))
    ending = stopping = None
    try:
        await asyncio.wait_for(adapter.driver.entered.wait(), 2)
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        ending = asyncio.create_task(
            call({**params, "phase": "end", "status": "cancelled"}, None),
        )
        await asyncio.sleep(0.05)
        with pytest.raises(RpcError, match="response finish handler failed"):
            await adapter._finish(
                ResponseFinishParams(
                    identity.channel_key,
                    identity.instance_id,
                    identity.generation,
                    params["response_handle"],
                    ResponseOutcome.CANCELLED,
                ),
                None,
            )
        assert (
            adapter._routes.snapshot(params["response_handle"]).cleanup_state
            == "pending"
        )
        stopping = asyncio.create_task(adapter.stop())
        await asyncio.sleep(0.05)
        assert not stopping.done() and not adapter.driver.stopped
        assert [event.phase for event in adapter.driver.events] == ["start"]
    finally:
        adapter.driver.release.set()
        await asyncio.gather(
            *(task for task in (starting, ending) if task),
            return_exceptions=True,
        )
        if stopping:
            await stopping
        else:
            await adapter.stop()
    assert [event.phase for event in adapter.driver.events] == ["start", "end"]
    assert adapter.driver.stopped


@pytest.mark.asyncio
async def test_real_workers_keep_concurrent_workspace_and_user_events_separate(
    tmp_path,
):
    key = "sdk-runs"
    source = tmp_path / "channel"
    make_channel(
        source,
        DRIVER.replace("DELAY", "None").replace("CONTINUE", "False"),
        ChannelDefinition(
            key,
            {"en": "Runs", "zh": "运行事件"},
            "driver:Driver",
            {"type": "object", "properties": {}},
            (),
            ("channel.generic.v1", "channel.run_events.v1"),
        ),
        capabilities=["channels", "storage"],
    )
    provider = make_plugin(
        tmp_path,
        MODEL,
        ["providers", "storage", "tools"],
        sdk_version="1.2.0",
    )
    root = tmp_path / "host"
    async with PluginTestHost(root, process_channels=(key,)) as host:
        assert (await host.install(source)).ok
        await host.load(provider)
        owners = (("one", "alice"), ("two", "bob"))
        stores = {}
        for workspace, _ in owners:
            await host.configure_chat_model(
                "policy-model",
                "model",
                workspace_id=workspace,
            )
            await host.start_channel(
                key,
                {"manual": True},
                workspace_id=workspace,
            )
            stores[workspace] = workspace_store(root, key, workspace)
        await asyncio.gather(
            *(
                host.send_channel(
                    key,
                    "request-start:"
                    + json.dumps(
                        {
                            "user": user,
                            "session": "room",
                            "message": "incoming-" + user,
                            "group": workspace == "one",
                        },
                    ),
                    workspace_id=workspace,
                    user_id=user,
                    session_id="room",
                )
                for workspace, user in owners
            ),
        )
        run_ids, pids = set(), []
        for workspace, user in owners:
            store = stores[workspace]
            await eventually(
                lambda: (store / "runs.json").exists()
                and len(json.loads((store / "runs.json").read_text())) == 2,
                timeout=15,
            )
            events = json.loads((store / "runs.json").read_text())
            assert [(event["phase"], event["status"]) for event in events] == [
                ("start", "running"),
                ("end", "completed"),
            ]
            assert events[0]["id"] == events[1]["id"]
            assert all(
                event["workspace"] == workspace
                and event["user"] == ("group" if workspace == "one" else user)
                and event["sender"] == event["acl"] == user
                and event["messages"] == ["incoming-" + user]
                and event["session"] == event["target"] == "room"
                for event in events
            )
            run_ids.add(events[0]["id"])
            pids.append(json.loads((store / "pid.json").read_text()))
        assert len(run_ids) == len(set(pids)) == 2
        assert (await host.uninstall(key)).quiescent
        assert all(not alive(pid) for pid in pids)
