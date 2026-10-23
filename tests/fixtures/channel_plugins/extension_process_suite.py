# -*- coding: utf-8 -*-
# Pytest fixture injection and real boundary-state checks are intentional.
# pylint: disable=unused-argument
# pylint: disable=redefined-outer-name
# pylint: disable=protected-access
"""G3–G6 proof through normal Loader/Manager and real local process IPC."""

import asyncio
import importlib.abc
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import psutil
import pytest
import pytest_asyncio

from extension_sample import ROOT, sample_source


class SampleImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("sample_chat.", "another_chat.")):
            raise AssertionError(
                "Child Driver/SDK imported in host: " + fullname,
            )


sys.meta_path.insert(0, SampleImportGuard())


async def eventually(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest_asyncio.fixture
# Complete Loader/Manager setup and cleanup remain one bounded fixture.
# pylint: disable-next=too-many-statements
async def runtime(tmp_path, monkeypatch):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
    from qwenpaw.app.task_tracker import TaskTracker
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.schemas import Message, RunStatus, TextContent

    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "host/config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: tmp_path / "installed",
    )
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    workspaces, loaders = [], []

    class Workspace:
        pass

    async def make(
        key="sample_chat",
        capabilities=None,
        capture_ingress=False,
        source_factory=sample_source,
        dependency_paths=(),
        existing_loader=None,
        workspace_name=None,
        python_executable=None,
        runtime_identity=None,
        runtime_settings=None,
        agent_content=None,
        **settings,
    ):
        if existing_loader is None:
            source = source_factory(
                tmp_path / "incoming",
                key,
                capabilities=capabilities,
            )
        loader = existing_loader or PluginLoader(
            [tmp_path / "installed"],
            channel_runtime=ChannelRuntimeSettings(
                python_executable=python_executable or sys.executable,
                runtime_identity=runtime_identity,
                support_root=ROOT / "src",
                qwenpaw_version="2.2.2b4",
                selected_channels=None,
                dependency_paths=dependency_paths,
                startup_timeout=5,
                shutdown_timeout=1,
                **(runtime_settings or {}),
            ),
        )
        if existing_loader is None:
            loader.registry.projector = WorkspaceProjector(
                live_workspaces=lambda: workspaces,
            )
        ws = Workspace()
        ws.agent_id = workspace_name or key
        ws.workspace_dir = tmp_path / ("workspace-" + ws.agent_id)
        ws.workspace_dir.mkdir()
        ws.requests = []
        ws.received = []
        ws._config = Config.model_validate(
            {
                "channels": {
                    key: {
                        "enabled": True,
                        "no_text_debounce": True,
                        **settings,
                    },
                },
            },
        )

        ws.config = ws._config

        async def agent(request):
            ws.requests.append(request)
            yield Message(
                object="message",
                status=RunStatus.Completed,
                role="assistant",
                content=(
                    agent_content
                    if agent_content is not None
                    else [TextContent(text="host answer")]
                ),
            )

        ws.stream_query = agent
        ws.chat_manager = ChatManager(
            repo=JsonChatRepository(ws.workspace_dir / "chats.json"),
        )
        ws.task_tracker = TaskTracker()
        ws.on_last_dispatch = None
        workspaces.append(ws)
        ws.channel_manager = ChannelManager.from_config(
            agent,
            ws._config,
            workspace_dir=ws.workspace_dir,
        )
        ws.channel_manager.set_workspace(ws)
        await ws.channel_manager.start_all()
        if existing_loader is None:
            owner = json.loads((source / "plugin.json").read_text())["id"]
            loaders.append((owner, loader))
            record = await loader.load_plugin_from_path(source)
        else:
            registration = loader.registry.get_channel_registration(key)
            assert registration is not None
            record = loader.get_loaded_plugin(registration.plugin_id)
            await loader.registry.projector.project_workspace(ws)
        assert record.status == "active" and record.enabled, record.diagnostics
        source = record.source_path
        channel = await ws.channel_manager.get_channel(key)
        assert channel is not None
        if capture_ingress:
            from qwenpaw.app.channels.unified_queue_manager import (
                EnqueueResult,
            )

            async def admit(payload):
                ws.received.append(payload)
                return EnqueueResult(True)

            channel.set_enqueue_async(admit)
        return NS(
            key=key,
            loader=loader,
            record=record,
            source=source,
            ws=ws,
            manager=ws.channel_manager,
            channel=channel,
            process=channel.channel_process,
        )

    make.workspaces = workspaces
    yield make
    try:
        for key, loader in reversed(loaders):
            if loader.get_loaded_plugin(key) is not None:
                await loader.unload_plugin(key)
        for ws in workspaces:
            await ws.channel_manager.stop_all()
    finally:
        PluginRegistry._instance = previous


async def inspect(rt):
    return await rt.process.call("fixture.inspect", {})


async def wait_effect(rt, operation):
    async with asyncio.timeout(8):
        while True:
            rows = (await inspect(rt))["effects"]
            if any(row["operation"] == operation for row in rows):
                return rows
            await asyncio.sleep(0.01)


async def emit(rt, **event):
    return await rt.process.call(
        "fixture.emit",
        {"event": {"id": "event-one", **event}},
    )


def identity(rt):
    return {
        "channel_key": rt.key,
        "instance_id": rt.channel._launch_spec.instance_id,
        "generation": rt.process.health_snapshot()["generation"],
    }


async def open_route(rt, room):
    target = rt.channel.to_handle_from_target(
        user_id="member",
        session_id=room,
    )
    result = await rt.process.call(
        "channel.response.open",
        {**identity(rt), "to_handle": target, "meta": {}},
    )
    return result["response_handle"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["sample_chat", "another_chat"])
async def test_named_generic_channel_runs_agent_in_host_and_sdk_in_owned_child(
    runtime,
    key,
):
    rt = await runtime(
        key,
        **(
            {
                "capabilities": ["channel.generic.v1", "media"],
                "rooms": ["room-A"],
            }
            if key == "another_chat"
            else {}
        ),
    )
    ack = await emit(rt)
    assert ack["accepted_event_ids"] == ["event-one"]
    await eventually(lambda: len(rt.ws.requests) == 1)
    await eventually(
        lambda: bool(
            list((rt.ws.workspace_dir / "channel_state").glob("*.json")),
        ),
    )
    request = rt.ws.requests[0]
    assert (
        request.user_id == "group" and request.session_id == "historic-room-A"
    )
    effects = await wait_effect(rt, "finish")
    sends = [row for row in effects if row["operation"] == "message.create"]
    assert len(sends) == 1
    assert sends[0]["content_parts"] == [
        {"type": "text", "text": "host answer"},
    ]
    child = await inspect(rt)
    assert (
        child["pid"]
        == child["sdk_pid"]
        == rt.process.health_snapshot()["pid"]
        != os.getpid()
    )
    assert Path(child["source"]).is_relative_to(rt.source / key)
    assert not any(name.startswith(key + ".") for name in sys.modules)
    pid = child["pid"]
    receipt = await rt.manager.stop_one(key)
    assert receipt.stopped and not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_route_description_is_read_only_and_varies_by_route(runtime):
    rt = await runtime(
        route_policies={
            "room-A": {
                "streaming": True,
                "prepare": False,
                "completion_reaction": True,
            },
            "room-B": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    first, second = await open_route(rt, "room-A"), await open_route(
        rt,
        "room-B",
    )
    before = await inspect(rt)
    for handle, expected in [
        (
            first,
            {"streaming": True, "prepare": False, "completion_reaction": True},
        ),
        (
            second,
            {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        ),
    ]:
        assert (
            await rt.process.call(
                "channel.response.describe",
                {**identity(rt), "response_handle": handle},
            )
            == expected
        )
    after = await inspect(rt)
    assert after["routes"] == before["routes"] and after["effects"] == []


@pytest.mark.asyncio
async def test_proxy_uses_route_policy_despite_platform_extension_fields(
    runtime,
):
    rt = await runtime(
        streaming_enabled=True,
        route_policies={
            "room-A": {
                "streaming": True,
                "prepare": False,
                "completion_reaction": True,
            },
            "room-B": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    for room in ["room-A", "room-B"]:
        handle = await open_route(rt, room)
        meta = {
            "response_handle": handle,
            "feishu_thread_id": "opaque-platform-field",
            "message_type": "markdown",
            "message_id": "opaque",
            "conversation_id": "opaque",
        }
        request = NS(user_id="member", session_id=room, channel_meta=meta)
        await rt.channel._before_consume_process(request)
        await rt.channel.on_streaming_start(
            request,
            handle,
            None,
            meta,
            "message",
        )
        if room == "room-A":
            meta["_last_delivery_id"] = meta["_isolated_streams"]["message"][
                "delivery_id"
            ]
        await rt.channel._on_process_completed(request, handle, meta)
    effects = (await inspect(rt))["effects"]
    assert [(row["room"], row["operation"]) for row in effects] == [
        ("room-A", "stream.start"),
        ("room-A", "reaction"),
        ("room-B", "prepare"),
    ]


@pytest.mark.asyncio
async def test_cron_and_persisted_legacy_target_use_same_durable_route(
    runtime,
):
    rt = await runtime()
    for target in [
        rt.channel.to_handle_from_target(
            user_id="member",
            session_id="room-A",
        ),
        "sample:old:room-B",
    ]:
        await rt.channel.send_content_parts(
            target,
            [{"type": "text", "text": "cron"}],
            {},
        )
    effects = (await inspect(rt))["effects"]
    assert [
        (row.get("room"), row["operation"])
        for row in effects
        if row["operation"] != "finish"
    ] == [
        ("room-A", "message.create"),
        ("room-B", "message.create"),
    ]
    assert len([row for row in effects if row["operation"] == "finish"]) == 2
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    with pytest.raises(ChannelDeliveryError, match="OUTBOUND_TARGET_UNKNOWN"):
        await rt.channel.send_content_parts(
            rt.channel.to_handle_from_target(
                user_id="member",
                session_id="missing",
            ),
            [{"type": "text", "text": "not sent"}],
            {},
        )
    assert (await inspect(rt))["effects"] == effects


@pytest.mark.asyncio
async def test_group_mention_cannot_be_bypassed_by_platform_metadata(runtime):
    rt = await runtime(require_mention=True)
    ack = await emit(rt, bot_mentioned=False, metadata={"is_group": False})
    assert ack["accepted_event_ids"] == []
    assert ack["rejected_events"][0]["reason_code"] == "MENTION_REQUIRED"
    assert rt.ws.requests == []


@pytest.mark.asyncio
async def test_shared_group_acl_records_actor_and_denies_before_preparation(
    runtime,
):
    rt = await runtime(
        access_control_group=True,
        route_policies={
            "room-A": {
                "streaming": True,
                "prepare": True,
                "completion_reaction": True,
            },
        },
    )
    ack = await emit(
        rt,
        shared_admission=True,
        metadata={"is_group": False, "feishu_sender_id": "forged"},
    )
    assert ack["accepted_event_ids"] == []
    effects = await wait_effect(rt, "finish")
    assert rt.ws.requests == []
    pending = rt.channel._get_acl_store().get_all_pending()
    assert [(row["channel"], row["user_id"]) for row in pending] == [
        ("sample_chat", "actor-A"),
    ]
    assert "prepare" not in [row["operation"] for row in effects]


@pytest.mark.asyncio
async def test_generic_prepare_unknown_is_not_replayed_or_reported_success(
    runtime,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await runtime(
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    handle = await open_route(rt, "room-A")
    meta = {"response_handle": handle}
    request = NS(user_id="member", session_id="room-A", channel_meta=meta)
    await rt.process.call("fixture.fault", {"mode": "unknown"})
    for _ in range(2):
        with pytest.raises(ChannelDeliveryError) as caught:
            await rt.channel._before_consume_process(request)
        assert (
            caught.value.state == "unknown"
            and caught.value.side_effect_possible
        )
    assert meta["_reply_unknown"] is True
    assert [row["operation"] for row in (await inspect(rt))["effects"]] == [
        "prepare",
    ]


@pytest.mark.asyncio
async def test_generic_scope_cancellation_finishes_the_original_route(runtime):
    rt = await runtime()
    handle = await open_route(rt, "room-A")
    meta = {"response_handle": handle}
    await rt.process.call("fixture.fault", {"mode": "delay"})

    async def send():
        async with rt.channel._response_scope(meta):
            await rt.channel.send_content_parts(
                handle,
                [{"type": "text", "text": "slow"}],
                meta,
            )

    task = asyncio.create_task(send())
    try:
        await wait_effect(rt, "message.create")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        effects = await wait_effect(rt, "finish")
        finished = [row for row in effects if row["operation"] == "finish"]
        assert len(finished) == 1
        assert (
            finished[0]["outcome"] == "cancelled"
            and finished[0]["response_handle"] == handle
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_generic_rejects_stale_identity_and_foreign_route_before_effects(
    runtime,
):
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime()
    handle = await open_route(rt, "room-A")
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.response.describe",
            {
                **identity(rt),
                "generation": 999,
                "response_handle": handle,
            },
        )
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.response.describe",
            {
                **identity(rt),
                "instance_id": "another-workspace",
                "response_handle": handle,
            },
        )
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.response.describe",
            {
                **identity(rt),
                "response_handle": "sample:reply:foreign",
            },
        )
    ack = await emit(rt, identity={"generation": 999})
    assert ack["accepted_event_ids"] == []
    assert ack["rejected_events"][0]["reason_code"] == "STALE_GENERATION"
    assert (await inspect(rt))["effects"] == [] and rt.ws.requests == []


@pytest.mark.asyncio
async def test_bad_update_keeps_installed_generic_source_and_live_generation(
    runtime,
    tmp_path,
):
    rt = await runtime()
    before = await inspect(rt)
    original = (rt.source / rt.key / "driver.py").read_bytes()
    candidate = sample_source(tmp_path / "update", rt.key)
    path = candidate / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["version"] = "2.0.0"
    path.write_text(json.dumps(manifest))
    with (candidate / rt.key / "driver.py").open("a") as stream:
        stream.write("\nraise RuntimeError('controlled invalid update')\n")
    report = await rt.loader.lifecycle.reload(rt.key, new_source=candidate)
    assert not report.ok and report.errors
    current = await rt.manager.get_channel(rt.key)
    assert current is rt.channel
    after = await inspect(rt)
    assert (
        after["pid"] == before["pid"]
        and after["identity"] == before["identity"]
    )
    assert (rt.source / rt.key / "driver.py").read_bytes() == original
    await emit(rt, id="after-failed-update")
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert (
        len(
            [
                row
                for row in await wait_effect(rt, "finish")
                if row["operation"] == "message.create"
            ],
        )
        == 1
    )


@pytest.mark.asyncio
async def test_config_api_exposes_installed_generic_schema_and_live_process(
    runtime,
    monkeypatch,
):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.app.routers import config as routes

    rt = await runtime(rooms=["room-A", "custom-room"])

    async def get_agent(_request):
        return rt.ws

    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        get_agent,
    )
    app = FastAPI()
    app.state.plugin_loader = rt.loader
    app.include_router(routes.router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/config/channels/schemas")
        assert response.status_code == 200
        row = response.json()[rt.key]
        assert (
            row["form_kind"] == "schema" and row["availability"] == "running"
        )
        assert row["runtime_state"] == "connected"
        fields = {field["name"]: field for field in row["config_fields"]}
        assert fields["route_policies"]["type"] == "json"
        assert fields["route_policies"]["json_type"] == "object"
        response = await client.get("/config/channels/" + rt.key)
        assert response.status_code == 200
        assert response.json()["rooms"] == ["room-A", "custom-room"]


@pytest.mark.asyncio
@pytest.mark.parametrize("capabilities", [["channel.generic.v99"], ["media"]])
async def test_unsupported_third_channel_contract_rejected_before_old_teardown(
    runtime,
    tmp_path,
    capabilities,
):
    rt = await runtime()
    before = await inspect(rt)
    original = (rt.source / "channel.json").read_bytes()
    candidate = sample_source(tmp_path / "update", capabilities=capabilities)
    path = candidate / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["version"] = "2.0.0"
    path.write_text(json.dumps(manifest))
    report = await rt.loader.lifecycle.reload(rt.key, new_source=candidate)
    assert not report.ok and report.errors
    assert await rt.manager.get_channel(rt.key) is rt.channel
    after = await inspect(rt)
    assert (
        after["pid"] == before["pid"]
        and after["identity"] == before["identity"]
    )
    assert (rt.source / "channel.json").read_bytes() == original


@pytest.mark.asyncio
async def test_proxy_reads_policy_once_per_route_across_stream_hooks(runtime):
    rt = await runtime(
        streaming_enabled=True,
        route_policies={
            "room-A": {
                "streaming": True,
                "prepare": False,
                "completion_reaction": False,
            },
            "room-B": {
                "streaming": False,
                "prepare": False,
                "completion_reaction": False,
            },
        },
    )
    first, second = await open_route(rt, "room-A"), await open_route(
        rt,
        "room-B",
    )
    meta = {"response_handle": first}
    request = NS(user_id="member", session_id="room-A", channel_meta=meta)
    await rt.channel._before_consume_process(request)
    await rt.channel.on_streaming_start(request, first, None, meta, "message")
    for text in ["one", "one two", "one two three"]:
        await rt.channel.on_streaming_delta(
            request,
            first,
            None,
            meta,
            "message",
            text,
        )
    await rt.channel.on_streaming_end(
        request,
        first,
        None,
        meta,
        "message",
        "one two three",
    )
    await rt.channel._on_process_completed(request, first, meta)
    evidence = await inspect(rt)
    assert evidence["policy_reads"] == 1
    assert [row["operation"] for row in evidence["effects"]] == [
        "stream.start",
        "stream.delta",
        "stream.delta",
        "stream.delta",
        "stream.end",
    ]
    meta["response_handle"] = second
    await rt.channel._before_consume_process(request)
    await rt.channel.on_streaming_start(request, second, None, meta, "message")
    evidence = await inspect(rt)
    assert evidence["policy_reads"] == 2
    assert len(evidence["effects"]) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capabilities,streaming_enabled,expected",
    [
        (["channel.generic.v1", "media"], True, []),
        (
            [
                "channel.generic.v1",
                "media",
                "reaction",
                "response.prepare",
                "streaming",
            ],
            False,
            ["prepare", "reaction"],
        ),
    ],
)
# Keep the stable pytest selector; only this definition is long.
# pylint: disable-next=line-too-long
async def test_optional_route_operations_are_narrowed_by_static_caps_and_user_stream_switch(  # noqa: E501
    runtime,
    capabilities,
    streaming_enabled,
    expected,
):
    rt = await runtime(
        capabilities=capabilities,
        streaming_enabled=streaming_enabled,
        route_policies={
            "room-A": {
                "streaming": True,
                "prepare": True,
                "completion_reaction": True,
            },
        },
    )
    handle = await open_route(rt, "room-A")
    meta = {"response_handle": handle, "_last_delivery_id": "prior-delivery"}
    request = NS(user_id="member", session_id="room-A", channel_meta=meta)
    await rt.channel._before_consume_process(request)
    await rt.channel.on_streaming_start(request, handle, None, meta, "message")
    await rt.channel._on_process_completed(request, handle, meta)
    assert [
        row["operation"] for row in (await inspect(rt))["effects"]
    ] == expected


@pytest.mark.asyncio
# Keep the stable pytest selector; only this definition is long.
# pylint: disable-next=line-too-long
async def test_generic_definite_prepare_refusal_keeps_failed_diagnostic_and_runs_agent(  # noqa: E501
    runtime,
):
    rt = await runtime(
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    await rt.process.call("fixture.fault", {"mode": "prepare-refused"})
    await emit(rt, id="definite-refusal")
    effects = await wait_effect(rt, "finish")
    assert len(rt.ws.requests) == 1
    assert [row["operation"] for row in effects] == [
        "prepare",
        "message.create",
        "finish",
    ]
    assert effects[1]["content_parts"] == [
        {"type": "text", "text": "host answer"},
    ]
    assert (await rt.channel.health_check())[
        "last_diagnostic"
    ] == "PLATFORM_PREPARE_REFUSED"
    failure = rt.ws.requests[0].channel_meta["_response_prepare_failure"]
    assert failure["result"]["state"] == "failed"
    assert failure["result"]["reason_code"] == "PLATFORM_PREPARE_REFUSED"


@pytest.mark.asyncio
async def test_generic_missing_standard_identity_is_rejected_over_real_ipc(
    runtime,
):
    rt = await runtime()
    ack = await emit(rt, metadata={"session_id": None})
    assert ack["accepted_event_ids"] == []
    assert ack["rejected_events"] == [
        {
            "event_id": "event-one",
            "reason_code": "SCHEMA_MISMATCH",
            "retryable": False,
        },
    ]
    assert rt.ws.requests == [] and (await inspect(rt))["effects"] == []


def durable_snapshot(rt, handle):
    for path in (rt.ws.workspace_dir / "channel_state").glob("*.json"):
        for state in json.loads(path.read_text()).values():
            for row in state["value"]:
                if row["response_handle"] == handle:
                    return row
    raise AssertionError(
        "Response journal missing from actual host state files",
    )


async def captured_control(rt):
    ack = await emit(rt, text="/status")
    assert ack["accepted_event_ids"] == ["event-one"]
    payload = rt.ws.received[0]
    assert rt.channel._command_registry.is_control_command("/status")
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["describe-error", "unknown", "delay"])
async def test_control_consume_finishes_route_after_describe_or_prepare_error(
    runtime,
    fault,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime(
        capture_ingress=True,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    payload = await captured_control(rt)
    handle = payload["meta"]["response_handle"]
    await rt.process.call("fixture.fault", {"mode": fault})
    with pytest.raises((RpcError, ChannelDeliveryError, ChannelCallUnknown)):
        await rt.channel.consume_one(payload)
    evidence = await inspect(rt)
    assert [row["response_handle"] for row in evidence["finish_calls"]] == [
        handle,
    ]
    assert evidence["finish_calls"][0]["outcome"] == "failed"
    assert rt.ws.requests == []
    assert [row["operation"] for row in evidence["effects"]] == (
        ["finish"] if fault == "describe-error" else ["prepare", "finish"]
    )
    snapshot = durable_snapshot(rt, handle)
    assert (
        snapshot["kind"] == "terminal"
        and snapshot["cleanup_state"] == "complete"
    )
    if fault != "describe-error":
        attempts = [
            ref
            for ref in snapshot["resource_refs"]
            if ref["kind"] == "sample.attempt"
        ]
        assert len(attempts) == 1
        assert attempts[0]["attributes"]["state"] == "unknown"
        assert (
            attempts[0]["resource_id"] == evidence["effects"][0]["delivery_id"]
        )


@pytest.mark.asyncio
async def test_control_consume_cancellation_finishes_and_preserves_uncertain_attempt(  # noqa: E501
    runtime,
):
    rt = await runtime(
        capture_ingress=True,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    payload = await captured_control(rt)
    handle = payload["meta"]["response_handle"]
    await rt.process.call("fixture.fault", {"mode": "delay"})
    task = asyncio.create_task(rt.channel.consume_one(payload))
    try:
        await wait_effect(rt, "prepare")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        evidence = await inspect(rt)
        assert [
            row["response_handle"] for row in evidence["finish_calls"]
        ] == [handle]
        assert evidence["finish_calls"][0]["outcome"] == "cancelled"
        assert [row["operation"] for row in evidence["effects"]] == [
            "prepare",
            "finish",
        ]
        assert rt.ws.requests == []
        snapshot = durable_snapshot(rt, handle)
        assert (
            snapshot["kind"] == "terminal"
            and snapshot["cleanup_state"] == "complete"
        )
        attempts = [
            ref
            for ref in snapshot["resource_refs"]
            if ref["kind"] == "sample.attempt"
        ]
        assert len(attempts) == 1
        assert attempts[0]["attributes"]["state"] == "unknown"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_control_consume_acl_records_actor_before_prepare(runtime):
    rt = await runtime(
        capture_ingress=True,
        access_control_group=False,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    payload = await captured_control(rt)
    # The public admission succeeded before policy changed; consume must recheck.
    rt.channel.access_control_group = True
    await rt.channel.consume_one(payload)
    evidence = await inspect(rt)
    assert rt.ws.requests == []
    assert [row["operation"] for row in evidence["effects"]] == [
        "message.create",
        "finish",
    ]
    assert len(evidence["finish_calls"]) == 1
    assert [
        (row["channel"], row["user_id"])
        for row in rt.channel._get_acl_store().get_all_pending()
    ] == [
        ("sample_chat", "actor-A"),
    ]


@pytest.mark.asyncio
async def test_control_consume_retains_definite_prepare_refusal_with_single_finish(  # noqa: E501
    runtime,
):
    rt = await runtime(
        capture_ingress=True,
        route_policies={
            "room-A": {
                "streaming": False,
                "prepare": True,
                "completion_reaction": False,
            },
        },
    )
    payload = await captured_control(rt)
    await rt.process.call("fixture.fault", {"mode": "prepare-refused"})
    await rt.channel.consume_one(payload)
    evidence = await inspect(rt)
    assert len(rt.ws.requests) == 1 and len(evidence["finish_calls"]) == 1
    assert [row["operation"] for row in evidence["effects"]] == [
        "prepare",
        "message.create",
        "finish",
    ]
    assert (await rt.channel.health_check())[
        "last_diagnostic"
    ] == "PLATFORM_PREPARE_REFUSED"
    failure = rt.ws.requests[0].channel_meta["_response_prepare_failure"]
    assert failure["result"]["state"] == "failed"


@pytest.mark.asyncio
async def test_actual_consume_buffers_media_route_until_text_without_early_finish(  # noqa: E501
    runtime,
):
    rt = await runtime(capture_ingress=True, no_text_debounce=True)
    await emit(
        rt,
        id="media-first",
        content_parts=[
            {
                "type": "image",
                "image_url": "https://fixture.invalid/image",
            },
        ],
    )
    media = rt.ws.received[0]
    first_handle = media["meta"]["response_handle"]
    await rt.channel.consume_one(media)
    evidence = await inspect(rt)
    assert evidence["finish_calls"] == [] and evidence["policy_reads"] == 0
    assert rt.ws.requests == []
    assert durable_snapshot(rt, first_handle)["kind"] == "active"
    await emit(rt, id="text-followup", text="/status")
    text = rt.ws.received[1]
    second_handle = text["meta"]["response_handle"]
    await rt.channel.consume_one(text)
    evidence = await inspect(rt)
    assert len(rt.ws.requests) == 1
    assert [part.type for part in rt.ws.requests[0].input[0].content] == [
        "image",
        "text",
    ]
    assert len(evidence["finish_calls"]) == 2
    assert {row["response_handle"] for row in evidence["finish_calls"]} == {
        first_handle,
        second_handle,
    }
    assert all(
        row["outcome"] == "completed" for row in evidence["finish_calls"]
    )
    assert all(
        durable_snapshot(rt, handle)["kind"] == "terminal"
        for handle in [first_handle, second_handle]
    )
