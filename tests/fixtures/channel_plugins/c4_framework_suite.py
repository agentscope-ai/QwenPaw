# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""C4 admission and observations through the actual Loader/Registry owner."""

from dataclasses import replace
import asyncio
import json

import pytest

from ownership_helpers import channel_leases

from workspace_runtime_suite import KEY, framework as runtime_framework, rows

framework = runtime_framework


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "dirty", "driver"])
async def test_failed_admission_never_projects_or_creates_consumer(
    framework,
    tmp_path,
    failure,
):
    from qwenpaw.plugins.execution.dependencies import repair_marker

    await framework.workspace("not-admitted")
    if failure == "missing":
        requirements = framework.source / "requirements.txt"
        requirements.write_text("c4-absent-sdk-admission>=1\n")
    elif failure == "dirty":
        site = tmp_path / "dirty-site"
        site.mkdir()
        repair_marker(site).write_text("incomplete previous install\n")
        framework.registry.channel_runtime = replace(
            framework.registry.channel_runtime,
            dependency_paths=(site,),
        )
    else:
        path = framework.source / KEY / "broken.py"
        path.write_text(
            "class Driver:\n"
            "    def bind(self, context): pass\n"
            "    def start(self, config): pass\n"
            "    async def stop(self): pass\n",
        )
        path = framework.source / "channel.json"
        descriptor = json.loads(path.read_text())
        descriptor["entrypoint"]["module"] = KEY + ".broken"
        path.write_text(json.dumps(descriptor))
    with pytest.raises(RuntimeError):
        await framework.activate()
    assert not channel_leases(framework.registry)
    assert not any(
        lease.key.kind == "preparation"
        for lease in framework.registry.runtime_owners.leases()
    )
    assert not any(
        rows(path, "connected") for path in framework.network.iterdir()
    )
    assert not any(getattr(ws, "requests", []) for ws in framework.workspaces)


@pytest.mark.asyncio
async def test_current_dependency_observation_survives_stale_owner_release(
    framework,
    tmp_path,
):
    from qwenpaw.plugins.dependency_usage import DependencyEnvironment

    from qwenpaw.plugins.ownership import RuntimeStopReceipt

    ws = await framework.workspace("dependency-owner")
    await framework.activate()
    old = await ws.channel_manager.get_channel(KEY)
    (old_lease,) = channel_leases(framework.registry)
    spec = old._launch_spec
    uses = framework.registry.dependency_usage.snapshot(None).uses
    assert any(not use.active and use.plugin_id == KEY for use in uses)
    observed = next(
        use for use in uses if use.origin == "runtime" and use.active
    )
    assert observed.instance_id == spec.instance_id
    assert observed.generation == spec.generation
    assert observed.snapshot.distributions
    generic = framework.registry.dependency_usage.snapshot(None).uses
    declarations = [use for use in generic if use.origin == "declaration"]
    runtimes = [use for use in generic if use.origin == "runtime"]
    assert len(declarations) == 1 and declarations[0].plugin_id == KEY
    assert declarations[0].environment is not None
    assert len(runtimes) == 1
    assert runtimes[0].instance_id == spec.instance_id
    assert runtimes[0].snapshot == observed.snapshot
    unrelated = DependencyEnvironment(
        spec.python_executable,
        (str(tmp_path / "independent-package-site"),),
        runtimes[0].snapshot.marker_environment,
    )
    assert not framework.registry.dependency_usage.snapshot(unrelated).uses
    assert (await ws.channel_manager.stop_one(KEY)).exited
    assert not any(
        use.origin == "runtime" and use.active
        for use in framework.registry.dependency_usage.snapshot(None).uses
    )
    await ws.channel_manager.start_one(KEY, ws._config)
    fresh = await ws.channel_manager.get_channel(KEY)
    assert fresh._launch_spec.generation > spec.generation
    assert not framework.registry.runtime_owners.release(
        old_lease,
        RuntimeStopReceipt(True),
    )
    active = [
        use
        for use in framework.registry.dependency_usage.snapshot(None).uses
        if use.origin == "runtime" and use.active
    ]
    assert (
        len(active) == 1
        and active[0].generation == fresh._launch_spec.generation
    )
    assert active[0].snapshot == fresh.channel_process.dependency_snapshot
    generic = [
        use
        for use in framework.registry.dependency_usage.snapshot(None).uses
        if use.origin == "runtime"
    ]
    assert (
        len(generic) == 1
        and generic[0].generation == fresh._launch_spec.generation
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    KEY != "dingtalk",
    reason="controlled async socket-close fixture",
)
async def test_failed_actual_stop_retains_dependency_observation(
    framework,
    monkeypatch,
):
    ws = await framework.workspace("failed-dependency-owner")
    await framework.activate()
    channel = await ws.channel_manager.get_channel(KEY)
    work = framework.mailbox(channel)
    (work / "send-mode").write_text("close-block")
    tree = channel.channel_process._tree
    signal = tree.signal
    monkeypatch.setattr(tree, "signal", lambda **_kwargs: None)
    try:
        receipt = await ws.channel_manager.stop_one(KEY)
        assert not receipt.exited
        active = [
            use
            for use in framework.registry.dependency_usage.snapshot(None).uses
            if use.origin == "runtime" and use.active
        ]
        assert len(active) == 1
        assert active[0].generation == channel._launch_spec.generation
        assert active[0].snapshot
        generic = [
            use
            for use in framework.registry.dependency_usage.snapshot(None).uses
            if use.origin == "runtime"
        ]
        assert (
            len(generic) == 1
            and generic[0].generation == channel._launch_spec.generation
        )
        assert generic[0].snapshot == active[0].snapshot
    finally:
        monkeypatch.setattr(tree, "signal", signal)
        (work / "close-release").touch()
        assert (await ws.channel_manager.stop_one(KEY)).exited


@pytest.mark.asyncio
async def test_live_channel_restart_waits_for_environment_exclusion(
    framework,
    monkeypatch,
):
    """Real owned proxy must not reconnect while a publisher holds its site."""
    from qwenpaw.plugins.install_lock import environment_coordinator

    workspace = await framework.workspace("live-admission-wait")
    await framework.activate()
    prior = await workspace.channel_manager.get_channel(KEY)
    snapshot = prior.channel_process.dependency_snapshot
    assert snapshot.dependency_sites
    assert (await workspace.channel_manager.stop_one(KEY)).exited
    connected_before = sum(
        len(rows(path, "connected")) for path in framework.network.iterdir()
    )
    entered = asyncio.Event()
    business_start = asyncio.Event()
    process_type = type(prior.channel_process)
    real_start = process_type.start

    async def start(process, spec):
        business_start.set()
        return await real_start(process, spec)

    monkeypatch.setattr(process_type, "start", start)

    async def restart():
        entered.set()
        await workspace.channel_manager.start_one(KEY, workspace._config)

    operation = None
    try:
        async with environment_coordinator(snapshot.dependency_sites):
            operation = asyncio.create_task(restart())
            await asyncio.wait_for(entered.wait(), 2)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(business_start.wait(), 1)
            assert not operation.done()
            assert (
                sum(
                    len(rows(path, "connected"))
                    for path in framework.network.iterdir()
                )
                == connected_before
            )
        await asyncio.wait_for(operation, 10)
        fresh = await workspace.channel_manager.get_channel(KEY)
        assert fresh._launch_spec.generation > prior._launch_spec.generation
        assert (
            sum(
                len(rows(path, "connected"))
                for path in framework.network.iterdir()
            )
            == connected_before + 1
        )
    finally:
        if operation is not None:
            await asyncio.gather(operation, return_exceptions=True)
        assert (await workspace.channel_manager.stop_one(KEY)).exited
