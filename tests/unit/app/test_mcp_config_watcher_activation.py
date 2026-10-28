# -*- coding: utf-8 -*-
"""Conditional two-second polling through the production driver facade."""
# pylint: disable=protected-access,redefined-outer-name

import asyncio

import pytest

from qwenpaw.drivers.storage import AsyncDriverCardStore

from .test_lazy_driver_runtime import live_runtime


@pytest.mark.asyncio
async def test_empty_workspace_never_snapshots_mcp(tmp_path, monkeypatch):
    snapshots = []
    original = AsyncDriverCardStore.snapshot

    async def observe(self, *args, **kwargs):
        snapshots.append(self)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncDriverCardStore, "snapshot", observe)
    async with live_runtime(tmp_path) as (_, workspace, runtime):
        descriptor = workspace._service_manager.descriptors.get(
            "driver_config_watcher",
        )
        if descriptor is not None:
            await workspace._service_manager._start_service(descriptor)
        try:
            await asyncio.sleep(0)
            assert not snapshots
            assert runtime.watcher is None
            assert runtime.manager is None
        finally:
            watcher = workspace._service_manager.services.get(
                "driver_config_watcher",
            )
            if watcher is not None:
                await watcher.stop()


class PollClock:
    """Control only the watcher's sleep; all other asyncio remains real."""

    def __init__(self):
        self.pending = []
        self.intervals = []

    async def sleep(self, seconds):
        self.intervals.append(seconds)
        future = asyncio.get_running_loop().create_future()
        self.pending.append(future)
        await future

    async def ready(self):
        from .test_lazy_driver_runtime import wait_until

        await wait_until(lambda: any(not f.done() for f in self.pending))

    def wake(self):
        future = next(f for f in self.pending if not f.done())
        future.set_result(None)

    async def tick(self):
        await self.ready()
        self.wake()
        await self.ready()


@pytest.fixture
def poll_clock(monkeypatch):
    from types import SimpleNamespace
    from qwenpaw.app import driver_config_watcher

    clock = PollClock()
    monkeypatch.setattr(
        driver_config_watcher,
        "asyncio",
        SimpleNamespace(
            sleep=clock.sleep,
            create_task=asyncio.create_task,
            CancelledError=asyncio.CancelledError,
        ),
    )
    return clock


def write_card(runtime, source):
    import os
    from qwenpaw.drivers.storage import card_path, dump_card

    path = card_path(runtime.cards_dir, source.name, protocol=source.protocol)
    dump_card(source, path)
    # Filesystems may have coarser mtime resolution than two synthetic ticks.
    previous = getattr(write_card, "mtime", 2000000000)
    write_card.mtime = previous + 1
    os.utime(path, (write_card.mtime, write_card.mtime))
    return path


@pytest.mark.asyncio
async def test_monitoring_keeps_two_second_interval(tmp_path, poll_clock):
    async with live_runtime(tmp_path) as (_, _, runtime):
        await runtime.request_monitoring("mcp")
        await poll_clock.tick()
        await poll_clock.tick()
        assert poll_clock.intervals == [2.0, 2.0, 2.0]
        assert runtime.manager is None
        assert runtime.watcher is not None


@pytest.mark.asyncio
async def test_disabled_source_can_be_enabled_by_manual_edit(
    tmp_path,
    poll_clock,
):
    from .test_lazy_driver_runtime import card, events

    async with live_runtime(tmp_path) as (host, _, runtime):
        await runtime.upsert_driver(card(enabled=False))
        await poll_clock.ready()
        assert runtime.manager is None
        assert events(host, "open") == []
        write_card(runtime, card())
        assert runtime.manager is None
        await poll_clock.tick()
        assert len(await runtime.list_capabilities()) == 1
        assert len(events(host, "opened")) == 1
        write_card(runtime, card(enabled=False))
        await poll_clock.tick()
        assert runtime.manager is None
        assert runtime.watcher is not None
        assert len(events(host, "closed")) == 1


@pytest.mark.asyncio
async def test_plugin_disable_stops_config_scan(
    tmp_path,
    poll_clock,
    monkeypatch,
):
    from .test_lazy_driver_runtime import PLUGIN_ID, card, events

    snapshots = []
    original = AsyncDriverCardStore.snapshot

    async def observe(self, *args, **kwargs):
        snapshots.append(self)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncDriverCardStore, "snapshot", observe)
    async with live_runtime(tmp_path) as (host, _, runtime):
        await runtime.upsert_driver(card())
        await poll_clock.ready()
        await host.set_enabled(PLUGIN_ID, False)
        after_disable = len(snapshots)
        write_card(runtime, card(label="edited-while-disabled"))
        await asyncio.sleep(0)
        assert len(snapshots) == after_disable
        assert runtime.watcher is None
        assert runtime.manager is None
        assert len(events(host, "closed")) == 1
        await host.set_enabled(PLUGIN_ID, True)
        await poll_clock.ready()
        assert runtime.watcher is not None
        assert len(await runtime.list_capabilities()) == 1
        assert events(host, "opened")[-1][-1] == "edited-while-disabled"
        assert len(events(host, "opened")) == 2


@pytest.mark.asyncio
async def test_monitoring_intent_survives_empty_restart_and_plugin_disable(
    tmp_path,
    poll_clock,
):
    from qwenpaw.app.workspace import Workspace
    from .test_lazy_driver_runtime import PLUGIN_ID, start_runtime

    async with live_runtime(tmp_path) as (host, workspace, runtime):
        await runtime.request_monitoring("mcp")
        await poll_clock.ready()
        await host.set_enabled(PLUGIN_ID, False)
        assert runtime.watcher is None
        await runtime.shutdown_all()
        replacement = Workspace(
            workspace.agent_id,
            str(workspace.workspace_dir),
        )
        replacement.set_app_services(host._app_services)
        host._workspaces[workspace.agent_id] = replacement
        second = await start_runtime(replacement)
        try:
            assert second.watcher is None
            await host.set_enabled(PLUGIN_ID, True)
            await poll_clock.ready()
            assert second.watcher is not None
            assert second.manager is None
        finally:
            await second.shutdown_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["add", "delete", "atomic", "directory"])
async def test_next_scan_applies_manual_file_changes(
    tmp_path,
    poll_clock,
    change,
):
    from .test_lazy_driver_runtime import card, events

    async with live_runtime(tmp_path) as (host, _, runtime):
        await runtime.request_monitoring("mcp")
        await poll_clock.ready()
        if change in {"delete", "atomic"}:
            path = write_card(runtime, card(label="first"))
            await poll_clock.tick()
            assert len(await runtime.list_capabilities()) == 1
        else:
            if change == "directory":
                assert not (runtime.cards_dir / "mcp").exists()
            path = write_card(runtime, card(label="added"))
        if change == "delete":
            path.unlink()
        elif change == "atomic":
            from qwenpaw.drivers.storage import dump_card

            replacement = path.with_suffix(".tmp")
            updated = card(label="second")
            updated.endpoint = {"revision": "second"}
            dump_card(updated, replacement)
            replacement.replace(path)
        await poll_clock.tick()
        capabilities = await runtime.list_capabilities()
        if change == "delete":
            assert capabilities == []
            assert runtime.manager is None
            assert len(events(host, "closed")) == 1
        else:
            expected = "same"
            assert [item.driver_name for item in capabilities] == [expected]
            assert events(host, "opened")[-1][-1] == (
                "second" if change == "atomic" else "added"
            )
        assert runtime.watcher is not None


@pytest.mark.asyncio
async def test_manual_write_during_await_is_seen_on_following_scan(
    tmp_path,
    poll_clock,
):
    from .test_lazy_driver_runtime import card, events, wait_until

    async with live_runtime(tmp_path) as (host, _, runtime):
        await runtime.request_monitoring("mcp")
        await poll_clock.ready()
        write_card(runtime, card(wait_open=True, label="first"))
        poll_clock.wake()
        await wait_until(lambda: len(events(host, "open")) == 1)
        write_card(runtime, card(label="second"))
        (tmp_path / "release-open").touch()
        await poll_clock.ready()
        await poll_clock.tick()
        assert len(await runtime.list_capabilities()) == 1
        assert events(host, "opened")[-1][-1] == "second"
        assert len(events(host, "opened")) == 2


@pytest.mark.asyncio
async def test_config_save_applies_without_waiting_for_poll(
    tmp_path,
    poll_clock,
):
    from qwenpaw.app.driver_config_service import DriverConfigService
    from .test_lazy_driver_runtime import card, events

    async with live_runtime(tmp_path) as (host, workspace, runtime):
        service = DriverConfigService(workspace)
        await service.save_card(card())
        try:
            await asyncio.wait_for(
                asyncio.gather(*service._reload_tasks),
                1,
            )
            await poll_clock.ready()
            assert len(await runtime.list_capabilities()) == 1
            assert len(events(host, "opened")) == 1
            # A monitoring sleep is pending; no poll was advanced.
            assert poll_clock.intervals == [2.0]
        finally:
            await asyncio.gather(
                *service._reload_tasks,
                return_exceptions=True,
            )


@pytest.mark.asyncio
async def test_other_protocol_poll_never_scans_disabled_mcp(
    tmp_path,
    poll_clock,
    monkeypatch,
):
    import json
    from .test_lazy_driver_runtime import PLUGIN_ID, card, fake_plugin

    snapshots = []
    original = AsyncDriverCardStore.snapshot

    async def observe(self, *args, **kwargs):
        snapshots.append(kwargs.get("protocols"))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncDriverCardStore, "snapshot", observe)
    async with live_runtime(tmp_path) as (host, _, runtime):
        other = tmp_path / "other"
        other.mkdir()
        plugin = fake_plugin(other)
        manifest = plugin / "plugin.json"
        data = json.loads(manifest.read_text())
        data["id"] = "other-driver-test"
        manifest.write_text(json.dumps(data))
        await host.load(
            plugin,
            config={
                "directory": str(tmp_path),
                "protocols": ["other"],
            },
        )
        await runtime.upsert_driver(card())
        await runtime.upsert_driver(card("other", protocol="other"))
        await poll_clock.ready()
        await host.set_enabled(PLUGIN_ID, False)
        await poll_clock.ready()
        snapshots.clear()
        await poll_clock.tick()
        assert snapshots == [{"other"}]
        assert runtime.watcher is not None
        assert [
            item.driver_name for item in await runtime.list_capabilities()
        ] == ["other"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["enable", "add", "config"])
async def test_activation_keeps_edits_between_load_and_watcher_baseline(
    tmp_path,
    poll_clock,
    monkeypatch,
    change,
):
    import os
    from qwenpaw.drivers.storage import card_path, dump_card
    from qwenpaw.plugins.testing import PluginTestHost
    from .test_lazy_driver_runtime import (
        PLUGIN_ID,
        card,
        events,
        fake_plugin,
        start_runtime,
    )

    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(fake_plugin(tmp_path))
        host.test_event_storage = host.context(PLUGIN_ID).storage
        workspace = await host._workspace("test")
        cards_dir = workspace.workspace_dir / "drivers"
        path = card_path(cards_dir, "same", protocol="mcp")
        dump_card(card(enabled=change == "config", label="before"), path)
        updated = card("added" if change == "add" else "same", label="after")
        target = card_path(cards_dir, updated.name, protocol="mcp")
        original = AsyncDriverCardStore.load_path
        edited = False

        async def read_then_edit(self, source_path):
            nonlocal edited
            observed = await original(self, source_path)
            if not edited and source_path == path:
                edited = True
                # Keep the exact old read while a manual writer publishes the
                # newer card before the activation path starts its watcher.
                dump_card(updated, target)
                os.utime(target, (2000000001, 2000000001))
            return observed

        monkeypatch.setattr(AsyncDriverCardStore, "load_path", read_then_edit)
        runtime = await start_runtime(workspace)
        try:
            assert edited
            assert runtime.watcher is not None
            await poll_clock.tick()
            capabilities = await runtime.list_capabilities()
            assert [item.driver_name for item in capabilities] == [
                updated.name,
            ]
            assert events(host, "opened") == [
                ["opened", updated.name, "after"],
            ]
            assert poll_clock.intervals == [2.0, 2.0]
        finally:
            await asyncio.wait_for(runtime.shutdown_all(), 3)
