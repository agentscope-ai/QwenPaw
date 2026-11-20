# -*- coding: utf-8 -*-
"""SDK callbacks across real worker restarts and production durable storage."""

import hashlib
import json
import os
import signal
import sys
from pathlib import Path

import pytest
from aiohttp import web

from qwenpaw.__version__ import __version__
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.app.channels.process_supervisor import LaunchSpec
from qwenpaw.channel_protocol.errors import RpcError
from qwenpaw.channel_protocol.response_receipts import (
    ResponseReceiptStore,
    receipt_key,
)
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
from qwenpaw.plugins.channel_workers import ChannelDefinition
from tests.channel_support.process import alive, digest, eventually

SOURCE = """
import json
import os
from urllib.request import Request, urlopen
from qwenpaw.plugins.channel_workers import ChannelDriver, ChannelSendResult, ChannelDeliveryError, ResponsePolicy

class Driver(ChannelDriver):
    response_policy = ResponsePolicy(prepare=True, completion_reaction=True, streaming=True)

    async def start(self, ch):
        starts = await ch.storage.aread_json("starts.json", [])
        starts.append({"pid": os.getpid(), "generation": ch.generation})
        await ch.storage.awrite_json("starts.json", starts)
        await ch.report_status("connected")

    async def effect(self, ch, operation, card, **values):
        body = json.dumps({"operation": operation, "card": card,
            "generation": ch.generation, **values}).encode()
        def post():
            request = Request(ch.config["platform"], data=body, headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=3) as response:
                return json.load(response)
        await ch.resources.run_sync(post)
        return ChannelSendResult(card)

    async def prepare_response(self, ch, response):
        step = await ch.delivery.prepare_step("create-card")
        if step.completed:
            return step.result
        result = await self.effect(ch, "prepare", response.delivery_id)
        await ch.delivery.record_progress(step, result)
        await ch.delivery.record_resource("temporary-card", result)
        return result

    async def send(self, ch, response):
        return await self.effect(ch, "message", "message-one")

    async def on_stream(self, ch, response):
        card = ch.delivery.resources()["temporary-card"].message_id
        if response.operation != "stream.start":
            assert response.previous.message_id == card
        result = await self.effect(ch, response.operation, card,
            sequence=response.sequence, text=response.text)
        scenario = ch.config["scenario"]
        if ((scenario == "unknown-send" and response.operation == "stream.delta")
            or (scenario == "unknown-end" and response.operation == "stream.end")):
            raise ChannelDeliveryError("PLATFORM_ACK_LOST", side_effect_possible=True)
        return result

    async def reaction(self, ch, response):
        assert response.previous.message_id == ch.delivery.resources()["temporary-card"].message_id
        return await self.effect(ch, "reaction", response.previous.message_id)

    async def finish_response(self, ch, target, outcome):
        attempts = await ch.storage.aread_json("cleanup-attempts.json", 0) + 1
        await ch.storage.awrite_json("cleanup-attempts.json", attempts)
        card = ch.delivery.resources()["temporary-card"].message_id
        if attempts == 1:
            raise RuntimeError("Expected local cleanup failure; retry after restart")
        await self.effect(ch, "local-cleanup", card, target=target.key, outcome=outcome)
        await ch.storage.awrite_json("cleaned.json", True)
"""


async def no_model(*args, **kwargs):
    raise AssertionError("This test exercises lifecycle RPC, not a model stub")
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["normal", "unknown-end", "unknown-send"])
async def test_callbacks_recover_with_durable_host_state_and_no_duplicate_effects(
    tmp_path,
    scenario,
):
    effects = []

    async def platform(request):
        effects.append(await request.json())
        return web.json_response({"confirmed": True})

    app = web.Application()
    app.router.add_post("/effect", platform)
    server = web.AppRunner(app)
    await server.setup()
    site = web.TCPSite(server, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    source = tmp_path / "source"
    source.mkdir()
    (source / "driver.py").write_text(SOURCE)
    definition = ChannelDefinition(
        "sdk-recovery",
        {"en": "Recovery", "zh": "恢复"},
        "driver:Driver",
        {"type": "object", "properties": {}},
        (),
        ("channel.generic.v1", "reaction", "response.prepare", "streaming"),
    )
    (source / "channel.json").write_text(json.dumps(definition.to_dict()))
    (source / "requirements.txt").write_text("")
    storage, workspace = tmp_path / "storage", tmp_path / "workspace"
    spec = LaunchSpec(
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        code_root=source,
        descriptor_path=source / "channel.json",
        source_revision=digest(source),
        descriptor=SharedChannelDescriptor.load(source / "channel.json"),
        requirements=(),
        channel_key="sdk-recovery",
        instance_id="recovery-instance",
        generation=1,
        qwenpaw_version=__version__,
        config={
            "platform": f"http://127.0.0.1:{port}/effect",
            "scenario": scenario,
        },
        restart_limit=2,
        restart_backoff=0.02,
        startup_timeout=10,
        shutdown_timeout=5,
        plugin_id="sdk-recovery",
        workspace_id=str(workspace),
        sdk_workspace_id="one",
        sdk_storage_root=storage,
        sdk_media_root=tmp_path / "media",
    )
    proxy = IsolatedChannelProxy(
        no_model,
        launch_spec=spec,
        descriptor=spec.descriptor,
        workspace_dir=workspace,
    )
    process = proxy.channel_process
    pids = []

    async def call(method, values):
        return await process.call(
            method,
            {**proxy._identity().to_mapping(), **values},
        )

    def starts():
        return json.loads((storage / "starts.json").read_text())

    async def crash_and_resume(generation):
        pid = starts()[-1]["pid"]
        pids.append(pid)
        os.kill(pid, signal.SIGKILL)
        await eventually(
            lambda: process.health_snapshot()["generation"] == generation
            and process.health_snapshot()["state"] == "ready"
            and process.health_snapshot()["platform_state"] == "connected",
            timeout=15,
        )
        assert not alive(pid)
        assert starts()[-1]["generation"] == generation

    try:
        await proxy.start()
        handle = (
            await call(
                "channel.response.open",
                {
                    "to_handle": "room",
                    "session_id": "session",
                    "meta": {},
                },
            )
        )["response_handle"]
        prepare = {
            "response_handle": handle,
            "delivery_id": hashlib.sha256(
                (handle + ":prepare").encode(),
            ).hexdigest(),
        }
        assert (await call("channel.response.prepare", prepare))[
            "state"
        ] == "acknowledged"
        first = {
            "delivery_id": "stream-one",
            "to_handle": handle,
            "operation": "stream.start",
            "stream_type": "message",
            "sequence": 0,
            "accumulated_text": "first",
        }
        delta = {
            **first,
            "delivery_id": "delta-one",
            "operation": "stream.delta",
            "target_delivery_id": "stream-one",
            "sequence": 1,
            "accumulated_text": "latest",
        }
        assert (await call("channel.send", first))["state"] == "acknowledged"
        # A reaction targets the confirmed resource and must also survive replay.
        reaction = {
            "delivery_id": "reaction-one",
            "to_handle": handle,
            "target_delivery_id": "stream-one",
            "reaction": "completed",
        }
        assert (await call("channel.reaction", reaction))[
            "state"
        ] == "acknowledged"
        expected_delta = (
            "unknown" if scenario == "unknown-send" else "acknowledged"
        )
        assert (await call("channel.send", delta))["state"] == expected_delta
        before = list(effects)
        await crash_and_resume(2)
        assert (await call("channel.response.prepare", prepare))[
            "state"
        ] == "acknowledged"
        assert (await call("channel.reaction", reaction))[
            "state"
        ] == "acknowledged"
        assert (await call("channel.send", delta))["state"] == expected_delta
        assert effects == before
        with pytest.raises(RpcError):
            await process.call(
                "channel.send",
                {**proxy._identity().to_mapping(), **delta, "generation": 1},
            )
        finish = {"response_handle": handle, "outcome": "cancelled"}
        # Local cleanup failing is not a successful cleanup/archival receipt.
        with pytest.raises(RpcError, match="finish handler failed"):
            await call("channel.response.finish", finish)
        assert json.loads((storage / "cleanup-attempts.json").read_text()) == 1
        assert not (storage / "cleaned.json").exists()
        archive = ResponseReceiptStore(
            proxy._state_path().with_suffix(".receipts.sqlite3"),
        )
        key = receipt_key("sdk.responses.v1", handle)
        assert archive.get(key) is None
        await crash_and_resume(3)
        assert (await call("channel.response.finish", finish))[
            "outcome"
        ] == "cancelled"
        assert json.loads((storage / "cleaned.json").read_text()) is True
        before = list(effects)
        await call("channel.response.finish", finish)
        assert effects == before
        operations = [row["operation"] for row in effects]
        assert operations.count("prepare") == operations.count("reaction") == 1
        assert (
            operations.count("stream.start")
            == operations.count("stream.delta")
            == 1
        )
        assert operations.count("stream.end") == (
            0 if scenario == "unknown-send" else 1
        )
        assert operations.count("local-cleanup") == 1
        if scenario == "normal":
            assert archive.get(key) is None
        else:
            receipt = archive.get(key)
            assert (
                receipt is not None and receipt["cleanup_state"] == "complete"
            )
            assert any(
                dict(ref["attributes"]).get("state") == "unknown"
                for ref in receipt["resource_refs"]
            )
            if scenario == "unknown-send":
                assert (await call("channel.send", delta))[
                    "state"
                ] == "unknown"
                assert effects == before
        assert (
            effects[-1]["generation"] == 3 and effects[-1]["target"] == "room"
        )
        if scenario == "unknown-send":
            # Cross the real 128-live-route bound without discarding any
            # unknown receipt or borrowing the first response's resource.
            for index in range(129):
                fresh = (
                    await call(
                        "channel.response.open",
                        {
                            "to_handle": f"room-{index}",
                            "session_id": f"session-{index}",
                            "meta": {},
                        },
                    )
                )["response_handle"]
                await call(
                    "channel.response.prepare",
                    {
                        "response_handle": fresh,
                        "delivery_id": hashlib.sha256(
                            (fresh + ":prepare").encode(),
                        ).hexdigest(),
                    },
                )
                assert (
                    await call("channel.send", {**first, "to_handle": fresh})
                )["state"] == "acknowledged"
                assert (
                    await call("channel.send", {**delta, "to_handle": fresh})
                )["state"] == "unknown"
                await call(
                    "channel.response.finish",
                    {**finish, "response_handle": fresh},
                )
            receipts = archive.list("sdk.responses.v1", limit=1000)
            assert len(receipts) == 130 and archive.get(key) == receipt
            state = json.loads(proxy._state_path().read_text())
            assert state["sdk.responses.v1"]["value"] == []
            cards = [
                row["card"] for row in effects if row["operation"] == "prepare"
            ]
            assert len(cards) == len(set(cards)) == 130
            assert (
                len(
                    [
                        row
                        for row in effects
                        if row["operation"] == "local-cleanup"
                    ],
                )
                == 130
            )
            before = list(effects)
            assert (await call("channel.send", delta))["state"] == "unknown"
            assert effects == before
    finally:
        if (storage / "starts.json").exists():
            pids.extend(row["pid"] for row in starts())
        await proxy.stop()
        await server.cleanup()
    assert (
        proxy.last_stop_result.exited and not proxy.last_stop_result.residual
    )
    assert all(not alive(pid) for pid in pids)


@pytest.mark.asyncio
async def test_local_cleanup_retains_live_thread_and_pending_route(tmp_path):
    import threading
    from qwenpaw.channel_protocol.models import (
        ResponseFinishParams,
        ResponseOutcome,
    )
    from qwenpaw.channel_protocol.response_lifecycle import (
        ResponseCleanupState,
    )
    from .test_sdk_channel_worker import Driver, setup, open_response

    released, stop_requested = threading.Event(), threading.Event()

    class ThreadCleanup(Driver):
        async def start(self, ch):
            self.scope = ch.resources.child()
            self.thread = self.scope.thread(
                lambda: released.wait(),
                stop=stop_requested,
            )
            await ch.report_status("connected")

        async def finish_response(self, ch, target, outcome):
            await self.scope.close()
            self.finished.append((target, outcome))

    adapter, peer, identity = await setup(tmp_path, ThreadCleanup)
    handle = await open_response(peer, identity)
    params = ResponseFinishParams(
        identity.channel_key,
        identity.instance_id,
        identity.generation,
        handle,
        ResponseOutcome.CANCELLED,
    )
    try:
        with pytest.raises(RpcError, match="finish handler failed"):
            await adapter._finish(params, None)
        assert stop_requested.is_set() and adapter.driver.thread.is_alive()
        assert not adapter.driver.scope.closed and not adapter.driver.finished
        assert (
            adapter._routes.snapshot(handle).cleanup_state
            is ResponseCleanupState.PENDING
        )
        assert (
            peer.receipts.get(receipt_key("sdk.responses.v1", handle)) is None
        )
        released.set()
        adapter.driver.thread.join(2)
        assert not adapter.driver.thread.is_alive()
        await adapter._finish(params, None)
        assert (
            adapter.driver.scope.closed and len(adapter.driver.finished) == 1
        )
        await adapter._finish(params, None)
        assert len(adapter.driver.finished) == 1
    finally:
        released.set()
        adapter.driver.thread.join(2)
        await adapter.stop()
