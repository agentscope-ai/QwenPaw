# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-import
"""C3 ownership and draining contracts, with real workers and queues."""

import asyncio

import psutil
import pytest

from ownership_helpers import channel_leases, channel_owner, channel_resources

from workspace_runtime_suite import (
    KEY,
    framework as _runtime_framework,
    native,
    emit,
    rows,
    sent,
    consumers,
)

framework = _runtime_framework


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_generic_owner_stop_uses_complete_manager_drain(
    framework,
    monkeypatch,
    timeout,
):
    """The ownership adapter must await business work before process exit."""
    import qwenpaw.app.channels.manager as manager_module

    if timeout:
        monkeypatch.setattr(manager_module, "_CHANNEL_DRAIN_TIMEOUT", 0.02)
    ws = await framework.workspace("generic-owner-stop")
    entered, release = asyncio.Event(), asyncio.Event()
    original_agent = ws.stream_query

    async def agent(request):
        entered.set()
        await release.wait()
        async for output in original_agent(request):
            yield output

    ws.stream_query = agent
    await framework.activate()
    channel = await ws.channel_manager.get_channel(KEY)
    owners = framework.registry.runtime_owners
    (held,) = channel_leases(framework.registry)
    assert owners.resource(held) is channel
    assert held.instance_id == channel._launch_spec.instance_id
    assert held.generation == channel._launch_spec.generation
    assert held.code_root == channel._launch_spec.code_root
    pid = channel.channel_process.health_snapshot()["pid"]
    work = framework.mailbox(channel)
    await native.eventually(lambda: rows(work, "connected"))
    emit(work, native.message("generic-owner-stop"))
    await asyncio.wait_for(entered.wait(), 5)
    stopping = asyncio.create_task(owners.stop_all(KEY))
    try:
        if timeout:
            receipts = await asyncio.wait_for(stopping, 2)
            assert len(receipts) == 1 and not receipts[0].stopped
            assert owners.leases(KEY) == (held,)
            assert owners.resource(held) is channel
        else:
            for _ in range(10):
                await asyncio.sleep(0)
            assert not stopping.done()
        assert psutil.pid_exists(pid) and not rows(work, "closed")
        assert await ws.channel_manager.get_channel(KEY) is channel
        release.set()
        if timeout:
            await native.eventually(lambda: sent(work))
            receipts = await asyncio.wait_for(owners.stop_all(KEY), 8)
        else:
            receipts = await asyncio.wait_for(stopping, 8)
        assert len(receipts) == 1 and receipts[0].stopped
        assert len(ws.requests) == len(sent(work)) == 1
        assert not psutil.pid_exists(pid) and not owners.leases(KEY)
        assert owners.resource(held) is None
        assert await ws.channel_manager.get_channel(KEY) is None
    finally:
        release.set()
        await asyncio.gather(stopping, return_exceptions=True)


@pytest.mark.asyncio
async def test_stop_waits_for_inflight_reply_before_reaping_owner(framework):
    """Stopping before Agent output completes must not kill its transport."""
    ws = await framework.workspace("inflight-stop")
    entered, release = asyncio.Event(), asyncio.Event()
    original_agent = ws.stream_query

    async def agent(request):
        entered.set()
        await release.wait()
        async for output in original_agent(request):
            yield output

    ws.stream_query = agent
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    pid = old.channel_process.health_snapshot()["pid"]
    work = framework.mailbox(old)
    await native.eventually(lambda: rows(work, "connected"))
    emit(work, native.message("inflight-stop"))
    await asyncio.wait_for(entered.wait(), 5)
    stopping = asyncio.create_task(manager.stop_one(KEY))
    try:
        # Loop barriers expose immediate-stop behavior without elapsed sleeps.
        for _ in range(10):
            await asyncio.sleep(0)
        assert not stopping.done(), "stop must await the accepted Agent run"
        assert await manager.get_channel(KEY) is old and psutil.pid_exists(pid)
        release.set()
        receipt = await asyncio.wait_for(stopping, 8)
        assert receipt.stopped and receipt.exited and not receipt.forced
        assert len(ws.requests) == len(sent(work)) == 1
        assert not psutil.pid_exists(pid)
        assert await manager.get_channel(KEY) is None
    finally:
        release.set()
        if not stopping.done():
            await asyncio.wait_for(stopping, 8)


def persist_agent(ws, monkeypatch, tmp_path):
    """Real root/agent config persistence; restart reads the updated file."""
    from qwenpaw.config import utils
    from qwenpaw.config.config import (
        AgentProfileConfig,
        AgentProfileRef,
        AgentsConfig,
        Config,
        save_agent_config,
    )

    monkeypatch.setattr(
        utils,
        "get_config_path",
        lambda: tmp_path / "config.json",
    )
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.setattr(utils, "_agent_config_cache", {})
    utils.save_config(
        Config(
            agents=AgentsConfig(
                profiles={
                    ws.agent_id: AgentProfileRef(
                        id=ws.agent_id,
                        workspace_dir=str(ws.workspace_dir),
                    ),
                },
            ),
        ),
    )
    config = AgentProfileConfig(
        id=ws.agent_id,
        name=ws.agent_id,
        channels=ws._config.channels,
    )
    save_agent_config(ws.agent_id, config)
    return config


@pytest.mark.asyncio
async def test_restart_factory_uses_latest_config_and_stale_token_is_harmless(
    framework,
    monkeypatch,
    tmp_path,
):
    from qwenpaw.config.config import save_agent_config

    ws = await framework.workspace("restart")
    config = persist_agent(ws, monkeypatch, tmp_path)
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    stale = await manager.start_one(KEY, ws._config)
    pid = old.channel_process.health_snapshot()["pid"]
    platform_config = getattr(config.channels, KEY)
    setattr(
        platform_config,
        "app_id" if KEY == "feishu" else "client_id",
        "changed-id",
    )
    save_agent_config(ws.agent_id, config)
    result = await manager.restart_channel(KEY)
    fresh = await manager.get_channel(KEY)
    assert result["status"] == "restarted" and fresh is not old
    assert fresh._launch_spec.instance_id == old._launch_spec.instance_id
    assert fresh._launch_spec.generation > old._launch_spec.generation
    assert (
        fresh._launch_spec.config["app_id" if KEY == "feishu" else "client_id"]
        == "changed-id"
    )
    assert not psutil.pid_exists(pid)
    assert (await manager.stop_one(KEY, expected=stale)).stopped
    assert await manager.get_channel(KEY) is fresh
    new_pid = fresh.channel_process.health_snapshot()["pid"]
    assert psutil.pid_exists(new_pid)
    # Canonical lifecycle registration follows legitimate factory replacement.
    report = await framework.loader.unload_plugin(KEY)
    assert report.clean and report.quiescent
    assert await manager.get_channel(KEY) is None
    assert not psutil.pid_exists(new_pid)


@pytest.mark.asyncio
async def test_disabled_workspace_restart_stops_without_replacement(
    framework,
    monkeypatch,
    tmp_path,
):
    from qwenpaw.config.config import save_agent_config

    ws = await framework.workspace("disable")
    config = persist_agent(ws, monkeypatch, tmp_path)
    await framework.activate()
    old = await ws.channel_manager.get_channel(KEY)
    pid = old.channel_process.health_snapshot()["pid"]
    getattr(config.channels, KEY).enabled = False
    save_agent_config(ws.agent_id, config)
    await ws.channel_manager.restart_channel(KEY)
    assert await ws.channel_manager.get_channel(KEY) is None
    assert not psutil.pid_exists(pid)
    assert len(consumers(framework.network)) == 1
    assert (await framework.loader.unload_plugin(KEY)).quiescent


@pytest.mark.asyncio
async def test_drain_timeout_preserves_accepted_work_and_owner_for_retry(
    framework,
    monkeypatch,
):
    import qwenpaw.app.channels.manager as manager_module

    monkeypatch.setattr(manager_module, "_CHANNEL_DRAIN_TIMEOUT", 0.05)
    ws = await framework.workspace("blocked")
    entered, release = asyncio.Event(), asyncio.Event()
    original_agent = ws.stream_query

    async def agent(request):
        entered.set()
        await release.wait()
        async for output in original_agent(request):
            yield output

    ws.stream_query = agent
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    pid = old.channel_process.health_snapshot()["pid"]
    work = framework.mailbox(old)
    await native.eventually(lambda: rows(work, "connected"))
    emit(work, native.message("blocked"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        receipt = await asyncio.wait_for(manager.stop_one(KEY), 1)
        assert (
            not receipt.stopped
        ), "drain timeout must refuse destructive stop"
        assert await manager.get_channel(KEY) is old
        assert psutil.pid_exists(pid) and not rows(work, "closed")
        assert (
            channel_owner(framework.registry, old._launch_spec.instance_id)
            is old
        )
        with pytest.raises(Exception):
            await manager.replace_channel(KEY, ws._config)
        assert len(consumers(framework.network)) == 1
        assert not ws.requests and ws.task_tracker._runs
        release.set()
        await native.eventually(lambda: sent(work))
        assert len(ws.requests) == 1
        assert (await manager.stop_one(KEY)).stopped
    finally:
        release.set()


@pytest.mark.asyncio
async def test_start_all_is_idempotent_preserving_live_queue_and_process(
    framework,
):
    ws = await framework.workspace("start-twice")
    await framework.activate()
    manager = ws.channel_manager
    channel = await manager.get_channel(KEY)
    queue = manager._queue_manager
    pid = channel.channel_process.health_snapshot()["pid"]
    await manager.start_all()
    assert manager._queue_manager is queue
    assert await manager.get_channel(KEY) is channel
    assert channel.channel_process.health_snapshot()["pid"] == pid
    assert len(consumers(framework.network)) == 1


@pytest.mark.asyncio
async def test_queue_drain_covers_dequeued_batch_and_preserves_it_on_timeout():
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    entered, release = asyncio.Event(), asyncio.Event()
    received = []

    async def consume(queue, *_args):
        await release.wait()
        batch = [await queue.get(), queue.get_nowait()]
        entered.set()
        await finished.wait()
        received.extend(batch)
        for _ in batch:
            queue.task_done()
        await asyncio.Event().wait()

    finished = asyncio.Event()
    queues = UnifiedQueueManager(consume)
    try:
        assert (await queues.admit(KEY, "batch", 20, "first")).accepted
        assert (await queues.admit(KEY, "batch", 20, "second")).accepted
        release.set()
        await asyncio.wait_for(entered.wait(), 1)
        assert not await queues.drain(KEY, timeout=0.02)
        assert not received and queues._queues
        finished.set()
        assert await queues.drain(KEY, timeout=1)
        assert received == ["first", "second"]
    finally:
        release.set()
        finished.set()
        await queues.stop_all()


async def real_manager_case(
    framework,
    monkeypatch,
    tmp_path,
    *,
    agent_id="real-agent",
    activate=True,
):
    """Use actual Workspace services with deterministic Agent output."""
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.app.workspace.workspace import Workspace
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.schemas import Message, RunStatus, TextContent

    template = await framework.workspace(agent_id)
    framework.workspaces.remove(template)
    persist_agent(template, monkeypatch, tmp_path)
    manager = MultiAgentManager()
    framework.registry.set_workspace_manager(manager)
    framework.registry.projector = WorkspaceProjector(
        live_workspaces=lambda: list(manager.agents.values()),
    )
    created = []
    entered, release = asyncio.Event(), asyncio.Event()
    release.set()

    def create(agent_id, workspace_dir):
        ws = Workspace(agent_id, workspace_dir)
        ws.requests = []

        async def agent(request):
            ws.requests.append(request)
            entered.set()
            await release.wait()
            yield Message(
                object="message",
                status=RunStatus.Completed,
                role="assistant",
                content=[TextContent(text="actual workspace answer")],
            )

        ws.stream_query = agent
        created.append(ws)
        framework.workspaces.append(ws)
        return ws

    monkeypatch.setattr(manager, "_create_workspace", create)
    await framework.loader.load_plugin(
        framework.manifest,
        framework.source,
        {"enabled": True},
        activate=activate,
    )
    return manager, created, entered, release


@pytest.mark.asyncio
async def test_actual_workspace_reload_drains_before_factory_handoff(
    framework,
    monkeypatch,
    tmp_path,
):
    manager, created, entered, release = await real_manager_case(
        framework,
        monkeypatch,
        tmp_path,
    )
    old = await manager.get_agent("real-agent")
    old_channel = await old.channel_manager.get_channel(KEY)
    old_pid = old_channel.channel_process.health_snapshot()["pid"]
    work = framework.mailbox(old_channel)
    await native.eventually(lambda: rows(work, "connected"))
    release.clear()
    emit(work, native.message("reload-inflight"))
    await asyncio.wait_for(entered.wait(), 5)
    reload_task = asyncio.create_task(manager.reload_agent("real-agent"))
    try:
        await native.eventually(
            lambda: len(created) == 2 and created[1]._started,
        )
        candidate = created[1]
        assert manager.get_loaded_agent("real-agent") is old
        assert await candidate.channel_manager.get_channel(KEY) is None
        assert len(consumers(framework.network)) == 1
        assert psutil.pid_exists(old_pid)
        release.set()
        assert await asyncio.wait_for(reload_task, 12)
        replacement = manager.get_loaded_agent("real-agent")
        channel = await replacement.channel_manager.get_channel(KEY)
        assert replacement is candidate and channel is not old_channel
        assert (
            channel._launch_spec.instance_id
            == old_channel._launch_spec.instance_id
        )
        assert (
            channel._launch_spec.generation
            > old_channel._launch_spec.generation
        )
        assert not psutil.pid_exists(old_pid)
        assert len(sent(work)) == 1 and len(old.requests) == 1
        assert not candidate.requests
        await manager.stop_all()
        assert not channel_leases(framework.registry)
    finally:
        release.set()
        if not reload_task.done():
            await asyncio.wait_for(reload_task, 12)
        await manager.stop_all()


def pause_preparation(manager, monkeypatch, *, priority):
    """Add one real service that exposes a deterministic startup gate."""
    from qwenpaw.app.workspace.service_manager import ServiceDescriptor

    entered, release = asyncio.Event(), asyncio.Event()
    create = manager._create_workspace

    def create_paused(agent_id, workspace_dir):
        ws = create(agent_id, workspace_dir)

        async def gate(_ws, _service, _publish):
            entered.set()
            await release.wait()

        ws._service_manager.register(
            ServiceDescriptor(
                name="test_prepare_gate",
                post_init=gate,
                priority=priority,
                concurrent_init=False,
            ),
        )
        return ws

    monkeypatch.setattr(manager, "_create_workspace", create_paused)
    return entered, release


@pytest.mark.asyncio
async def test_unpublished_workspace_is_covered_by_unload_barrier(
    framework,
    monkeypatch,
    tmp_path,
):
    manager, created, _entered, _release = await real_manager_case(
        framework,
        monkeypatch,
        tmp_path,
        activate=False,
    )
    prepare_entered, prepare_release = pause_preparation(
        manager,
        monkeypatch,
        priority=35,
    )
    startup = asyncio.create_task(manager.get_agent("real-agent"))
    try:
        await asyncio.wait_for(prepare_entered.wait(), 10)
        assert manager.get_loaded_agent("real-agent") is None
        await framework.loader.activate_plugin_unlocked(KEY)
        channel = await created[0].channel_manager.get_channel(KEY)
        assert (
            channel is not None
        ), "preparing workspace must participate in projection"
        pid = channel.channel_process.health_snapshot()["pid"]
        report = await framework.loader.unload_plugin(KEY)
        assert report.clean and report.quiescent and not psutil.pid_exists(pid)
        assert await created[0].channel_manager.get_channel(KEY) is None
        prepare_release.set()
        ws = await asyncio.wait_for(startup, 10)
        assert manager.get_loaded_agent("real-agent") is ws
        assert await ws.channel_manager.get_channel(KEY) is None
        assert len(consumers(framework.network)) == 1
    finally:
        prepare_release.set()
        if not startup.done():
            await asyncio.wait_for(startup, 10)
        await manager.stop_all()


@pytest.mark.asyncio
async def test_unrelated_console_stream_survives_selected_channel_restart(
    framework,
    monkeypatch,
    tmp_path,
):
    from qwenpaw.schemas import TextContent

    ws = await framework.workspace("console-restart")
    persist_agent(ws, monkeypatch, tmp_path)
    original_agent = ws.stream_query
    entered, release = asyncio.Event(), asyncio.Event()

    async def agent(request):
        if request.channel == "console":
            entered.set()
            await release.wait()
        async for output in original_agent(request):
            yield output

    ws.stream_query = agent
    await framework.activate()
    manager = ws.channel_manager
    console = await manager.get_channel("console")
    queue, _ = await ws.task_tracker.attach_or_start(
        "console-run",
        {
            "sender_id": "console-user",
            "content_parts": [TextContent(text="console survives")],
        },
        console.stream_one,
        owner=ws,
        channel_id="console",
    )
    await asyncio.wait_for(entered.wait(), 5)
    old = await manager.get_channel(KEY)
    try:
        await asyncio.wait_for(manager.restart_channel(KEY), 10)
        assert await manager.get_channel(KEY) is not old
        assert await ws.task_tracker.get_status("console-run") == "running"
        assert not release.is_set()
        release.set()
        output = await asyncio.wait_for(queue.get(), 5)
        assert "answer:console-restart" in output
    finally:
        release.set()
        await ws.task_tracker.wait_all_done(timeout=5)


@pytest.mark.asyncio
async def test_global_disable_and_enable_use_one_factory_owner(
    framework,
    monkeypatch,
    tmp_path,
):
    ws = await framework.workspace("global-toggle")
    persist_agent(ws, monkeypatch, tmp_path)
    await framework.activate()
    old = await ws.channel_manager.get_channel(KEY)
    pid = old.channel_process.health_snapshot()["pid"]
    report = await framework.loader.lifecycle.set_enabled(KEY, False)
    assert report.quiescent and report.clean
    assert await ws.channel_manager.get_channel(KEY) is None
    assert not psutil.pid_exists(pid)
    await framework.loader.lifecycle.set_enabled(KEY, True)
    fresh = await ws.channel_manager.get_channel(KEY)
    assert fresh is not None and fresh is not old
    assert fresh._launch_spec.instance_id == old._launch_spec.instance_id
    assert fresh._launch_spec.generation > old._launch_spec.generation
    assert len(consumers(framework.network)) == 2


def delay_platform_network(framework, *, offline=False):
    """Pause only the child SDK connection, leaving host/Worker untouched."""
    boundary = framework.source / KEY / "boundary.py"
    source = boundary.read_text()
    marker = (
        "    async def _connect(self):\n"
        if KEY == "feishu"
        else "    async def __aenter__(self):\n"
    )
    wait = (
        "        record('network-wait')\n"
        "        while not (work.parent / 'network-release').exists():\n"
        "            await asyncio.sleep(0.01)\n"
    )
    if offline:
        wait += (
            "        raise ConnectionError('controlled offline platform')\n"
        )
    assert marker in source
    boundary.write_text(source.replace(marker, marker + wait, 1))


@pytest.mark.asyncio
@pytest.mark.parametrize("offline", [False, True])
async def test_real_core_ready_console_serves_while_selected_sdk_waits(
    framework,
    monkeypatch,
    tmp_path,
    offline,
):
    from qwenpaw.schemas import TextContent

    delay_platform_network(framework, offline=offline)
    manager, _created, _entered, _release = await real_manager_case(
        framework,
        monkeypatch,
        tmp_path,
        agent_id="default",
        activate=False,
    )
    core_ready = asyncio.Event()
    result = await manager.start_all_configured_agents(
        on_core_ready=lambda _results: core_ready.set(),
    )
    assert core_ready.is_set() and result["default"]
    ws = manager.get_loaded_agent("default")
    activation = asyncio.create_task(
        framework.loader.activate_plugin_unlocked(KEY),
    )
    try:
        await native.eventually(
            lambda: any(
                rows(path, "network-wait")
                for path in framework.network.iterdir()
            ),
            # Audit, reaped probe and normal worker each retain their 8s limit.
            timeout=3 * framework.registry.channel_runtime.startup_timeout,
        )
        channel = await ws.channel_manager.get_channel(KEY)
        health = await channel.health_check()
        assert (
            health["platform_state"] == "connecting"
            and health["status"] == "unhealthy"
        )
        console = await ws.channel_manager.get_channel("console")
        output = [
            item
            async for item in console.stream_one(
                {
                    "sender_id": "console-user",
                    "content_parts": [TextContent(text="ready chat")],
                },
            )
        ]
        assert any("actual workspace answer" in item for item in output)
        assert not activation.done()
        (framework.network / "network-release").touch()
        if offline:
            from qwenpaw.plugins.workspace_projector import ProjectionError

            with pytest.raises(ProjectionError):
                await asyncio.wait_for(activation, 12)
        else:
            await asyncio.wait_for(activation, 12)
        if offline:
            assert await ws.channel_manager.get_channel(KEY) is None
            assert not channel_leases(framework.registry)
            record = framework.loader.get_loaded_plugin(KEY)
            assert record.status == "failed" and record.diagnostics
        else:
            assert (await channel.health_check())["status"] == "healthy"
    finally:
        (framework.network / "network-release").touch()
        if not activation.done():
            await asyncio.wait_for(activation, 12)
        await manager.stop_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_rejected_or_cancelled_reload_retains_old_owner_and_work(
    framework,
    monkeypatch,
    tmp_path,
    cancel,
):
    import qwenpaw.app.channels.manager as manager_module

    manager, created, entered, release = await real_manager_case(
        framework,
        monkeypatch,
        tmp_path,
    )
    old = await manager.get_agent("real-agent")
    channel = await old.channel_manager.get_channel(KEY)
    work = framework.mailbox(channel)
    pid = channel.channel_process.health_snapshot()["pid"]
    await native.eventually(lambda: rows(work, "connected"))
    release.clear()
    emit(work, native.message("reject-reload"))
    await asyncio.wait_for(entered.wait(), 5)
    if not cancel:
        monkeypatch.setattr(manager_module, "_CHANNEL_DRAIN_TIMEOUT", 0.05)
    reloading = asyncio.create_task(manager.reload_agent("real-agent"))
    try:
        if cancel:
            await native.eventually(
                lambda: len(created) == 2 and created[1]._started,
            )
            reloading.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reloading
        else:
            assert not await asyncio.wait_for(reloading, 10)
        assert manager.get_loaded_agent("real-agent") is old
        assert await old.channel_manager.get_channel(KEY) is channel
        assert (
            psutil.pid_exists(pid) and len(consumers(framework.network)) == 1
        )
        assert channel_resources(framework.registry) == [channel]
        assert await old.task_tracker.has_active_tasks()
        release.set()
        await native.eventually(lambda: sent(work))
        assert len(old.requests) == len(sent(work)) == 1
    finally:
        release.set()
        if not reloading.done():
            await asyncio.wait_for(reloading, 12)
        await manager.stop_all()


@pytest.mark.asyncio
async def test_stop_during_sdk_startup_reaps_before_next_generation(framework):
    delay_platform_network(framework)
    ws = await framework.workspace("stop-starting")
    activating = asyncio.create_task(framework.activate())
    try:
        await native.eventually(
            lambda: any(
                rows(path, "network-wait")
                for path in framework.network.iterdir()
            ),
            # Audit, reaped probe and normal worker each retain their 8s limit.
            timeout=3 * framework.registry.channel_runtime.startup_timeout,
        )
        old = await ws.channel_manager.get_channel(KEY)
        pid = old.channel_process.health_snapshot()["pid"]
        assert channel_resources(framework.registry) == [old]
        receipt = await asyncio.wait_for(ws.channel_manager.stop_one(KEY), 5)
        assert receipt.stopped and receipt.exited
        await asyncio.wait_for(
            asyncio.gather(activating, return_exceptions=True),
            5,
        )
        assert not psutil.pid_exists(pid) and not channel_leases(
            framework.registry,
        )
        assert await ws.channel_manager.get_channel(KEY) is None
        assert len(consumers(framework.network)) == 1
    finally:
        (framework.network / "network-release").touch()
        await asyncio.wait_for(
            asyncio.gather(activating, return_exceptions=True),
            10,
        )


if KEY == "dingtalk":

    @pytest.mark.asyncio
    async def test_app_stop_retains_workspace_when_os_cannot_reap_child(
        framework,
        monkeypatch,
        tmp_path,
    ):
        manager, _created, _entered, _release = await real_manager_case(
            framework,
            monkeypatch,
            tmp_path,
        )
        ws = await manager.get_agent("real-agent")
        channel = await ws.channel_manager.get_channel(KEY)
        pid = channel.channel_process.health_snapshot()["pid"]
        work = framework.mailbox(channel)
        (work / "send-mode").write_text("close-unreapable")
        tree = channel.channel_process._tree
        signal = tree.signal
        monkeypatch.setattr(tree, "signal", lambda **_kwargs: None)
        try:
            with pytest.raises(Exception):
                await manager.stop_all()
            assert rows(work, "close-unreapable")
            assert manager.get_loaded_agent("real-agent") is ws
            assert await ws.channel_manager.get_channel(KEY) is channel
            assert (
                channel_owner(
                    framework.registry,
                    channel._launch_spec.instance_id,
                )
                is channel
            )
            assert psutil.pid_exists(pid)
            receipt = channel.last_stop_result
            assert not receipt.exited and "PROCESS_RUNNING" in receipt.residual
            with pytest.raises(Exception):
                await ws.channel_manager.replace_channel(KEY, ws.config)
            assert len(consumers(framework.network)) == 1
        finally:
            monkeypatch.setattr(tree, "signal", signal)
            (work / "close-release").touch()
            await manager.stop_all()
        assert (
            not psutil.pid_exists(pid)
            and manager.get_loaded_agent("real-agent") is None
        )


@pytest.mark.asyncio
async def test_unload_during_replacement_start_cannot_leave_new_owner(
    framework,
    monkeypatch,
    tmp_path,
):
    delay_platform_network(framework)
    (framework.network / "network-release").touch()
    ws = await framework.workspace("unload-replacement")
    persist_agent(ws, monkeypatch, tmp_path)
    await framework.activate()
    old = await ws.channel_manager.get_channel(KEY)
    old_pid = old.channel_process.health_snapshot()["pid"]
    (framework.network / "network-release").unlink()
    replacing = asyncio.create_task(ws.channel_manager.restart_channel(KEY))
    unloading = None
    try:
        await native.eventually(
            lambda: len(consumers(framework.network)) == 2,
            timeout=(
                framework.registry.channel_runtime.shutdown_timeout
                + framework.registry.channel_runtime.startup_timeout
            ),
        )
        fresh = await ws.channel_manager.get_channel(KEY)
        assert fresh is not old and not psutil.pid_exists(old_pid)
        work = framework.mailbox(fresh)
        await native.eventually(lambda: rows(work, "network-wait"))
        new_pid = fresh.channel_process.health_snapshot()["pid"]
        unloading = asyncio.create_task(framework.loader.unload_plugin(KEY))
        # Manager cancellation must settle startup before unregistering owner.
        report = await asyncio.wait_for(unloading, 8)
        assert report.quiescent and report.clean
        outcome = await asyncio.gather(replacing, return_exceptions=True)
        assert (
            outcome  # Replacement may be cancelled by the authorized unload.
        )
        assert await ws.channel_manager.get_channel(KEY) is None
        assert not channel_leases(framework.registry)
        assert not psutil.pid_exists(new_pid)
    finally:
        (framework.network / "network-release").touch()
        if not replacing.done():
            await asyncio.gather(replacing, return_exceptions=True)
        if unloading is not None and not unloading.done():
            await asyncio.wait_for(unloading, 8)


@pytest.mark.asyncio
async def test_replacement_drains_real_queued_and_dequeued_batch(framework):
    ws = await framework.workspace("batch-handoff")
    agent_entered, agent_release = asyncio.Event(), asyncio.Event()
    original_agent = ws.stream_query

    async def agent(request):
        agent_entered.set()
        await agent_release.wait()
        async for output in original_agent(request):
            yield output

    ws.stream_query = agent
    await framework.activate()
    manager = ws.channel_manager
    old = await manager.get_channel(KEY)
    work = framework.mailbox(old)
    pid = old.channel_process.health_snapshot()["pid"]
    queues = manager._queue_manager
    consume = queues._consumer_fn
    queue_entered, queue_release = asyncio.Event(), asyncio.Event()

    async def consumer(queue, *args):
        queue_entered.set()
        await queue_release.wait()
        await consume(queue, *args)

    queues._consumer_fn = consumer
    await native.eventually(lambda: rows(work, "connected"))
    for index, text in enumerate(("first", "second", "third")):
        content = (
            {"text": text} if KEY == "feishu" else {"text": {"content": text}}
        )
        emit(work, native.message(f"queued-{index}", content=content))
    await asyncio.wait_for(queue_entered.wait(), 5)
    await native.eventually(lambda: len(old._accepted) == 3)
    replacing = asyncio.create_task(manager.replace_channel(KEY, ws._config))
    try:
        for _ in range(10):
            await asyncio.sleep(0)
        assert not replacing.done() and psutil.pid_exists(pid)
        queue_release.set()
        await asyncio.wait_for(agent_entered.wait(), 5)
        assert not replacing.done() and psutil.pid_exists(pid)
        assert await manager.get_channel(KEY) is old
        agent_release.set()
        await asyncio.wait_for(replacing, 10)
        assert len(ws.requests) == len(sent(work)) == 1
        parts = ws.requests[0].input[0].content
        output = "\n".join(
            part.text
            for part in parts
            if getattr(part, "type", None) == "text"
        )
        assert all(text in output for text in ("first", "second", "third"))
        assert not psutil.pid_exists(pid)
        fresh = await manager.get_channel(KEY)
        assert (
            fresh is not old
            and fresh._launch_spec.generation > old._launch_spec.generation
        )
    finally:
        queue_release.set()
        agent_release.set()
        if not replacing.done():
            await asyncio.wait_for(replacing, 10)


@pytest.mark.asyncio
async def test_lazy_and_scheduled_startup_do_not_wait_on_each_other(
    framework,
    monkeypatch,
    tmp_path,
):
    manager, created, _entered, _release = await real_manager_case(
        framework,
        monkeypatch,
        tmp_path,
        activate=False,
    )
    lock = manager._operation_locks.setdefault("real-agent", asyncio.Lock())
    await lock.acquire()
    lazy = asyncio.create_task(manager.get_agent("real-agent"))
    await asyncio.sleep(0)
    scheduled = manager.schedule_agent_startup("real-agent")
    await asyncio.sleep(0)
    lock.release()
    try:
        ws, success = await asyncio.wait_for(
            asyncio.gather(lazy, scheduled),
            5,
        )
        assert success and manager.get_loaded_agent("real-agent") is ws
        assert len(created) == 1
    finally:
        lazy.cancel()
        scheduled.cancel()
        await asyncio.gather(lazy, scheduled, return_exceptions=True)
        await manager.stop_all()


@pytest.mark.asyncio
async def test_cancelled_enqueue_drain_restores_same_owner_admission(
    framework,
):
    from qwenpaw.schemas import TextContent

    ws = await framework.workspace("quiesce-cancel")
    await framework.activate()
    manager = ws.channel_manager
    channel = await manager.get_channel(KEY)
    queues = manager._queue_manager
    payload = {
        "sender_id": "console-user",
        "session_id": "console-pending",
        "content_parts": [TextContent(text="queued before quiesce")],
    }
    await queues._lock.acquire()
    manager.enqueue("console", payload)
    await native.eventually(lambda: manager._enqueue_tasks)
    quiescing = asyncio.create_task(manager.quiesce())
    try:
        await native.eventually(lambda: KEY in manager._paused_channels)
        quiescing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await quiescing
        queues._lock.release()
        assert await manager.get_channel(KEY) is channel
        assert manager._queue_manager is queues
        accepted = await manager.enqueue_async(
            channel,
            {
                "sender_id": "ou_alice",
                "session_id": "after-cancel",
                "content_parts": [],
            },
        )
        assert (
            accepted.accepted
        ), "cancelled drain must restore old owner's admission"
        await asyncio.wait_for(ws.started.wait(), 5)
        assert ws.requests[0].channel == "console"
    finally:
        if queues._lock.locked():
            queues._lock.release()
        if not quiescing.done():
            quiescing.cancel()
            await asyncio.gather(quiescing, return_exceptions=True)


async def assert_failed_startup_routes(manager):
    """Scheduled and bulk boot paths must not bless a failed retained owner."""
    from qwenpaw.exceptions import ConfigurationException
    from qwenpaw.app.agent_startup import AgentStartupStatus

    with pytest.raises(ConfigurationException, match="cleanup is incomplete"):
        await manager.get_agent("real-agent")
    assert not await manager.schedule_agent_startup("real-agent")
    assert (
        manager.get_agent_startup_status("real-agent")
        == AgentStartupStatus.FAILED
    )
    with pytest.raises(
        ConfigurationException,
        match="cleanup is incomplete",
    ):
        await manager.get_agent("real-agent")
    results = await manager.start_all_configured_agents()
    assert results == {"real-agent": False}
    assert (
        manager.get_agent_startup_status("real-agent")
        == AgentStartupStatus.FAILED
    )
    with pytest.raises(
        ConfigurationException,
        match="cleanup is incomplete",
    ):
        await manager.get_agent("real-agent")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop_failure",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                KEY != "dingtalk",
                reason="controlled socket close boundary",
            ),
        ),
    ],
)
async def test_cancel_before_publication_cleans_or_retains_actual_workspace(
    framework,
    monkeypatch,
    tmp_path,
    stop_failure,
):
    manager, created, _entered, _release = await real_manager_case(
        framework,
        monkeypatch,
        tmp_path,
        activate=False,
    )
    prepared, finish_prepare = pause_preparation(
        manager,
        monkeypatch,
        priority=100,
    )
    startup = asyncio.create_task(manager.get_agent("real-agent"))
    tree = signal = work = None
    try:
        await asyncio.wait_for(prepared.wait(), 10)
        await framework.loader.activate_plugin_unlocked(KEY)
        ws = created[0]
        channel = await ws.channel_manager.get_channel(KEY)
        pid = channel.channel_process.health_snapshot()["pid"]
        if stop_failure:
            work = framework.mailbox(channel)
            (work / "send-mode").write_text("close-unreapable")
            tree = channel.channel_process._tree
            signal = tree.signal
            monkeypatch.setattr(tree, "signal", lambda **_kwargs: None)
        await manager._lock.acquire()
        finish_prepare.set()
        await native.eventually(lambda: ws._started)
        assert manager.get_loaded_agent("real-agent") is None
        startup.cancel()
        manager._lock.release()
        with pytest.raises(asyncio.CancelledError):
            await startup
        if stop_failure:
            assert rows(work, "close-unreapable")
            assert manager.get_loaded_agent("real-agent") is ws
            assert psutil.pid_exists(pid) and len(created) == 1
            assert channel_resources(framework.registry) == [
                channel,
            ]
            assert "PROCESS_RUNNING" in channel.last_stop_result.residual
            await assert_failed_startup_routes(manager)
            assert (
                manager.get_loaded_agent("real-agent") is ws
                and len(created) == 1
            )
            assert psutil.pid_exists(pid)
        else:
            assert manager.get_loaded_agent("real-agent") is None
            assert not ws._started and not psutil.pid_exists(pid)
            assert not channel_leases(framework.registry)
            replacement = await manager.get_agent("real-agent")
            assert replacement is not ws and len(created) == 2
    finally:
        if manager._lock.locked():
            manager._lock.release()
        finish_prepare.set()
        if tree is not None:
            monkeypatch.setattr(tree, "signal", signal)
            (work / "close-release").touch()
        if not startup.done():
            startup.cancel()
        await asyncio.gather(startup, return_exceptions=True)
        await manager.stop_all()


@pytest.mark.asyncio
async def test_cancel_after_publication_preserves_published_workspace(
    framework,
    monkeypatch,
    tmp_path,
):
    delay_platform_network(framework)
    manager, created, _entered, _release = await real_manager_case(
        framework,
        monkeypatch,
        tmp_path,
    )
    startup = asyncio.create_task(manager.get_agent("real-agent"))
    try:
        await native.eventually(
            lambda: any(
                rows(path, "network-wait")
                for path in framework.network.iterdir()
            ),
            # Audit, reaped probe and normal worker each retain their 8s limit.
            timeout=3 * framework.registry.channel_runtime.startup_timeout,
        )
        ws = created[0]
        channel = await ws.channel_manager.get_channel(KEY)
        pid = channel.channel_process.health_snapshot()["pid"]
        assert manager.get_loaded_agent("real-agent") is ws
        startup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await startup
        assert await manager.get_agent("real-agent") is ws
        assert len(created) == 1 and psutil.pid_exists(pid)
        (framework.network / "network-release").touch()
        await native.eventually(
            lambda: rows(framework.mailbox(channel), "connected"),
        )
        assert await ws.channel_manager.get_channel(KEY) is channel
    finally:
        (framework.network / "network-release").touch()
        if not startup.done():
            startup.cancel()
        await asyncio.gather(startup, return_exceptions=True)
        await manager.stop_all()
