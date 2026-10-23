# -*- coding: utf-8 -*-
"""Independent G3 actual process cancellation, custody isolation and residuals."""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import psutil
import pytest

from management_process_suite import (
    KEY,
    ROOT,
    active_management,
    assert_exact_use,
    assert_no_management_declarations,
    assert_released,
    eventually,
    inspection_spec,
    local_management_http,
    management_runtime,
    management_sample_source,
    parameters,
    parent_import_boundary,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behavior", ["normal", "swallow", "blocking", "descendant"]
)
async def test_service_cancel_waits_actual_child_tree_exit(
    management_runtime, local_management_http, behavior
):
    from qwenpaw.app.channels.management import ManagementCancelled

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http, behavior=behavior),
            timeout=3,
        )
    )
    await eventually(lambda: len(local_management_http.requests) == 1)
    (lease,) = active_management(rt)
    process = rt.owners.resource(lease)
    pid = process.health_snapshot()["pid"]
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    with pytest.raises(ManagementCancelled) as cancelled:
        await operation
    assert cancelled.value.reason_code == "MANAGEMENT_CANCELLED"
    assert cancelled.value.side_effect_possible is True
    assert_released(rt, lease, process, pid)
    if behavior in {"swallow", "blocking"}:
        assert process.last_cleanup.forced
    if behavior == "descendant":
        assert not psutil.pid_exists(int(rt.sample.descendant.read_text()))


@pytest.mark.asyncio
async def test_service_same_slot_busy_but_A_cancel_preserves_B(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import (
        ManagementError,
        ManagementCancelled,
    )

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    tasks = [
        asyncio.create_task(
            rt.service.execute(
                workspace,
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=3,
            )
        )
        for workspace in ("workspace-A", "workspace-B")
    ]
    try:
        await eventually(lambda: len(local_management_http.requests) == 2)
        leases = {lease.key.scope_id: lease for lease in active_management(rt)}
        processes = {
            workspace: rt.owners.resource(lease)
            for workspace, lease in leases.items()
        }
        pids = {
            workspace: process.health_snapshot()["pid"]
            for workspace, process in processes.items()
        }
        with pytest.raises(ManagementError) as busy:
            await rt.service.execute(
                "workspace-A",
                KEY,
                "connection.verify",
                parameters(local_management_http, "connection.verify"),
                timeout=3,
            )
        assert busy.value.reason_code == "MANAGEMENT_BUSY"
        assert len(local_management_http.requests) == 2
        receipt = await rt.owners.stop(leases["workspace-A"])
        assert receipt.stopped
        with pytest.raises(ManagementCancelled):
            await tasks[0]
        assert_released(
            rt,
            leases["workspace-A"],
            processes["workspace-A"],
            pids["workspace-A"],
        )
        assert leases["workspace-B"] in rt.owners.leases(KEY)
        assert (
            processes["workspace-B"].health_snapshot()["pid"]
            == pids["workspace-B"]
        )
        assert not tasks[1].done()
        local_management_http.reply_gate.set()
        result = await tasks[1]
        assert result.to_mapping()["workspace_id"] == "workspace-B"
        assert_released(
            rt,
            leases["workspace-B"],
            processes["workspace-B"],
            pids["workspace-B"],
        )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["disable", "unload", "uninstall"])
async def test_loader_lifecycle_stops_management_without_holding_network_lock(
    management_runtime, local_management_http, action
):
    from qwenpaw.app.channels.management import (
        ManagementCancelled,
        ManagementError,
    )

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    )
    await eventually(lambda: len(local_management_http.requests) == 1)
    (lease,) = active_management(rt)
    process = rt.owners.resource(lease)
    pid = process.health_snapshot()["pid"]
    if action == "disable":
        report = await rt.loader.lifecycle.set_enabled(KEY, False)
    else:
        report = await rt.loader.unload_plugin(
            KEY, delete_files=action == "uninstall"
        )
    assert report.quiescent and not report.needs_restart
    with pytest.raises(ManagementCancelled):
        await operation
    assert_released(rt, lease, process, pid)
    with pytest.raises(ManagementError) as denied:
        await rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    assert denied.value.reason_code in {
        "PLUGIN_DISABLED",
        "PLUGIN_NOT_INSTALLED",
        "CHANNEL_UNAVAILABLE",
    }
    assert not local_management_http.requests[1:]


@pytest.mark.asyncio
async def test_management_admission_refuses_mutation_and_held_lifecycle_without_queue(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import ManagementError

    rt = await management_runtime()
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold_lifecycle():
        async with rt.loader.plugin_lifecycle(KEY):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold_lifecycle())
    await entered.wait()
    try:
        with pytest.raises(ManagementError) as denied:
            await rt.service.execute(
                "workspace-A",
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=3,
            )
        assert denied.value.reason_code == "MANAGEMENT_BUSY"
    finally:
        release.set()
        await holder
    with rt.owners.mutation(rt.record.source_path):
        with pytest.raises(ManagementError) as denied:
            await rt.service.execute(
                "workspace-A",
                KEY,
                "qrcode.fetch",
                parameters(local_management_http),
                timeout=3,
            )
        assert denied.value.reason_code == "MANAGEMENT_BUSY"
    assert not active_management(rt)
    assert not local_management_http.requests


@pytest.mark.asyncio
async def test_service_cancel_during_spawn_has_stop_and_dependency_bound_before_await(
    management_runtime, local_management_http, monkeypatch
):
    from qwenpaw.app.channels.management import ManagementCancelled

    rt = await management_runtime()
    entered, release = asyncio.Event(), asyncio.Event()
    spawn = asyncio.create_subprocess_exec
    pids = []

    async def held_spawn(*args, **kwargs):
        (lease,) = active_management(rt)
        assert rt.owners.resource(lease) is not None
        assert_exact_use(rt, lease)
        entered.set()
        await release.wait()
        child = await spawn(*args, **kwargs)
        pids.append(child.pid)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", held_spawn)
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    )
    await entered.wait()
    (lease,) = active_management(rt)
    process = rt.owners.resource(lease)
    operation.cancel()
    await asyncio.sleep(0)
    operation.cancel()
    assert not operation.done()
    release.set()
    with pytest.raises(ManagementCancelled) as cancelled:
        await operation
    assert cancelled.value.side_effect_possible is False
    assert not active_management(rt)
    assert process.last_cleanup.exited and not process.last_cleanup.residual
    assert all(not psutil.pid_exists(pid) for pid in pids)
    assert not local_management_http.requests


@pytest.mark.asyncio
async def test_service_cancel_during_handshake_reaps_child(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.management import ManagementCancelled

    rt = await management_runtime(import_delay=0.5)
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    )
    await eventually(
        lambda: active_management(rt)
        and rt.owners.resource(active_management(rt)[0]).observed_hello
        is not None
    )
    (lease,) = active_management(rt)
    process = rt.owners.resource(lease)
    assert process.health_snapshot()["state"] == "starting"
    pid = process.health_snapshot()["pid"]
    operation.cancel()
    with pytest.raises(ManagementCancelled) as cancelled:
        await operation
    assert cancelled.value.side_effect_possible is False
    assert_released(rt, lease, process, pid)
    assert not local_management_http.requests


@pytest.mark.asyncio
async def test_service_cancel_during_cleanup_cannot_publish_credentials_early(
    management_runtime, local_management_http, monkeypatch
):
    from qwenpaw.app.channels.management import ManagementCancelled
    from qwenpaw.plugins.execution.process import PluginProcess

    rt = await management_runtime()
    entered, release = asyncio.Event(), asyncio.Event()
    terminate = PluginProcess._terminate_tree

    async def held_terminate(process, *args, **kwargs):
        entered.set()
        await release.wait()
        return await terminate(process, *args, **kwargs)

    with monkeypatch.context() as boundary:
        boundary.setattr(PluginProcess, "_terminate_tree", held_terminate)
        operation = asyncio.create_task(
            rt.service.execute(
                "workspace-A",
                KEY,
                "qrcode.poll",
                parameters(local_management_http, "qrcode.poll"),
                timeout=3,
            )
        )
        await entered.wait()
        (lease,) = active_management(rt)
        process = rt.owners.resource(lease)
        pid = local_management_http.requests[0]["pid"]
        assert not operation.done()
        assert_exact_use(rt, lease)
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        assert not operation.done()
        release.set()
        with pytest.raises(ManagementCancelled):
            await operation
    assert_released(rt, lease, process, pid)


@pytest.mark.asyncio
async def test_real_unreaped_child_retains_custody_and_blocks_slot_mutation_and_uninstall(
    management_runtime, local_management_http, monkeypatch
):
    from qwenpaw.app.channels.management import ManagementError
    from qwenpaw.plugins.execution.process_tree import ProcessTree
    from qwenpaw.plugins.ownership import RuntimeSourceBusyError

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http, behavior="swallow"),
            timeout=3,
        )
    )
    await eventually(lambda: len(local_management_http.requests) == 1)
    (lease,) = active_management(rt)
    process = rt.owners.resource(lease)
    pid = process.health_snapshot()["pid"]
    files = {
        path.relative_to(rt.record.source_path): path.read_bytes()
        for path in rt.record.source_path.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    signal = ProcessTree.signal

    def refuse_owned_signal(tree, *, force):
        if tree.pid != pid:
            signal(tree, force=force)

    try:
        with monkeypatch.context() as boundary:
            boundary.setattr(ProcessTree, "signal", refuse_owned_signal)
            operation.cancel()
            with pytest.raises(ManagementError) as failed:
                await operation
            assert failed.value.reason_code == "MANAGEMENT_CLEANUP_FAILED"
            assert failed.value.needs_restart is True
            assert (
                failed.value.receipt is not None
                and not failed.value.receipt.stopped
            )
            assert psutil.pid_exists(pid)
            assert lease in rt.owners.leases(KEY)
            assert rt.owners.resource(lease) is process
            assert_exact_use(rt, lease)
            with pytest.raises(RuntimeSourceBusyError):
                with rt.owners.mutation(rt.record.source_path):
                    raise AssertionError("retained source admitted mutation")
            with pytest.raises(ManagementError) as busy:
                await rt.service.execute(
                    "workspace-A",
                    KEY,
                    "qrcode.fetch",
                    parameters(local_management_http),
                    timeout=3,
                )
            assert busy.value.reason_code == "MANAGEMENT_BUSY"
            assert len(local_management_http.requests) == 1
            report = await rt.loader.unload_plugin(KEY, delete_files=True)
            assert not report.quiescent and report.needs_restart
            assert rt.record.source_path.is_dir()
            assert {
                path.relative_to(rt.record.source_path): path.read_bytes()
                for path in rt.record.source_path.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            } == files
        receipt = await rt.owners.stop(lease)
        assert receipt.stopped
        assert_released(rt, lease, process, pid)
        assert_no_management_declarations(rt)
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await rt.owners.stop(lease)


@pytest.mark.asyncio
async def test_management_A_cancel_preserves_actual_runtime_and_preparation_processes(
    management_runtime, local_management_http
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.app.channels.management import ManagementCancelled
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt
    from qwenpaw.plugins.dependency_usage import DependencyDeclaration

    rt = await management_runtime(run_driver=True, import_delay=0.5)
    row = rt.loader.registry.get_channel_catalog_entry(KEY)
    description = row.description_record
    runtime = ChannelProcess()
    run_lease = rt.owners.reserve(
        KEY,
        RuntimeKey("channel", KEY, "workspace-A"),
        rt.record.source_path,
        instance_id="actual-runtime",
    )
    token = rt.usage.declare(
        DependencyDeclaration(
            KEY, description.source_revision, description.requirements, None
        )
    )
    rt.usage.bind(run_lease, token)
    runtime.dependency_observer = lambda snapshot: rt.usage.observe(
        run_lease, snapshot
    )

    async def stop_runtime():
        result = await runtime.stop()
        return RuntimeStopReceipt(
            result.exited and not result.residual,
            exited=result.exited,
            returncode=result.returncode,
            forced=result.forced,
            residual=result.residual,
        )

    rt.owners.attach(run_lease, stop_runtime, resource=runtime)
    installed = SimpleNamespace(source=rt.record.source_path)
    run_spec = replace(
        inspection_spec(installed),
        instance_id=run_lease.instance_id,
        generation=run_lease.generation,
    )
    operations, probe_task = [], None
    prep_lease = None
    try:
        await runtime.start(run_spec)
        await eventually(
            lambda: runtime.health_snapshot()["platform_state"] == "connected"
        )
        runtime_pid = runtime.health_snapshot()["pid"]
        local_management_http.reply_gate.clear()
        operations = [
            asyncio.create_task(
                rt.service.execute(
                    workspace,
                    KEY,
                    "qrcode.fetch",
                    parameters(local_management_http),
                    timeout=3,
                )
            )
            for workspace in ("workspace-A", "workspace-B")
        ]
        await eventually(lambda: len(local_management_http.requests) == 2)
        preparation, prep_lease = rt.loader._own_preparation(
            KEY,
            ChannelProcess,
            rt.record.source_path,
            instance_id="actual-preparation",
        )
        probe_task = asyncio.create_task(
            preparation.probe(
                replace(
                    run_spec,
                    instance_id=prep_lease.instance_id,
                    generation=prep_lease.generation,
                )
            )
        )
        await eventually(lambda: preparation.observed_hello is not None)
        preparation_pid = preparation.health_snapshot()["pid"]
        assert preparation_pid is not None and not probe_task.done()
        leases = {lease.key.scope_id: lease for lease in active_management(rt)}
        assert run_lease in rt.owners.leases(
            KEY
        ) and prep_lease in rt.owners.leases(KEY)
        assert len(rt.owners.leases(KEY)) == 4
        receipt = await rt.owners.stop(leases["workspace-A"])
        assert receipt.stopped
        with pytest.raises(ManagementCancelled):
            await operations[0]
        assert runtime.health_snapshot()["pid"] == runtime_pid
        assert runtime.health_snapshot()["platform_state"] == "connected"
        assert run_lease in rt.owners.leases(KEY)
        assert prep_lease in rt.owners.leases(KEY)
        assert leases["workspace-B"] in rt.owners.leases(KEY)
        assert not operations[1].done()
        local_management_http.reply_gate.set()
        await operations[1]
        evidence = await probe_task
        assert evidence.cleanup.exited and not evidence.cleanup.residual
        assert not psutil.pid_exists(preparation_pid)
    finally:
        for task in operations:
            if not task.done():
                task.cancel()
        await asyncio.gather(*operations, return_exceptions=True)
        if probe_task is not None:
            await asyncio.gather(probe_task, return_exceptions=True)
        if prep_lease is not None:
            receipt = await rt.owners.stop(prep_lease)
            assert receipt.stopped
        receipt = await rt.owners.stop(run_lease)
        assert receipt.stopped
        rt.usage.withdraw(token)
    assert not psutil.pid_exists(runtime_pid)


@pytest.mark.asyncio
async def test_loader_update_cancels_management_before_source_replacement(
    management_runtime, local_management_http, tmp_path
):
    from qwenpaw.app.channels.management import ManagementCancelled

    rt = await management_runtime()
    local_management_http.reply_gate.clear()
    operation = asyncio.create_task(
        rt.service.execute(
            "workspace-A",
            KEY,
            "qrcode.fetch",
            parameters(local_management_http),
            timeout=3,
        )
    )
    await eventually(lambda: len(local_management_http.requests) == 1)
    (lease,) = active_management(rt)
    process = rt.owners.resource(lease)
    pid = process.health_snapshot()["pid"]
    replacement = management_sample_source(tmp_path / "update")
    manifest_path = replacement.source / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "1.0.1"
    manifest_path.write_text(json.dumps(manifest))
    report = await rt.loader.lifecycle.reload(
        KEY, new_source=replacement.source
    )
    assert report.ok, report.errors
    with pytest.raises(ManagementCancelled):
        await operation
    assert_released(rt, lease, process, pid)
    assert rt.loader.get_loaded_plugin(KEY).manifest.version == "1.0.1"
    assert len(local_management_http.requests) == 1
