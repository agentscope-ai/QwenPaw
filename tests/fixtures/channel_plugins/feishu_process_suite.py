# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""B3 real host/child contracts; only the external SDK/network is
controlled.
"""

import asyncio
from dataclasses import replace
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN = (
    "lark_oapi",
    "qwenpaw.app.channels.feishu",
    "plugin_feishu",
    "feishu.platform",
    "feishu.channel",
    "feishu.driver",
    "_qwenpaw_shared_driver.platform",
)


class ParentPlatformGuard(importlib.abc.MetaPathFinder):
    """A caught ImportError cannot hide an attempted host SDK import."""

    def find_spec(self, fullname, _path=None, _target=None):
        if any(
            fullname == name or fullname.startswith(name + ".")
            for name in FORBIDDEN
        ):
            raise AssertionError(f"Platform imported in host: {fullname}")


sys.meta_path.insert(0, ParentPlatformGuard())


def digest(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name, data = (
                path.relative_to(root).as_posix().encode(),
                path.read_bytes(),
            )
            result.update(len(name).to_bytes(8, "big"))
            result.update(name)
            result.update(len(data).to_bytes(8, "big"))
            result.update(data)
    return result.hexdigest()


async def eventually(predicate, timeout=6):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def restart(rt):
    generation = rt.process.health_snapshot()["generation"]
    await rt.process.stop()
    rt.spec = replace(rt.spec, generation=generation + 1)
    await rt.process.start(rt.spec)
    async with asyncio.timeout(6):
        while (await rt.channel.health_check()).get(
            "platform_state",
        ) != "connected":
            await asyncio.sleep(0.01)


def message(
    mid,
    *,
    sender="ou_alice",
    group=False,
    mentioned=False,
    thread="",
    kind="text",
    content=None,
    **header,
):
    return {
        "header": {"event_id": mid, **header},
        "event": {
            "sender": {"sender_id": {"open_id": sender}, "name": "Alice"},
            "message": {
                "message_id": mid,
                "chat_id": "oc_room",
                "chat_type": "group" if group else "p2p",
                "thread_id": thread,
                "message_type": kind,
                "content": json.dumps(
                    content
                    or {"text": "@_user_1 hello" if mentioned else "hello"},
                ),
                "mentions": (
                    [{"id": {"open_id": "ou_bot"}, "key": "@_user_1"}]
                    if mentioned
                    else []
                ),
            },
        },
    }


def set_admission(channel, callback):
    """Adapt the direct-proxy fixture to acknowledged local admission."""
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult

    async def admit(payload):
        callback(payload)
        return EnqueueResult(True)

    channel.set_enqueue_async(admit)


@pytest.fixture
def proxy_api():
    name = "qwenpaw.app.channels.isolated_proxy"
    assert importlib.util.find_spec(name), "B3 IsolatedChannelProxy is missing"
    api = importlib.import_module(name)
    assert hasattr(
        api,
        "IsolatedChannelProxy",
    ), "B3 host proxy class is missing"
    return api.IsolatedChannelProxy


@pytest_asyncio.fixture
async def runtime(proxy_api, tmp_path):
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        LaunchSpec,
    )
    from qwenpaw.schemas import Message, RunStatus, TextContent

    owned = []

    async def make(agent=None, **settings):
        index = len(owned)
        work = tmp_path / f"work-{index}"
        work.mkdir()
        code = tmp_path / f"code-{index}"
        plugin = code / "feishu"
        shutil.copytree(
            ROOT / "plugins/channel/feishu",
            code,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        fixture = Path(__file__).with_name("feishu_process_boundary.py")
        (plugin / "boundary.py").write_text(
            f"WORK = {str(work)!r}\n" + fixture.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        descriptor = json.loads((code / "channel.json").read_text())
        descriptor["entrypoint"]["module"] = "feishu.boundary"
        (code / "channel.json").write_text(json.dumps(descriptor))
        config = {
            "enabled": True,
            "app_id": "cli_test",
            "app_secret": "test-only",
            "no_text_debounce": False,
            "media_dir": str(work / "media"),
            **settings,
        }
        spec = LaunchSpec(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            code_root=code,
            descriptor_path=code / "channel.json",
            source_revision=digest(code),
            channel_key="feishu",
            instance_id=f"workspace-{index}",
            generation=1,
            qwenpaw_version="2.2.2b4",
            config=config,
            # Real lark-oapi startup took 3.8s on the diagnostic host.
            # Leave headroom for cold imports; explicit hang tests stay sharp.
            startup_timeout=8,
            shutdown_timeout=0.8,
        )
        requests, queued, pids = [], [], []

        async def default_agent(request):
            requests.append(request)
            pids.append(os.getpid())
            yield Message(
                object="message",
                status=RunStatus.Completed,
                role="assistant",
                content=[TextContent(text="host answer")],
            )

        process = ChannelProcess()
        channel = proxy_api(
            agent or default_agent,
            launch_spec=spec,
            channel_process=process,
            workspace_dir=work,
        )
        owned.append(channel)
        set_admission(channel, queued.append)
        rt = NS(
            channel=channel,
            process=process,
            spec=spec,
            work=work,
            requests=requests,
            queued=queued,
            pids=pids,
        )

        def rows(kind=None):
            path = work / "ledger.jsonl"
            records = (
                [json.loads(line) for line in path.read_text().splitlines()]
                if path.exists()
                else []
            )
            return [r for r in records if kind is None or r["kind"] == kind]

        def emit(event, kind="message"):
            with (work / "inbox.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"kind": kind, "value": event}) + "\n")

        rt.rows, rt.emit = rows, emit
        await channel.start()
        await eventually(lambda: rows("connected"))
        async with asyncio.timeout(6):
            while (await channel.health_check()).get(
                "platform_state",
            ) != "connected":
                await asyncio.sleep(0.01)
        return rt

    yield make
    for channel in reversed(owned):
        await asyncio.wait_for(channel.stop(), 5)


@pytest.mark.asyncio
async def test_native_message_runs_host_agent_and_sends_from_real_child(
    runtime,
):
    """Moving Agent/ACL to the child or bypassing the real wire breaks this."""
    from qwenpaw.app.channels.base import BaseChannel
    from qwenpaw.plugins.execution.process import PluginProcess

    rt = await runtime()
    rt.emit(message("dm-1"))
    await eventually(lambda: rt.queued)
    await rt.channel.consume_one(rt.queued.pop())
    sent = rt.rows("create")
    assert isinstance(rt.channel, BaseChannel)
    assert isinstance(rt.process, PluginProcess)
    assert rt.pids == [os.getpid()]
    assert rt.requests[0].user_id == "ou_alice"
    assert rt.requests[0].input[0].content[0].text == "hello"
    assert len(sent) == 1
    assert sent[0]["pid"] != os.getpid()
    assert sent[0]["receive_id"] == "ou_alice"
    assert (
        json.loads(sent[0]["content"])["zh_cn"]["content"][0][0]["text"]
        == "host answer"
    )
    assert not any(
        n == p or n.startswith(p + ".") for n in sys.modules for p in FORBIDDEN
    )


def post_text(row):
    return json.loads(row["content"])["zh_cn"]["content"][0][0]["text"]


async def inbound(rt, event, kind="message"):
    count = len(rt.queued)
    rt.emit(event, kind)
    await eventually(lambda: len(rt.queued) > count)
    return rt.queued[-1]


@pytest.mark.asyncio
async def test_native_filters_group_mention_self_app_and_stale_events(runtime):
    """Wrong mention or SDK callback identity handling leaks forbidden
    events.
    """
    rt = await runtime(require_mention=True)
    for event in [
        message("unmentioned", group=True),
        message("self", sender="ou_bot"),
        message("other-app", app_id="cli_other"),
        message("stale", create_time="1"),
    ]:
        rt.emit(event)
    accepted = await inbound(
        rt,
        message("mentioned", group=True, mentioned=True),
    )
    assert [p["meta"]["feishu_message_id"] for p in rt.queued] == ["mentioned"]
    assert accepted["acl_sender_id"] == "ou_alice"
    assert (
        rt.channel.build_agent_request_from_native(accepted)
        .input[0]
        .content[0]
        .text
        == "hello"
    )


@pytest.mark.asyncio
async def test_host_acl_checks_real_sender_before_agent_for_shared_group(
    runtime,
    monkeypatch,
):
    """Synthetic shared user IDs must never replace the ACL principal."""
    rt = await runtime(access_control_group=True, share_session_in_group=True)
    from qwenpaw.app.channels.access_control import AccessControlStore

    checks = []
    store = AccessControlStore(rt.work / "acl.json")
    original_whitelist = store.is_whitelisted

    def checked_whitelist(channel, sender):
        checks.append((channel, sender))
        return original_whitelist(channel, sender)

    monkeypatch.setattr(store, "is_whitelisted", checked_whitelist)
    monkeypatch.setattr(
        "qwenpaw.app.channels.base.get_access_control_store",
        lambda *_a, **_k: store,
    )
    rt.emit(message("acl", group=True))
    await eventually(lambda: len(rt.rows("create")) == 1)
    assert checks == [("feishu", "ou_alice")]
    assert rt.requests == rt.queued == []
    assert [
        (row["channel"], row["user_id"]) for row in store.get_all_pending()
    ] == [("feishu", "ou_alice")]
    assert len(rt.rows("create")) == 1
    assert rt.rows("create")[0]["receive_id"] == "oc_room"
    store.add_to_whitelist("feishu", "ou_alice")
    payload = await inbound(rt, message("authorized-shared", group=True))
    assert (
        rt.channel.build_agent_request_from_native(payload).user_id == "group"
    )
    assert rt.requests == []


@pytest.mark.asyncio
async def test_rejected_admission_retries_and_concurrent_duplicate_is_once(
    runtime,
):
    """Dedup before successful host enqueue loses a retried native callback."""
    rt = await runtime()
    attempts = []

    def accept(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise RuntimeError("host queue temporarily unavailable")
        rt.queued.append(payload)

    set_admission(rt.channel, accept)
    event = message("same-id")
    rt.emit(event)
    await eventually(lambda: len(attempts) == 1)
    # Ensure the negative acknowledgement has reached the child before retry.
    await asyncio.sleep(0.1)
    for _ in range(4):
        rt.emit(event)
    await eventually(lambda: len(rt.queued) == 1)
    await eventually(lambda: len(rt.rows("callback")) == 5)
    await asyncio.sleep(0.1)
    assert len(attempts) == 2
    assert len(rt.queued) == 1


@pytest.mark.asyncio
async def test_proactive_send_reads_both_old_receive_store_orders(runtime):
    """Swapping legacy tuple order sends scheduled messages to the wrong ID."""
    rt = await runtime(bot_prefix="[bot]")
    (rt.work / "feishu_receive_ids.json").write_text(
        json.dumps(
            {"old": ["ou_old", "open_id"], "new": ["chat_id", "oc_new"]},
        ),
    )
    await rt.channel.stop()
    await rt.channel.start()
    for target in [
        "feishu:sw:old",
        "feishu:sw:new",
        "feishu:chat_id:oc_direct",
        "ou_raw",
    ]:
        await rt.channel.send(target, "hello")
    assert [r["receive_id"] for r in rt.rows("create")] == [
        "ou_old",
        "oc_new",
        "oc_direct",
        "ou_raw",
    ]
    assert [post_text(r) for r in rt.rows("create")] == ["[bot]hello"] * 4


@pytest.mark.asyncio
async def test_media_download_and_upload_round_trip_through_child(runtime):
    """Lost locator/content conversion or host SDK upload breaks media."""
    from qwenpaw.schemas import (
        ImageContent,
        FileContent,
        TextContent,
        RefusalContent,
    )

    rt = await runtime()
    parts = []
    for mid, kind, content in [
        ("image-in", "image", {"image_key": "img-in"}),
        (
            "file-in",
            "file",
            {"file_key": "file-in", "file_name": "report.pdf"},
        ),
    ]:
        payload = await inbound(rt, message(mid, kind=kind, content=content))
        part = (
            rt.channel.build_agent_request_from_native(payload)
            .input[0]
            .content[0]
        )
        parts.append(part)
    assert isinstance(parts[0], ImageContent)
    assert isinstance(parts[1], FileContent)
    for part in parts:
        locator = getattr(part, "image_url", None) or part.file_url
        assert (
            Path(locator.removeprefix("file://")).read_bytes()
            == b"media-content"
        )
    await rt.channel.send_content_parts(
        "ou_alice",
        [
            TextContent(text="hello"),
            RefusalContent(refusal="cannot comply"),
            *parts,
        ],
    )
    sent = rt.rows("create")
    assert [r["msg_type"] for r in sent] == ["post", "image", "file"]
    assert post_text(sent[0]) == "hello\ncannot comply"
    assert rt.rows("image")[0]["uploaded_bytes"] == list(b"media-content")
    assert rt.rows("file")[0]["uploaded_bytes"] == list(b"media-content")
    assert all(r["pid"] != os.getpid() for r in rt.rows("download") + sent)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "deny"])
@pytest.mark.parametrize(
    "shared,thread",
    [(False, ""), (True, ""), (False, "omt-topic")],
)
async def test_card_callback_preserves_actual_approval_actor(
    runtime,
    shared,
    thread,
    decision,
    monkeypatch,
):
    """Approval must use operator identity even in synthetic group/topic
    sessions.
    """
    from qwenpaw.schemas import Message, TextContent
    from qwenpaw.runtime.commands.control.base import ControlContext
    from qwenpaw.runtime.commands.control.approval_handler import (
        ApprovalCommandHandler,
    )
    from qwenpaw.app.approvals.service import (
        ApprovalService,
        ApprovalIdentityPolicy,
        PendingApproval,
    )

    rt = await runtime(share_session_in_group=shared, require_mention=True)
    payload = await inbound(
        rt,
        message("approval-source", group=True, mentioned=True, thread=thread),
    )
    request = rt.channel.build_agent_request_from_native(payload)
    event = Message(
        content=[TextContent(text="Allow tool?")],
        metadata={
            "metadata": {
                "message_type": "tool_guard_approval",
                "approval_request_id": "approval-1",
                "tool_name": "shell",
                "severity": "high",
            },
        },
    )
    await rt.channel.on_event_message_completed(
        request,
        rt.channel.get_to_handle_from_request(request),
        event,
        dict(request.channel_meta),
    )
    action = json.loads(rt.rows("create")[-1]["content"])["elements"][-1][
        "actions"
    ][0 if decision == "approve" else 1]["value"]
    assert action["session_ctx"]["session_id"] == request.session_id
    click = {
        "header": {"event_id": "card-1"},
        "event": {
            "operator": {"open_id": "ou_alice"},
            "action": {"value": action},
        },
    }
    callback = await inbound(rt, click, "card")
    command = rt.channel.build_agent_request_from_native(callback)
    assert command.session_id == request.session_id
    assert command.user_id == callback["acl_sender_id"] == "ou_alice"
    assert (
        command.input[0].content[0].text == f"/approval {decision} approval-1"
    )
    context = ControlContext(
        workspace=None,
        payload=command,
        channel=rt.channel,
        session_id=command.session_id,
        user_id=command.user_id,
        agent_id="default",
        args={"action": decision, "request_id": "approval-1"},
    )
    pending = PendingApproval(
        request_id="approval-1",
        session_id=request.session_id,
        root_session_id=request.session_id,
        owner_agent_id="default",
        user_id=request.user_id,
        channel="feishu",
        agent_id="default",
        tool_name="shell",
        created_at=time.time(),
        future=asyncio.get_running_loop().create_future(),
        identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
    )
    assert ApprovalService.actor_can_resolve(
        pending,
        ApprovalCommandHandler._actor(context),
    ) is (not shared and not thread)
    service = ApprovalService()
    service._pending[pending.request_id] = pending
    monkeypatch.setattr(
        "qwenpaw.runtime.commands.control.approval_handler."
        "get_approval_service",
        lambda: service,
    )
    # A different real card operator passes mention admission, but cannot
    # resolve the original request even in a shared group session.
    click["header"]["event_id"] = "card-other-actor"
    click["event"]["operator"]["open_id"] = "ou_mallory"
    outsider = rt.channel.build_agent_request_from_native(
        await inbound(rt, click, "card")
    )
    outsider_context = replace(
        context, payload=outsider, user_id=outsider.user_id
    )
    await ApprovalCommandHandler().handle(outsider_context)
    assert outsider_context.approval_resolution.outcome.value == "forbidden"
    assert not pending.future.done()
    assert await service.get_request("approval-1") is pending

    await ApprovalCommandHandler().handle(context)
    if shared or thread:
        assert context.approval_resolution.outcome.value == "forbidden"
        assert not pending.future.done()
    else:
        expected = "approved" if decision == "approve" else "denied"
        assert context.approval_resolution.outcome.value == expected
        assert pending.future.result().value == expected
        assert await service.get_request("approval-1") is None

    # Control events still cross the ordinary Host ACL gate.
    from qwenpaw.app.channels.access_control import AccessControlStore

    store = AccessControlStore(rt.work / "card-acl.json")
    monkeypatch.setattr(
        "qwenpaw.app.channels.base.get_access_control_store",
        lambda *_a, **_k: store,
    )
    rt.channel.access_control_group = True
    queued = len(rt.queued)
    click["header"]["event_id"] = "card-denied-by-acl"
    rt.emit(click, "card")
    await eventually(lambda: store.get_all_pending())
    assert len(rt.queued) == queued
    assert [row["user_id"] for row in store.get_all_pending()] == [
        "ou_mallory"
    ]


async def stream_request(rt, mid, **settings):
    payload = await inbound(rt, message(mid, **settings))
    request = rt.channel.build_agent_request_from_native(payload)
    return (
        request,
        rt.channel.get_to_handle_from_request(request),
        dict(request.channel_meta),
    )


@pytest.mark.asyncio
async def test_concurrent_topics_keep_reply_and_never_create_stream_card(
    runtime,
):
    """A mutable last-message route cross-wires out-of-order topic replies."""
    rt = await runtime(streaming_enabled=True)
    first = await stream_request(rt, "topic-a", group=True, thread="omt_a")
    second = await stream_request(rt, "topic-b", group=True, thread="omt_b")
    for request, target, meta in [second, first]:
        await rt.channel.on_streaming_start(
            request,
            target,
            None,
            meta,
            "message",
        )
        await rt.channel.on_streaming_end(
            request,
            target,
            None,
            meta,
            "message",
            request.channel_meta["feishu_message_id"],
        )
    assert rt.rows("card") == rt.rows("create") == []
    assert [(r["message_id"], post_text(r)) for r in rt.rows("reply")] == [
        ("topic-b", "topic-b"),
        ("topic-a", "topic-a"),
    ]


@pytest.mark.asyncio
async def test_stream_update_finishes_same_card_and_does_not_send_duplicate(
    runtime,
):
    """Losing delivery ID or sequence creates duplicate stream replies."""
    rt = await runtime(streaming_enabled=True)
    request, target, meta = await stream_request(rt, "stream")
    await rt.channel.on_streaming_start(request, target, None, meta, "message")
    await rt.channel.on_streaming_delta(
        request,
        target,
        None,
        meta,
        "message",
        "hello",
    )
    await rt.channel.on_streaming_end(
        request,
        target,
        None,
        meta,
        "message",
        "hello world",
    )
    assert len(rt.rows("card")) == len(rt.rows("create")) == 1
    assert rt.rows("update")[-1]["content"] == "hello world"
    assert {r["card_id"] for r in rt.rows("update") + rt.rows("settings")} == {
        "card-1",
    }
    seq = [r["sequence"] for r in rt.rows("update")]
    assert seq == sorted(set(seq))
    assert (
        json.loads(rt.rows("settings")[-1]["settings"])["config"][
            "streaming_mode"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_child_restart_restores_inflight_stream_without_recreating_card(
    runtime,
):
    """Dropping durable response/delivery state duplicates a card after
    restart.
    """
    rt = await runtime(streaming_enabled=True)
    request, target, meta = await stream_request(rt, "restore")
    await rt.channel.on_streaming_start(request, target, None, meta, "message")
    await rt.channel.on_streaming_delta(
        request,
        target,
        None,
        meta,
        "message",
        "before",
    )
    old_pid = rt.rows("connected")[-1]["pid"]
    await restart(rt)
    await eventually(lambda: len(rt.rows("connected")) == 2)
    await rt.channel.on_streaming_end(
        request,
        target,
        None,
        meta,
        "message",
        "after restart",
    )
    assert len(rt.rows("card")) == len(rt.rows("create")) == 1
    assert rt.rows("update")[-1]["card_id"] == "card-1"
    assert rt.rows("update")[-1]["content"] == "after restart"
    assert rt.rows("update")[-1]["pid"] != old_pid


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unknown", "commit-exit"])
async def test_uncertain_platform_send_is_recorded_and_never_replayed(
    runtime,
    mode,
):
    """Treating lost platform/IPC receipt as retryable duplicates a
    committed send.
    """
    rt = await runtime()
    _request, _target, meta = await stream_request(rt, "uncertain-send")
    params = {
        "channel_key": "feishu",
        "instance_id": rt.spec.instance_id,
        "generation": rt.spec.generation,
        "delivery_id": "same-logical-delivery",
        "to_handle": meta["response_handle"],
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": "once"}],
    }
    (rt.work / "send-mode").write_text(mode)
    if mode == "commit-exit":
        from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown

        with pytest.raises(ChannelCallUnknown):
            await rt.process.call("channel.send", params)
    else:
        result = await rt.process.call("channel.send", params)
        assert result["state"] == "unknown"
    assert len(rt.rows("create")) == 1
    (rt.work / "send-mode").unlink()
    await restart(rt)
    await eventually(lambda: len(rt.rows("connected")) == 2)
    params["generation"] = rt.spec.generation
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert len(rt.rows("create")) == 1


@pytest.mark.asyncio
async def test_custom_endpoint_reaches_sdk_http_and_websocket(runtime):
    """Hardcoded Feishu endpoint bypasses the user's gateway."""
    rt = await runtime(domain="https://gateway.example.invalid")
    assert rt.rows("client")[0]["domain"] == "https://gateway.example.invalid"
    assert (
        rt.rows("connected")[0]["domain"] == "https://gateway.example.invalid"
    )
    assert (
        rt.rows("http")[0]["url"]
        == "https://gateway.example.invalid/open-apis/bot/v3/info"
    )


@pytest.mark.asyncio
async def test_real_descriptor_loads_and_rejects_invalid_config_before_network(
    tmp_path,
):
    """The shim cannot hide an unwired production descriptor/Driver class."""
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        LaunchSpec,
    )

    code = tmp_path / "actual-entry"
    shutil.copytree(
        ROOT / "plugins/channel/feishu",
        code,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    spec = LaunchSpec(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        code_root=code,
        descriptor_path=code / "channel.json",
        source_revision=digest(code),
        channel_key="feishu",
        instance_id="real-descriptor",
        generation=1,
        qwenpaw_version="2.2.2b4",
        config={"app_id": "", "app_secret": ""},
        startup_timeout=8,
        shutdown_timeout=0.5,
    )
    process = ChannelProcess()
    try:
        await process.start(spec)
        await eventually(
            lambda: process.health_snapshot()["platform_state"] == "failed",
        )
        assert process.health_snapshot()["state"] == "ready"
    finally:
        assert (await process.stop()).exited


@pytest.mark.asyncio
async def test_cancelled_host_agent_finalizes_only_its_inflight_stream(
    runtime,
):
    """Cancellation must finish its exact card without closing another
    reply.
    """
    from qwenpaw.schemas import Message, RunStatus, TextContent

    entered = asyncio.Event()
    rt = None

    async def agent(request):
        target = rt.channel.get_to_handle_from_request(request)
        meta = request.channel_meta
        await rt.channel.on_streaming_start(
            request,
            target,
            None,
            meta,
            "message",
        )
        await rt.channel.on_streaming_delta(
            request,
            target,
            None,
            meta,
            "message",
            "partial",
        )
        entered.set()
        await asyncio.Event().wait()
        yield Message(
            object="message",
            status=RunStatus.Completed,
            content=[TextContent(text="never")],
        )

    rt = await runtime(agent=agent, streaming_enabled=True)
    payload = await inbound(rt, message("cancel-me"))
    task = asyncio.create_task(rt.channel.consume_one(payload))
    await asyncio.wait_for(entered.wait(), 4)
    other = await stream_request(rt, "other", sender="ou_bob")
    request, target, meta = other
    await rt.channel.on_streaming_start(request, target, None, meta, "message")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await rt.channel.on_streaming_end(
        request,
        target,
        None,
        meta,
        "message",
        "other completed",
    )
    assert len(rt.rows("card")) == len(rt.rows("create")) == 2
    assert rt.rows("update")[-1]["card_id"] == "card-2"
    assert rt.rows("update")[-1]["content"] == "other completed"
    assert {r["card_id"] for r in rt.rows("settings")} == {"card-1", "card-2"}


@pytest.mark.asyncio
async def test_network_reconnect_fences_late_old_connection_callbacks(runtime):
    """An SDK callback retained by an old WebSocket cannot enter a newer
    turn.
    """
    rt = await runtime()
    rt.emit({}, "disconnect")
    await eventually(lambda: len(rt.rows("connected")) == 2)
    rt.emit(message("late-old"), "old-message")
    await inbound(rt, message("fresh"))
    assert [p["meta"]["feishu_message_id"] for p in rt.queued] == ["fresh"]


@pytest.mark.asyncio
async def test_new_process_rejects_old_generation_before_side_effect(
    runtime,
):
    """Restart must reject stale requests instead of using a newer route."""
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime()
    await restart(rt)
    await eventually(lambda: len(rt.rows("connected")) == 2)
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.response.open",
            {
                "channel_key": "feishu",
                "instance_id": rt.spec.instance_id,
                "generation": 1,
                "to_handle": "ou_alice",
                "meta": {},
            },
        )
    assert rt.rows("create") == []


@pytest.mark.asyncio
async def test_agent_unknown_send_does_not_emit_second_error_message(
    runtime,
):
    """BaseChannel generic error fallback must not replay an uncertain
    reply.
    """
    rt = await runtime()
    payload = await inbound(rt, message("agent-unknown"))
    (rt.work / "send-mode").write_text("unknown")
    try:
        await rt.channel.consume_one(payload)
    except Exception as error:
        assert "UNKNOWN" in str(error).upper() or getattr(
            error,
            "side_effect_possible",
            False,
        )
    assert len(rt.requests) == 1
    assert len(rt.rows("create")) == 1
    assert post_text(rt.rows("create")[0]) == "host answer"


@pytest.mark.asyncio
async def test_filtered_events_do_not_exhaust_reply_route_capacity(runtime):
    """Allocating persistent reply routes before mention rejection starves
    users.
    """
    rt = await runtime(require_mention=True)
    for index in range(140):
        rt.emit(message(f"unmentioned-{index}", group=True))
    payload = await inbound(
        rt,
        message("accepted-after-filters", group=True, mentioned=True),
    )
    await rt.channel.consume_one(payload)
    assert len(rt.queued) == 1
    assert len(rt.requests) == len(rt.rows("create")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, {}], ids=["omitted", "explicit"])
async def test_standalone_proactive_sends_release_finished_routes(
    runtime,
    metadata,
):
    """Successful scheduled sends cannot retain active routes until
    capacity fills.
    """
    rt = await runtime()
    for index in range(140):
        await rt.channel.send(
            "ou_alice",
            f"scheduled {index}",
            dict(metadata) if metadata is not None else None,
        )
    assert len(rt.rows("create")) == 140
    assert post_text(rt.rows("create")[-1]) == "scheduled 139"


@pytest.mark.asyncio
async def test_tracker_cancellation_finalizes_its_stream(runtime):
    """The bound-workspace Agent path must run the same response cleanup."""
    from qwenpaw.schemas import Message, RunStatus

    async def agent(_request):
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.InProgress,
        )
        await asyncio.Event().wait()

    rt = await runtime(agent=agent, streaming_enabled=True)
    payload = await inbound(rt, message("tracker-cancel"))

    async def consume():
        async for _event in rt.channel._stream_with_tracker(payload):
            pass

    task = asyncio.create_task(consume())
    try:
        await eventually(lambda: len(rt.rows("create")) == 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(rt.rows("settings")) == 1
        assert rt.rows("settings")[0]["card_id"] == "card-1"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_tracker_unknown_send_does_not_emit_second_error_message(
    runtime,
):
    """The tracker's separate metadata copy cannot bypass unknown
    protection.
    """
    rt = await runtime()
    payload = await inbound(rt, message("tracker-unknown"))
    (rt.work / "send-mode").write_text("unknown")
    try:
        async for _event in rt.channel._stream_with_tracker(payload):
            pass
    except Exception as error:
        assert "UNKNOWN" in str(error).upper() or getattr(
            error,
            "side_effect_possible",
            False,
        )
    assert len(rt.requests) == 1
    assert len(rt.rows("create")) == 1
    assert post_text(rt.rows("create")[0]) == "host answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["normal", "unknown", "cancelled"])
async def test_bound_workspace_dispatch_uses_real_tracker_and_closes_response(
    runtime,
    outcome,
    monkeypatch,
):
    """Workspace dispatch must preserve response cleanup and unknown
    handling.
    """
    from unittest.mock import AsyncMock
    from qwenpaw.app.task_tracker import TaskTracker
    from qwenpaw.channel_protocol.models import SendParams
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )
    from qwenpaw.schemas import Message, RunStatus

    async def blocked_agent(_request):
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.InProgress,
        )
        await asyncio.Event().wait()

    rt = await runtime(
        agent=blocked_agent if outcome == "cancelled" else None,
        streaming_enabled=outcome == "cancelled",
    )
    sends = []
    call = rt.process.call

    async def capture_send(method, params=None, **kwargs):
        result = await call(method, params, **kwargs)
        if method == "channel.send":
            sends.append(
                (SendParams.from_mapping(params).to_mapping(), result)
            )
        return result

    monkeypatch.setattr(rt.process, "call", capture_send)
    tracker = TaskTracker()
    chat_manager = NS(
        get_or_create_chat=AsyncMock(return_value=NS(id="real-chat")),
        touch_chat=AsyncMock(),
        mark_chat_finished=AsyncMock(),
    )
    rt.channel.set_workspace(
        NS(task_tracker=tracker, chat_manager=chat_manager),
        NS(is_control_command=lambda _: False),
    )
    payload = await inbound(rt, message(f"workspace-{outcome}"))
    if outcome == "unknown":
        (rt.work / "send-mode").write_text("unknown")
    task = asyncio.create_task(rt.channel.consume_one(payload))
    try:
        if outcome == "cancelled":
            await eventually(lambda: len(rt.rows("create")) == 1)
            assert await tracker.request_stop("real-chat")
        await asyncio.wait_for(task, 6)
        assert len(rt.rows("create")) == 1
        handle = payload["meta"]["response_handle"]
        if outcome == "unknown":
            assert len(sends) == 1
            params, result = sends[0]
            assert params["to_handle"] == handle
            assert result["state"] == "unknown"
            assert result["reason_code"] == "MESSAGE_RESULT_UNKNOWN"
            store = ResponseReceiptStore(
                rt.channel._state_path().with_suffix(".receipts.sqlite3"),
            )
            key = receipt_key("feishu.shared.responses", handle)
            receipt = store.get(key)
            assert receipt["cleanup_state"] == "complete"
            assert receipt["route_refs"] == []
            assert handle not in persisted_routes(rt)
            attempts = [
                ref
                for ref in receipt["resource_refs"]
                if ref["kind"] == "feishu.attempt"
                and ref["resource_id"] == params["delivery_id"]
            ]
            assert len(attempts) == 1
            attrs = attempts[0]["attributes"]
            assert attrs["state"] == result["state"]
            assert attrs["reason_code"] == result["reason_code"]
            intent = {k: v for k, v in params.items() if k != "generation"}
            fingerprint = hashlib.sha256(
                json.dumps(intent, sort_keys=True).encode(),
            ).hexdigest()
            assert attrs["fingerprint"] == fingerprint
            old_pid = rt.process.health_snapshot()["pid"]
            await restart(rt)
            assert rt.process.health_snapshot()["pid"] != old_pid
            replay = {**params, "generation": rt.spec.generation}
            assert await rt.process.call("channel.send", replay) == result
            assert len(rt.rows("create")) == 1
            assert store.get(key) == receipt
            assert handle not in persisted_routes(rt)
        else:
            receipt = persisted_routes(rt)[handle]
        assert receipt["kind"] == "terminal"
        if outcome == "cancelled":
            assert receipt["outcome"] == "cancelled"
            assert len(rt.rows("settings")) == 1
        elif outcome == "normal":
            assert receipt["cleanup_state"] == "complete"
    finally:
        await tracker.request_stop("real-chat")
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_public_restart_advances_generation_and_keeps_accepted_dedup(
    runtime,
):
    """Public restart must not reuse a generation or re-admit an accepted
    event.
    """
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime()
    await inbound(rt, message("accepted-once"))
    before = rt.process.health_snapshot()
    await rt.channel.stop()
    await rt.channel.start()
    async with asyncio.timeout(6):
        while (await rt.channel.health_check()).get(
            "platform_state",
        ) != "connected":
            await asyncio.sleep(0.01)
    after = rt.process.health_snapshot()
    assert after["pid"] != before["pid"]
    assert after["generation"] == before["generation"] + 1
    rt.emit(message("accepted-once"))
    await inbound(rt, message("fresh-after-restart"))
    assert [p["meta"]["feishu_message_id"] for p in rt.queued] == [
        "accepted-once",
        "fresh-after-restart",
    ]
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.response.open",
            {
                "channel_key": "feishu",
                "instance_id": rt.spec.instance_id,
                "generation": before["generation"],
                "to_handle": "ou_alice",
                "meta": {},
            },
        )


@pytest.mark.asyncio
async def test_blocked_sdk_send_keeps_host_scheduling_and_cancellation_unknown(
    runtime,
):
    """SDK stalls stay in the child, and cancellation must preserve
    uncertainty.
    """
    rt = await runtime()
    (rt.work / "send-mode").write_text("commit-hang")
    task = asyncio.create_task(rt.channel.send("ou_alice", "blocked"))
    try:
        await eventually(lambda: len(rt.rows("create")) == 1)
        ticks = 0
        until = asyncio.get_running_loop().time() + 0.15
        while asyncio.get_running_loop().time() < until:
            ticks += 1
            await asyncio.sleep(0.01)
        assert ticks >= 8
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert any(
            row["method"] == "channel.send"
            for row in rt.process.health_snapshot()["unknown_outcomes"]
        )
        assert len(rt.rows("create")) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def persisted_routes(rt):
    """Read real durable response receipts without reaching into proxy
    state.
    """
    found = {}

    def walk(value):
        if isinstance(value, dict):
            if {
                "response_handle",
                "route_refs",
                "resource_refs",
            } <= value.keys():
                found[value["response_handle"]] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for path in (rt.work / "channel_state").glob("*.json"):
        walk(json.loads(path.read_text()))
    return found


async def public_stream(rt, handle, *, sequence=7):
    identity = {
        "channel_key": "feishu",
        "instance_id": rt.spec.instance_id,
        "generation": rt.spec.generation,
    }
    result = await rt.process.call(
        "channel.send",
        {
            **identity,
            "delivery_id": "stream-resource",
            "to_handle": handle,
            "operation": "stream.start",
            "stream_type": "message",
            "sequence": 0,
            "accumulated_text": "started",
        },
    )
    assert result["state"] == "acknowledged"
    result = await rt.process.call(
        "channel.send",
        {
            **identity,
            "delivery_id": "delta-attempt",
            "to_handle": handle,
            "operation": "stream.delta",
            "stream_type": "message",
            "target_delivery_id": "stream-resource",
            "sequence": sequence,
            "accumulated_text": "partial",
        },
    )
    return result


def finish_params(rt, handle):
    return {
        "channel_key": "feishu",
        "instance_id": rt.spec.instance_id,
        "generation": rt.spec.generation,
        "response_handle": handle,
        "outcome": "cancelled",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ["update-unknown", "update-exit", "settings-unknown"],
)
async def test_ambiguous_stream_cleanup_is_not_replayed_after_restart(
    runtime,
    mode,
):
    """Cleanup intent must be durable before an uncertain SDK finalization."""
    rt = await runtime(streaming_enabled=True)
    _request, _target, meta = await stream_request(rt, "cleanup-unknown")
    handle = meta["response_handle"]
    assert (await public_stream(rt, handle))["state"] == "acknowledged"
    (rt.work / "send-mode").write_text(mode)
    if mode == "update-exit":
        from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown

        with pytest.raises(ChannelCallUnknown):
            await rt.process.call(
                "channel.response.finish",
                finish_params(rt, handle),
            )
    else:
        from qwenpaw.channel_protocol.errors import RpcError

        with pytest.raises(RpcError) as caught:
            await rt.process.call(
                "channel.response.finish",
                finish_params(rt, handle),
            )
        assert caught.value.data["reason_code"] in {
            "RESPONSE_FINISH_FAILED",
            "RESPONSE_FINISH_UNKNOWN",
        }
    assert [r["sequence"] for r in rt.rows("update")] == [7, 8]
    attempts = len(rt.rows("update")), len(rt.rows("settings"))
    (rt.work / "send-mode").unlink()
    await restart(rt)
    health = await rt.channel.health_check()
    assert health["platform_state"] == "connected"
    assert health.get("last_diagnostic") in {
        "RESPONSE_FINISH_FAILED",
        "RESPONSE_FINISH_UNKNOWN",
    }
    from qwenpaw.channel_protocol.errors import RpcError

    with pytest.raises(RpcError) as caught:
        await rt.process.call(
            "channel.response.finish",
            finish_params(rt, handle),
        )
    assert caught.value.data["reason_code"] in {
        "RESPONSE_FINISH_FAILED",
        "RESPONSE_FINISH_UNKNOWN",
    }
    assert (len(rt.rows("update")), len(rt.rows("settings"))) == attempts
    assert len(rt.rows("card")) == len(rt.rows("create")) == 1
    receipt = persisted_routes(rt)[handle]
    assert receipt["kind"] == "terminal"
    assert receipt["cleanup_state"] == "pending"
    resources = [row["attributes"] for row in receipt["resource_refs"]]
    assert any(row.get("cleanup") == "unknown" for row in resources)
    assert not any(row.get("cleanup") == "complete" for row in resources)


@pytest.mark.asyncio
async def test_cleanup_sequence_exceeds_previously_attempted_unknown_delta(
    runtime,
):
    """A lost delta receipt still advances the next SDK cleanup sequence."""
    rt = await runtime(streaming_enabled=True)
    _request, _target, meta = await stream_request(rt, "sequence-unknown")
    handle = meta["response_handle"]
    # Apply uncertainty only to the update; card creation is already known.
    start = {
        "channel_key": "feishu",
        "instance_id": rt.spec.instance_id,
        "generation": rt.spec.generation,
        "delivery_id": "stream-resource",
        "to_handle": handle,
        "operation": "stream.start",
        "stream_type": "message",
        "sequence": 0,
        "accumulated_text": "started",
    }
    assert (await rt.process.call("channel.send", start))[
        "state"
    ] == "acknowledged"
    (rt.work / "send-mode").write_text("update-unknown")
    delta = {
        **start,
        "delivery_id": "uncertain-delta",
        "operation": "stream.delta",
        "target_delivery_id": "stream-resource",
        "sequence": 19,
        "accumulated_text": "may have arrived",
    }
    assert (await rt.process.call("channel.send", delta))["state"] == "unknown"
    (rt.work / "send-mode").unlink()
    await rt.process.call("channel.response.finish", finish_params(rt, handle))
    assert [r["sequence"] for r in rt.rows("update")] == [19, 20]
    assert rt.rows("settings")[-1]["sequence"] == 21


@pytest.mark.asyncio
async def test_merged_native_messages_finish_every_original_response(runtime):
    """Merging content must not orphan the other request-scoped reply
    routes.
    """
    rt = await runtime()
    first = await inbound(rt, message("merge-first"))
    second = await inbound(rt, message("merge-second"))
    handles = [p["meta"]["response_handle"] for p in [first, second]]
    merged = rt.channel.merge_native_items([first, second])
    await rt.channel.consume_one(merged)
    assert [part.text for part in rt.requests[0].input[0].content] == [
        "hello",
        "hello",
    ]
    receipts = persisted_routes(rt)
    assert [
        (receipts[h]["kind"], receipts[h]["cleanup_state"]) for h in handles
    ] == [("terminal", "complete")] * 2
    assert len(rt.rows("create")) == 1


@pytest.mark.asyncio
async def test_media_no_text_debounce_finishes_buffered_and_current_routes(
    runtime,
):
    """Default media buffering must retain its response handle through text."""
    rt = await runtime(no_text_debounce=True)
    image = await inbound(
        rt,
        message(
            "buffered-image",
            kind="image",
            content={"image_key": "img-in"},
        ),
    )
    await rt.channel.consume_one(image)
    assert rt.requests == []
    text = await inbound(rt, message("following-text"))
    await rt.channel.consume_one(text)
    assert len(rt.requests) == 1
    receipts = persisted_routes(rt)
    handles = [p["meta"]["response_handle"] for p in [image, text]]
    assert [
        (receipts[h]["kind"], receipts[h]["cleanup_state"]) for h in handles
    ] == [("terminal", "complete")] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parts,expected",
    [(False, "[caller]hello"), (True, "[caller]  hello")],
)
async def test_per_send_prefix_and_target_override_reach_platform(
    runtime,
    parts,
    expected,
):
    """Caller send metadata overrides the configured prefix and receive
    target.
    """
    from qwenpaw.schemas import TextContent

    rt = await runtime(bot_prefix="[config]")
    meta = {
        "bot_prefix": "[caller]",
        "feishu_receive_id": "oc_override",
        "feishu_receive_id_type": "chat_id",
    }
    if parts:
        await rt.channel.send_content_parts(
            "ou_unused",
            [TextContent(text="hello")],
            meta,
        )
    else:
        await rt.channel.send("ou_unused", "hello", meta)
    assert len(rt.rows("create")) == 1
    assert rt.rows("create")[0]["receive_id"] == "oc_override"
    assert post_text(rt.rows("create")[0]) == expected


@pytest.mark.asyncio
async def test_large_streams_bound_state_and_preserve_active_unknown(
    runtime,
):
    """Terminal stream text cannot exhaust checkpoints or evict live
    uncertainty.
    """
    rt = await runtime(streaming_enabled=True)
    active = await inbound(rt, message("keep-active"))
    unknown = await inbound(rt, message("keep-unknown"))
    active_handle = active["meta"]["response_handle"]
    unknown_handle = unknown["meta"]["response_handle"]
    uncertain = {
        "channel_key": "feishu",
        "instance_id": rt.spec.instance_id,
        "generation": rt.spec.generation,
        "delivery_id": "keep-delivery",
        "to_handle": unknown_handle,
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": "once"}],
    }
    (rt.work / "send-mode").write_text("unknown")
    assert (await rt.process.call("channel.send", uncertain))[
        "state"
    ] == "unknown"
    (rt.work / "send-mode").unlink()
    text = "x" * 50_000
    for index in range(21):
        request, target, meta = await stream_request(rt, f"large-{index}")
        await rt.channel.on_streaming_start(
            request,
            target,
            None,
            meta,
            "message",
        )
        await rt.channel.on_streaming_end(
            request,
            target,
            None,
            meta,
            "message",
            text,
        )
        result = await rt.process.call(
            "channel.response.finish",
            {
                **finish_params(rt, meta["response_handle"]),
                "outcome": "completed",
            },
        )
        assert result["state"] == "closed"
    assert len(rt.rows("card")) == len(rt.rows("settings")) == 21
    assert all(
        path.stat().st_size <= 1024 * 1024
        for path in (rt.work / "channel_state").glob("*.json")
    )
    receipts = persisted_routes(rt)
    assert receipts[active_handle]["kind"] == "active"
    assert receipts[unknown_handle]["kind"] == "active"
    count = len(rt.rows("create"))
    assert (await rt.process.call("channel.send", uncertain))[
        "state"
    ] == "unknown"
    assert len(rt.rows("create")) == count


@pytest.mark.asyncio
async def test_single_sdk_callback_recovers_transient_host_admission(runtime):
    """SDK success ACK means ingress retries must have their own owner."""
    rt = await runtime()
    attempts = []

    def accept(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise RuntimeError("queue temporarily unavailable")
        rt.queued.append(payload)

    set_admission(rt.channel, accept)
    rt.emit(message("single-transient"))
    await eventually(lambda: len(rt.queued) == 1)
    assert len(rt.rows("callback")) == 1
    assert len(attempts) == 2
    assert len({p["meta"]["response_handle"] for p in attempts}) == 1
    await rt.channel.consume_one(rt.queued[0])
    assert len(rt.requests) == len(rt.rows("create")) == 1


@pytest.mark.asyncio
async def test_exhausted_host_admission_retries_are_bounded_and_release_route(
    runtime,
):
    """Queue rejection cannot retry forever or hold unused route capacity."""
    rt = await runtime()
    attempts = []

    def reject(payload):
        attempts.append(payload)
        raise RuntimeError("queue remains unavailable")

    set_admission(rt.channel, reject)
    rt.emit(message("always-rejected"))
    await eventually(lambda: len(attempts) >= 2)
    await eventually(
        lambda: not any(
            row["kind"] == "active" for row in persisted_routes(rt).values()
        ),
    )
    count = len(attempts)
    assert 2 <= count <= 10
    assert (await rt.channel.health_check()).get(
        "last_diagnostic",
    ) == "HOST_ADMISSION_EXHAUSTED"
    await asyncio.sleep(0.2)
    assert len(attempts) == count
    assert len(rt.rows("callback")) == 1
    assert rt.queued == rt.rows("create") == []

    # A definitely unused route must allow a later native redelivery to work.
    set_admission(rt.channel, rt.queued.append)
    payload = await inbound(rt, message("always-rejected"))
    assert len(rt.queued) == 1
    await rt.channel.consume_one(payload)
    assert len(rt.rows("create")) == 1
    assert post_text(rt.rows("create")[0]) == "host answer"


@pytest.mark.asyncio
async def test_permanent_host_policy_rejection_releases_unused_route(runtime):
    """A permanent host rejection cannot retain a route awaiting acceptance."""
    rt = await runtime()
    rt.channel.require_mention = True
    rt.emit(message("permanent-mention-rejection", group=True))
    await eventually(lambda: len(rt.rows("callback")) == 1)
    await eventually(
        lambda: bool(list((rt.work / "channel_state").glob("*.json"))),
    )
    await eventually(
        lambda: all(
            row["kind"] != "active" for row in persisted_routes(rt).values()
        ),
    )
    assert rt.queued == rt.rows("create") == []


@pytest.mark.asyncio
async def test_stop_cancels_pending_host_admission_retries(runtime):
    """Stopping the channel must end its ingress retry owner promptly."""
    rt = await runtime()
    attempts = []

    def reject(payload):
        attempts.append(payload)
        raise RuntimeError("queue remains unavailable")

    set_admission(rt.channel, reject)
    rt.emit(message("stop-retrying"))
    await eventually(lambda: len(attempts) >= 2)
    await asyncio.wait_for(rt.channel.stop(), 3)
    count = len(attempts)
    await asyncio.sleep(0.2)
    assert len(attempts) == count
    assert rt.process.health_snapshot()["pid"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("parts", [False, True])
async def test_definite_standalone_failure_closes_its_owned_route(
    runtime,
    parts,
):
    """A known platform refusal must release standalone reply ownership."""
    from qwenpaw.schemas import TextContent

    rt = await runtime()
    (rt.work / "send-mode").write_text("definite-failure")
    with pytest.raises(Exception) as caught:
        if parts:
            await rt.channel.send_content_parts(
                "ou_alice",
                [TextContent(text="hello")],
                {},
            )
        else:
            await rt.channel.send("ou_alice", "hello", {})
    assert getattr(caught.value, "side_effect_possible", None) is False
    receipts = list(persisted_routes(rt).values())
    assert len(receipts) == 1
    assert (receipts[0]["kind"], receipts[0].get("cleanup_state")) == (
        "terminal",
        "complete",
    )


@pytest.mark.asyncio
async def test_merged_media_buffer_finishes_all_original_routes(runtime):
    """Buffering merged image-only content cannot discard an earlier handle."""
    rt = await runtime(no_text_debounce=True)
    images = [
        await inbound(
            rt,
            message(mid, kind="image", content={"image_key": key}),
        )
        for mid, key in [
            ("merged-image-a", "img-a"),
            ("merged-image-b", "img-b"),
        ]
    ]
    await rt.channel.consume_one(rt.channel.merge_native_items(images))
    assert rt.requests == []
    text = await inbound(rt, message("text-after-merged-images"))
    await rt.channel.consume_one(text)
    receipts = persisted_routes(rt)
    handles = [p["meta"]["response_handle"] for p in [*images, text]]
    assert [
        (receipts[h]["kind"], receipts[h].get("cleanup_state"))
        for h in handles
    ] == [("terminal", "complete")] * 3


@pytest.mark.asyncio
async def test_standalone_approval_notification_releases_its_route(runtime):
    """Inherited approval notifications also own standalone reply routes."""
    rt = await runtime()
    await rt.channel.send_approval_notification(
        session_id="approval-session",
        user_id="ou_alice",
        request_id="approval-standalone",
        tool_name="shell",
        severity="high",
        result_summary="Allow?",
        channel_meta={
            "feishu_receive_id": "ou_alice",
            "feishu_receive_id_type": "open_id",
        },
    )
    assert len(rt.rows("create")) == 1
    assert rt.rows("create")[0]["msg_type"] == "interactive"
    receipts = list(persisted_routes(rt).values())
    assert len(receipts) == 1
    assert (receipts[0]["kind"], receipts[0].get("cleanup_state")) == (
        "terminal",
        "complete",
    )


@pytest.mark.asyncio
async def test_cancellation_during_normal_cleanup_propagates_and_keeps_owner(
    runtime,
):
    """First cancellation during finalization cannot become normal success."""
    from qwenpaw.schemas import Message, RunStatus

    async def agent(_request):
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.InProgress,
        )

    rt = await runtime(agent=agent, streaming_enabled=True)
    payload = await inbound(rt, message("cancel-during-cleanup"))
    (rt.work / "send-mode").write_text("update-block")

    async def consume():
        async for _event in rt.channel._stream_with_tracker(payload):
            pass

    task = asyncio.create_task(consume())
    try:
        await eventually(lambda: len(rt.rows("update")) == 1)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert rt.rows("settings") == []
        (rt.work / "update-release").touch()
        await eventually(lambda: len(rt.rows("settings")) == 1)
        handle = payload["meta"]["response_handle"]
        await eventually(
            lambda: persisted_routes(rt)[handle].get("cleanup_state")
            == "complete",
        )
        assert len(rt.rows("update")) == len(rt.rows("settings")) == 1
    finally:
        (rt.work / "update-release").touch()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_lost_admission_ack_preserves_accepted_reply_route(
    runtime,
    monkeypatch,
):
    """Drop one real encoded IPC receipt after host admission, then recover."""
    rt = await runtime()
    writer = rt.process._peer._transport._writer
    write = writer.write
    dropped, recovered = asyncio.Event(), asyncio.Event()

    def write_with_first_ack_loss(data):
        frame = json.loads(bytes(data).split(b"\r\n\r\n", 1)[1])
        receipt = frame.get("result", {})
        if isinstance(receipt, dict):
            if receipt.get("accepted_event_ids") and not dropped.is_set():
                dropped.set()
                return
            if receipt.get("duplicate_event_ids"):
                recovered.set()
        write(data)

    monkeypatch.setattr(writer, "write", write_with_first_ack_loss)
    payload = await inbound(rt, message("accepted-ack-lost"))
    await asyncio.wait_for(dropped.wait(), 2)
    await asyncio.wait_for(recovered.wait(), 38)
    # The next native event acts as a production child/host processing fence.
    await inbound(rt, message("after-ack-recovery"))
    assert len(rt.rows("callback")) == 2
    assert [p["meta"]["feishu_message_id"] for p in rt.queued].count(
        "accepted-ack-lost",
    ) == 1
    handle = payload["meta"]["response_handle"]
    assert persisted_routes(rt)[handle]["kind"] == "active"
    await rt.channel.consume_one(payload)
    assert len(rt.rows("create")) == 1
    assert post_text(rt.rows("create")[0]) == "host answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
# Keep the stable pytest selector; only this definition is long.
# pylint: disable-next=line-too-long
async def test_standard_debounce_separates_members_and_threads_without_changing_historic_session(  # noqa: E501
    runtime,
    shared,
):
    rt = await runtime(share_session_in_group=shared)
    native = []
    for event in [
        message("member-one", sender="ou_member00000001", group=True),
        message("member-two", sender="ou_member00000002", group=True),
        message(
            "thread-one",
            sender="ou_member00000001",
            group=True,
            thread="omt-thread00000001",
        ),
        message(
            "thread-two",
            sender="ou_member00000001",
            group=True,
            thread="omt-thread00000002",
        ),
    ]:
        native.append(await inbound(rt, event))
    assert [item["session_id"] for item in native] == ["test_oc_room"] * 4
    requests = [
        rt.channel.build_agent_request_from_native(item) for item in native
    ]
    assert [request.session_id for request in requests] == ["test_oc_room"] * 4
    assert [item["acl_sender_id"] for item in native] == [
        "ou_member00000001",
        "ou_member00000002",
        "ou_member00000001",
        "ou_member00000001",
    ]
    expected_members = (
        ["test_oc_room", "test_oc_room"]
        if shared
        else [
            "test_oc_room:ou_member00000001",
            "test_oc_room:ou_member00000002",
        ]
    )
    assert [
        rt.channel.get_debounce_key(item) for item in native
    ] == expected_members + [
        "test_oc_room:thread:00000001",
        "test_oc_room:thread:00000002",
    ]
    assert [request.user_id for request in requests] == (
        ["group", "group"]
        if shared
        else ["ou_member00000001", "ou_member00000002"]
    ) + ["thread:00000001", "thread:00000002"]
