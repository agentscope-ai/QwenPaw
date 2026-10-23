# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,too-many-statements
# pylint: disable=unused-argument,using-constant-test
"""C2 real workspace/process integration with controlled vendor networking."""

import asyncio
import hashlib
import importlib
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace as NS

import psutil
import pytest

from ownership_helpers import channel_leases
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
KEY = os.environ["QWENPAW_C2_CHANNEL"]
sys.path.insert(0, str(Path(__file__).parent))
native = importlib.import_module(KEY + "_process_suite")

IMPORT_ATTEMPTS = []


class RecordingPlatformGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(
            (
                "lark_oapi",
                "dingtalk_stream",
                "alibabacloud_",
                "qwenpaw.app.channels.feishu",
                "qwenpaw.app.channels.dingtalk",
                "feishu.driver",
                "feishu.platform",
                "dingtalk.driver",
                "dingtalk.transport",
            ),
        ):
            IMPORT_ATTEMPTS.append(fullname)
            raise AssertionError("Host platform import: " + fullname)


sys.meta_path.insert(0, RecordingPlatformGuard())


@pytest.fixture(autouse=True)
def assert_no_host_platform_import_attempts():
    IMPORT_ATTEMPTS.clear()
    yield
    assert not IMPORT_ATTEMPTS


class Workspace:
    """Minimal workspace container carrying real framework services."""


def installed_artifact(tmp_path):
    source = tmp_path / "installed" / KEY
    shutil.copytree(
        ROOT / "plugins/channel" / KEY,
        source,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    network = tmp_path / "network"
    network.mkdir()
    boundary = Path(__file__).with_name(KEY + "_process_boundary.py")
    prefix = (
        "import os\nfrom pathlib import Path\n"
        f"WORK = str(Path({str(network)!r}) / str(os.getpid()))\n"
        "Path(WORK).mkdir(parents=True, exist_ok=True)\n"
    )
    suffix = (
        "\nimport sys\n"
        "record('origins', files={name: module.__file__ for name, module in "
        f"list(sys.modules.items()) if name.startswith({KEY!r} + '.')}})\n"
    )
    driver_name = "FeishuDriver" if KEY == "feishu" else "DingTalkDriver"
    suffix += (
        f"\n_ActualDriver = {driver_name}\n"
        f"class {driver_name}(_ActualDriver):\n"
        "    def __init__(self):\n"
        "        record('driver-constructed')\n"
        "        super().__init__()\n"
        "    def bind(self, context):\n"
        "        record('driver-bound')\n"
        "        return super().bind(context)\n"
        "    async def start(self, config):\n"
        "        record('driver-start')\n"
        "        return await super().start(config)\n"
        "    async def stop(self):\n"
        "        record('driver-stop')\n"
        "        return await super().stop()\n"
    )
    (source / KEY / "boundary.py").write_text(
        prefix + boundary.read_text() + suffix,
    )
    descriptor = json.loads((source / "channel.json").read_text())
    descriptor["entrypoint"]["module"] = KEY + ".boundary"
    (source / "channel.json").write_text(json.dumps(descriptor))
    return source, network


@pytest_asyncio.fixture
async def framework(tmp_path):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
    from qwenpaw.app.task_tracker import TaskTracker
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.schemas import Message, RunStatus, TextContent

    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    source, network = installed_artifact(tmp_path)
    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text()),
    )
    workspaces = []
    loader = PluginLoader(
        [source.parent],
        channel_runtime=ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            qwenpaw_version="2.2.2b4",
            selected_channels=frozenset({"feishu", "dingtalk"}),
            startup_timeout=8,
            shutdown_timeout=1,
            admission_timeout=0.2,
        ),
    )
    loader.registry = registry
    registry.projector = WorkspaceProjector(live_workspaces=lambda: workspaces)

    async def workspace(name, *, enabled=True, configured=True, **settings):
        ws = Workspace()
        ws.agent_id = name
        ws.workspace_dir = tmp_path / name
        ws.workspace_dir.mkdir()
        ws.requests, ws.agent_pids, ws.dispatches = [], [], []
        ws.started = asyncio.Event()
        config = {
            "enabled": enabled,
            "no_text_debounce": True,
            "python_executable": "/malicious/user/python",
            "generation": 999,
            **(
                {"app_id": "cli_test", "app_secret": "test-only"}
                if KEY == "feishu"
                else {"client_id": "client-one", "client_secret": "test-only"}
            ),
            **settings,
        }
        ws._config = Config.model_validate(
            {"channels": {KEY: config} if configured else {}},
        )

        async def agent(request):
            ws.requests.append(request)
            ws.agent_pids.append(os.getpid())
            ws.started.set()
            yield Message(
                object="message",
                status=RunStatus.Completed,
                role="assistant",
                content=[TextContent(text="answer:" + name)],
            )

        async def dispatched(channel, user, session):
            ws.dispatches.append((channel, user, session))

        ws.stream_query = agent
        ws.chat_manager = ChatManager(
            repo=JsonChatRepository(ws.workspace_dir / "chats.json"),
        )
        ws.task_tracker = TaskTracker()
        ws.on_last_dispatch = dispatched
        workspaces.append(ws)
        return ws

    async def activate(*, global_enabled=True):
        record = await loader.load_plugin(
            manifest,
            source,
            {"enabled": global_enabled},
            activate=False,
        )
        for ws in workspaces:
            ws.channel_manager = ChannelManager.from_config(
                ws.stream_query,
                ws._config,
                ws.on_last_dispatch,
                workspace_dir=ws.workspace_dir,
                defer_process_channels=True,
            )
            ws.channel_manager.set_workspace(ws)
            await ws.channel_manager.start_all()
            assert await ws.channel_manager.get_channel(KEY) is None
        await loader.activate_plugin_unlocked(KEY)
        return record

    def mailbox(channel):
        return network / str(channel.channel_process.health_snapshot()["pid"])

    case = NS(
        loader=loader,
        registry=registry,
        source=source,
        network=network,
        manifest=manifest,
        workspaces=workspaces,
        workspace=workspace,
        activate=activate,
        mailbox=mailbox,
    )
    yield case
    try:
        if loader.get_loaded_plugin(KEY) is not None:
            await loader.unload_plugin(KEY)
        for ws in workspaces:
            manager = getattr(ws, "channel_manager", None)
            if manager is not None:
                await manager.stop_all()
    finally:
        PluginRegistry._instance = previous


def rows(work, kind=None):
    ledger = work / "ledger.jsonl"
    records = (
        [json.loads(line) for line in ledger.read_text().splitlines()]
        if ledger.exists()
        else []
    )
    return [row for row in records if kind is None or row["kind"] == kind]


def consumers(network):
    """Count normal Driver instances; probe imports never construct one."""
    return [
        path
        for path in network.iterdir()
        if path.is_dir() and rows(path, "driver-constructed")
    ]


def emit(work, event):
    value = {"kind": "message", "value": event} if KEY == "feishu" else event
    with (work / "inbox.jsonl").open("a") as stream:
        stream.write(json.dumps(value) + "\n")


def sent(work):
    return (
        rows(work, "create")
        if KEY == "feishu"
        else [r for r in rows(work, "http") if r["payload"]]
    )


@pytest.mark.asyncio
async def test_loader_two_workspaces_real_queue_acl_session_and_reply(
    framework,
):
    from qwenpaw.app.channels.access_control import get_access_control_store

    case = framework
    a = await case.workspace(
        "agent-a",
        access_control_group=True,
        share_session_in_group=True,
    )
    b = await case.workspace(
        "agent-b",
        access_control_group=True,
        share_session_in_group=True,
    )
    principal = "ou_alice" if KEY == "feishu" else "ding1234"
    get_access_control_store(a.workspace_dir).add_to_whitelist(KEY, principal)
    get_access_control_store(b.workspace_dir).add_to_blacklist(KEY, principal)
    record = await case.activate()
    assert record.status == "active" and record.enabled
    channels = [await ws.channel_manager.get_channel(KEY) for ws in (a, b)]
    assert all(ch is not None for ch in channels)
    identities = [ch._launch_spec.instance_id for ch in channels]
    assert identities == [
        "channel:"
        + hashlib.sha256(
            (str(ws.workspace_dir.resolve()) + "\0" + KEY).encode(),
        ).hexdigest()
        for ws in (a, b)
    ]
    assert len(set(identities)) == 2
    pids = [ch.channel_process.health_snapshot()["pid"] for ch in channels]
    assert len(set(pids)) == 2 and os.getpid() not in pids
    for ch in channels:
        spec = ch._launch_spec
        assert (
            spec.python_executable == sys.executable and spec.generation == 1
        )
        assert (
            "python_executable" not in spec.config
            and "generation" not in spec.config
        )
        work = case.mailbox(ch)
        await native.eventually(lambda work=work: rows(work, "connected"))
        origins = rows(work, "origins")[0]["files"]
        assert KEY + ".driver" in origins
        assert all(
            Path(path).is_relative_to(case.source / KEY)
            for path in origins.values()
        )
        emit(work, native.message("shared", group=True))
    await asyncio.wait_for(a.started.wait(), 8)
    await native.eventually(
        lambda: all(sent(case.mailbox(ch)) for ch in channels),
    )
    assert len(a.requests) == 1 and b.requests == []
    assert a.agent_pids == [os.getpid()]
    request = a.requests[0]
    assert request.channel == KEY and request.user_id == "group"
    assert request.session_id and request.input[0].content[0].text == "hello"
    reply = sent(case.mailbox(channels[0]))[0]
    if KEY == "feishu":
        assert reply["receive_id"] == "oc_room"
        assert (
            json.loads(reply["content"])["zh_cn"]["content"][0][0]["text"]
            == "answer:agent-a"
        )
    else:
        assert reply["url"] == native.WEBHOOK
        assert reply["payload"]["markdown"]["text"].strip() == "answer:agent-a"
    assert reply["pid"] == pids[0]
    assert len(await a.chat_manager.list_chats(channel=KEY)) == 1
    assert await b.chat_manager.list_chats(channel=KEY) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gate",
    [
        "global",
        "disabled",
        "absent",
        "missing_artifact",
        "load_all_disabled",
        "environment",
    ],
)
async def test_closed_activation_gate_never_spawns(
    framework,
    gate,
    monkeypatch,
):
    if gate == "environment":
        monkeypatch.setenv("QWENPAW_ENABLED_CHANNELS", "console")
    ws = await framework.workspace(
        "gated",
        enabled=gate != "disabled",
        configured=gate != "absent",
    )
    if gate in {"missing_artifact", "load_all_disabled"}:
        from qwenpaw.app.channels.manager import ChannelManager

        if gate == "load_all_disabled":
            await framework.loader.load_all_plugins(
                configs={KEY: {"enabled": False}},
                activate=True,
            )
        # Runtime selection exists before any catalog row; no builtin fallback.
        manager = ChannelManager.from_config(
            ws.stream_query,
            ws._config,
            workspace_dir=ws.workspace_dir,
        )
        ws.channel_manager = manager
        manager.set_workspace(ws)
        await manager.start_all()
    else:
        await framework.activate(global_enabled=gate != "global")
    assert await ws.channel_manager.get_channel(KEY) is None
    assert not consumers(framework.network)
    assert not channel_leases(framework.registry)
    assert not any(
        lease.key.kind == "preparation"
        for lease in framework.registry.runtime_owners.leases()
    )
    assert all(
        not psutil.pid_exists(int(path.name))
        for path in framework.network.iterdir()
        if path.is_dir()
    )
    assert not any(
        rows(path, "connected") for path in framework.network.iterdir()
    )
    if gate in {"global", "missing_artifact", "load_all_disabled"}:
        assert not list(framework.network.iterdir())


@pytest.mark.asyncio
async def test_stop_receipt_reaps_child_and_restart_retains_stable_identity(
    framework,
):
    ws = await framework.workspace("stable")
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    spec = old._launch_spec
    pid = old.channel_process.health_snapshot()["pid"]
    receipt = await manager.stop_one(KEY)
    assert receipt.stopped and receipt.exited and receipt.returncode == 0
    assert (
        receipt.instance_id == spec.instance_id
        and receipt.generation == spec.generation
    )
    assert not receipt.forced and receipt.residual == ()
    assert not psutil.pid_exists(pid)
    await manager.stop_all()
    # A new manager for the same stable workspace cannot reset generation.
    from qwenpaw.app.channels.manager import ChannelManager

    new = ChannelManager([])
    new._process = ws.stream_query
    new.set_workspace(ws)
    await new.start_all()
    ws.channel_manager = new
    handle = await new.start_one(KEY, ws._config)
    assert handle.channel._launch_spec.instance_id == spec.instance_id
    assert handle.channel._launch_spec.generation > spec.generation
    assert handle.channel.channel_process.health_snapshot()["pid"] != pid
    assert (await new.stop_one(KEY)).stopped


@pytest.mark.asyncio
async def test_unknown_outbound_never_sends_agent_reply_twice(framework):
    ws = await framework.workspace("unknown")
    await framework.activate()
    ch = await ws.channel_manager.get_channel(KEY)
    work = framework.mailbox(ch)
    await native.eventually(lambda work=work: rows(work, "connected"))
    (work / "send-mode").write_text(
        "unknown" if KEY == "feishu" else "webhook-unknown",
    )
    emit(work, native.message("unknown-result"))
    await asyncio.wait_for(ws.started.wait(), 8)
    await native.eventually(lambda: sent(work))
    # Queue metrics provide a completion barrier; no timing sleep masks retry.
    await native.eventually(
        lambda: not ws.task_tracker._runs
        or all(run.task.done() for run in ws.task_tracker._runs.values()),
    )
    assert len(ws.requests) == len(sent(work)) == 1


@pytest.mark.asyncio
async def test_lost_ack_retry_commits_once_after_real_queue_put(framework):
    from workspace_admission_suite import batch

    ws = await framework.workspace("ack-loss")
    await framework.activate()
    manager = ws.channel_manager
    channel = await manager.get_channel(KEY)
    # Freeze queue allocation, not the queue/Manager operation itself.
    lock = manager._queue_manager._lock
    await lock.acquire()
    entered = asyncio.Event()

    async def admit(payload):
        entered.set()
        return await manager.enqueue_async(channel, payload, timeout=2)

    channel.set_enqueue_async(admit)
    packet = batch(channel, "lost-ack")
    # The fixture event must follow the selected platform identity.
    from dataclasses import replace

    packet = replace(
        packet,
        events=(replace(packet.events[0], channel_key=KEY),),
    )
    caller = asyncio.create_task(channel._event_batch(packet, None))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert "lost-ack" not in channel._accepted and not ws.requests
        caller.cancel()
    finally:
        lock.release()
    with pytest.raises(asyncio.CancelledError):
        await caller
    retry = await channel._event_batch(packet, None)
    assert retry["accepted_event_ids"] == []
    assert retry["duplicate_event_ids"] == ["lost-ack"]
    await asyncio.wait_for(ws.started.wait(), 5)
    assert len(ws.requests) == 1


@pytest.mark.asyncio
async def test_backlog_uses_old_owner_after_same_key_replacement(framework):
    ws = await framework.workspace("backlog")
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    queues = manager._queue_manager
    original_consumer = queues._consumer_fn
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_consumer(queue, *args):
        entered.set()
        await release.wait()
        await original_consumer(queue, *args)

    queues._consumer_fn = paused_consumer
    from qwenpaw.schemas import TextContent

    payload = {
        "session_id": "backlog-session",
        "sender_id": "ou_alice",
        "acl_sender_id": "ou_alice",
        "content_parts": [TextContent(text="old backlog")],
        "meta": {
            "session_id": "backlog-session",
            "user_id": "ou_alice",
            "debounce_key": "backlog-session",
            "feishu_receive_id": "ou_alice",
            "feishu_receive_id_type": "open_id",
            "session_webhook": (
                "https://oapi.dingtalk.com/robot/"
                "sendBySession?session=old-session"
            ),
            "conversation_id": "backlog-session",
            "conversation_type": "single",
        },
    }
    fresh_requests = []

    async def fresh_agent(request):
        fresh_requests.append(request)
        if False:
            yield None

    try:
        result = await manager.enqueue_async(old, payload)
        assert result.accepted
        await asyncio.wait_for(entered.wait(), 5)
        stopping = asyncio.create_task(manager.stop_one(KEY))
        await asyncio.sleep(0)
        assert not stopping.done() and await manager.get_channel(KEY) is old
        release.set()
        receipt = await asyncio.wait_for(stopping, 8)
        assert receipt.stopped
        manager._process = fresh_agent
        replacement = (await manager.start_one(KEY, ws._config)).channel
        assert replacement is not old
        assert (
            replacement._launch_spec.generation > old._launch_spec.generation
        )
        release.set()
        await asyncio.wait_for(ws.started.wait(), 5)
        assert len(ws.requests) == 1 and not fresh_requests
        assert ws.requests[0].input[0].content[0].text == "old backlog"
    finally:
        release.set()
        current = await manager.get_channel(KEY)
        if current is not None and current is not old:
            assert (await manager.stop_one(KEY)).stopped


@pytest.mark.asyncio
async def test_factory_replacement_cannot_overlap_process_owners(framework):
    ws = await framework.workspace("factory-replacement")
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    pid = old.channel_process.health_snapshot()["pid"]
    await manager.replace_channel(KEY, ws._config)
    replacement = await manager.get_channel(KEY)
    assert replacement is not old and not psutil.pid_exists(pid)
    assert replacement._launch_spec.instance_id == old._launch_spec.instance_id
    assert replacement._launch_spec.generation > old._launch_spec.generation
    assert [ch for ch in manager.channels if ch.channel == KEY] == [
        replacement,
    ]
    assert len(consumers(framework.network)) == 2
    report = await framework.loader.unload_plugin(KEY)
    assert report.quiescent and report.clean


@pytest.mark.asyncio
async def test_stop_wakes_capacity_wait_with_negative_ack_and_no_commit(
    framework,
):
    from workspace_admission_suite import batch
    from dataclasses import replace

    ws = await framework.workspace("stop-admission")
    await framework.activate()
    manager = ws.channel_manager
    channel = await manager.get_channel(KEY)
    queues = manager._queue_manager
    queues._queue_maxsize = 1
    entered, release = asyncio.Event(), asyncio.Event()
    original_consumer = queues._consumer_fn

    async def paused_consumer(queue, *args):
        entered.set()
        await release.wait()
        await original_consumer(queue, *args)

    queues._consumer_fn = paused_consumer
    packet = batch(channel, "capacity-stop")
    packet = replace(
        packet,
        events=(replace(packet.events[0], channel_key=KEY),),
    )
    first = {
        "session_id": "session-one",
        "sender_id": "ou_alice",
        "content_parts": [],
        "meta": {
            "session_id": "session-one",
            "user_id": "ou_alice",
            "debounce_key": "session-one",
            "feishu_receive_id": "ou_alice",
            "feishu_receive_id_type": "open_id",
            "session_webhook": (
                "https://oapi.dingtalk.com/robot/"
                "sendBySession?session=old-session"
            ),
            "conversation_id": "session-one",
            "conversation_type": "single",
        },
    }
    admit_entered = asyncio.Event()

    async def admit(payload):
        admit_entered.set()
        return await manager.enqueue_async(channel, payload, timeout=5)

    channel.set_enqueue_async(admit)
    try:
        assert (await manager.enqueue_async(channel, first)).accepted
        await asyncio.wait_for(entered.wait(), 5)
        task = asyncio.create_task(channel._event_batch(packet, None))
        await asyncio.wait_for(admit_entered.wait(), 5)
        stopping = asyncio.create_task(manager.stop_one(KEY))
        ack = await asyncio.wait_for(task, 1)
        assert ack["accepted_event_ids"] == []
        assert ack["rejected_events"] == [
            {
                "event_id": "capacity-stop",
                "reason_code": "CHANNEL_STOPPING",
                "retryable": True,
            },
        ]
        assert "capacity-stop" not in channel._accepted
        assert len(next(iter(queues._queues.values())).queue._queue) == 1
        assert not stopping.done()
        release.set()
        receipt = await asyncio.wait_for(stopping, 8)
        assert receipt.stopped and receipt.exited
    finally:
        release.set()


@pytest.mark.asyncio
async def test_existing_builtin_owner_refuses_process_projection(framework):
    from qwenpaw.app.channels.console import ConsoleChannel
    from qwenpaw.app.channels.manager import ChannelManager

    ws = await framework.workspace("builtin-owner")
    # A real in-process channel stands in the official key's existing owner.
    legacy = ConsoleChannel(ws.stream_query, enabled=True, bot_prefix="")
    legacy.channel = KEY
    manager = ChannelManager([legacy])
    manager.set_workspace(ws)
    manager._process = ws.stream_query
    ws.channel_manager = manager
    await manager.start_all()
    record = await framework.loader.load_plugin(
        framework.manifest,
        framework.source,
        {"enabled": True},
        activate=True,
    )
    assert record.status == "failed"
    assert any(
        "CHANNEL_ALREADY_OWNED" in diagnostic
        for diagnostic in record.diagnostics
    )
    assert manager.channels == [legacy]
    assert not consumers(framework.network)
    assert not any(
        rows(path, "connected") for path in framework.network.iterdir()
    )
    assert not any(
        lease.key.kind == "preparation"
        for lease in framework.registry.runtime_owners.leases()
    )


@pytest.mark.asyncio
async def test_stale_projection_binding_cannot_unload_live_replacement(
    framework,
):
    ws = await framework.workspace("replacement-unload")
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    assert (await manager.stop_one(KEY)).stopped
    replacement = (await manager.start_one(KEY, ws._config)).channel
    pid = replacement.channel_process.health_snapshot()["pid"]
    try:
        report = await framework.loader.unload_plugin(KEY)
        assert not report.quiescent and not report.clean
        assert framework.loader.get_loaded_plugin(KEY) is not None
        assert framework.registry.get_channel_catalog_entry(KEY) is not None
        assert framework.loader.lifecycle.get_instance(
            KEY,
        ).has_runtime_ledger()
        assert (
            await manager.get_channel(KEY) is replacement
            and replacement is not old
        )
        assert replacement.channel_process.health_snapshot()["pid"] == pid
        assert psutil.pid_exists(pid)
    finally:
        assert (await manager.stop_one(KEY)).stopped
    report = await framework.loader.unload_plugin(KEY)
    assert report.clean and report.quiescent
    assert framework.loader.get_loaded_plugin(KEY) is None
    assert framework.registry.get_channel_catalog_entry(KEY) is None
    assert not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_cancel_before_manager_binding_releases_unstarted_owner(
    framework,
    monkeypatch,
):
    from qwenpaw.app.channels.manager import ChannelManager

    ws = await framework.workspace("cancel-before-binding")
    await framework.loader.load_plugin(
        framework.manifest,
        framework.source,
        {"enabled": True},
        activate=False,
    )
    manager = ChannelManager.from_config(
        ws.stream_query,
        ws._config,
        workspace_dir=ws.workspace_dir,
    )
    ws.channel_manager = manager
    manager.set_workspace(ws)
    await manager.start_all()
    allocated = asyncio.Event()
    reserve = framework.registry.runtime_owners.reserve

    def allocate(*args, **kwargs):
        lease = reserve(*args, **kwargs)
        if lease.key.kind == "channel":
            allocated.set()
        return lease

    monkeypatch.setattr(
        framework.registry.runtime_owners,
        "reserve",
        allocate,
    )
    await manager._lock.acquire()
    task = asyncio.create_task(manager.start_one(KEY, ws._config))
    try:
        await asyncio.wait_for(allocated.wait(), 2)
        assert channel_leases(framework.registry)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        manager._lock.release()
    try:
        assert not channel_leases(framework.registry)
        assert not list(framework.network.iterdir())
        assert await manager.get_channel(KEY) is None
        replacement = (await manager.start_one(KEY, ws._config)).channel
        assert replacement.channel_process.health_snapshot()["pid"]
        assert (await manager.stop_one(KEY)).stopped
    finally:
        await framework.registry.runtime_owners.stop_all(KEY)


if KEY == "dingtalk":

    @pytest.mark.asyncio
    async def test_forced_network_close_reports_real_process_exit(framework):
        ws = await framework.workspace("forced-close")
        await framework.activate()
        channel = await ws.channel_manager.get_channel(KEY)
        spec = channel._launch_spec
        pid = channel.channel_process.health_snapshot()["pid"]
        work = framework.mailbox(channel)
        (work / "send-mode").write_text("close-block")
        receipt = await asyncio.wait_for(ws.channel_manager.stop_one(KEY), 6)
        assert receipt.stopped and receipt.exited and receipt.forced
        assert receipt.returncode is not None and receipt.returncode != 0
        assert receipt.instance_id == spec.instance_id
        assert receipt.generation == spec.generation and receipt.residual == ()
        assert not psutil.pid_exists(pid)
