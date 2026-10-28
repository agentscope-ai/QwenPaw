# -*- coding: utf-8 -*-
"""Production workspace driver ownership, through an SDK-only protocol."""
# pylint: disable=protected-access

import asyncio
from contextlib import asynccontextmanager

import pytest

from qwenpaw.app.workspace.service_factories import create_driver_service
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.plugins.testing import PluginTestHost

from tests.unit.plugins.sdk_author_fixture import make_plugin

PLUGIN_ID = "lazy-driver-test"
SOURCE = """
import asyncio
from pathlib import Path
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.drivers import DriverProtocolSpec, DriverCapabilitySpec

class Plugin:
    def register(self, plugin):
        directory = Path(plugin.config.get("directory"))
        def record(event, source):
            rows = plugin.storage.read_json("events", [])
            rows.append([event, source.source_id, source.config.get("label")])
            plugin.storage.write_json("events", rows)
        class Connection:
            def __init__(self, context, source):
                self.source = source
                record("create", source)
            async def open(self):
                record("open", self.source)
                while self.source.config.get("wait_open") and not (
                    directory / "release-open").exists():
                    await asyncio.sleep(.005)
                record("opened", self.source)
            async def discover(self, request):
                return (DriverCapabilitySpec("echo", "Echo", {}),)
            async def invoke(self, name, arguments, request):
                raise SDKError("unused")
            async def close(self):
                record("close-attempt", self.source)
                if self.source.config.get("fail_close") and not (
                    directory / "allow-close").exists():
                    raise SDKError("synthetic close failure")
                record("closed", self.source)
        for protocol in plugin.config.get("protocols", ("mcp",)):
            plugin.register_driver_protocol(DriverProtocolSpec(
                protocol, lambda source: None, Connection))
plugin = Plugin()
"""


def fake_plugin(tmp_path):
    import json

    source = SOURCE.replace(
        'Path(plugin.config.get("directory"))',
        f'Path(plugin.config.get("directory", {str(tmp_path)!r}))',
    )
    path = make_plugin(tmp_path, source, ["drivers", "storage"])
    manifest = path / "plugin.json"
    data = json.loads(manifest.read_text())
    data["id"] = PLUGIN_ID
    data["sdk"]["version"] = "1.1.0"
    manifest.write_text(json.dumps(data))
    return path


def card(name="same", *, protocol="mcp", enabled=True, **config):
    return DriverCard(
        name=name,
        protocol=protocol,
        enabled=enabled,
        endpoint={},
        config=config,
        policy={"default_effect": "allow"},
    )


async def start_runtime(workspace):
    published = []

    def publish(value):
        published.append(value)
        workspace._service_manager.services["driver_manager"] = value

    runtime = await create_driver_service(
        workspace,
        None,
        publish,
    )
    assert published == [runtime]
    assert workspace.driver_manager is runtime
    return runtime


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


def events(host, kind):
    return [
        row
        for row in host.test_event_storage.read_json("events", [])
        if row[0] == kind
    ]


@asynccontextmanager
async def live_runtime(tmp_path, *, load=True):
    plugin = fake_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        if load:
            await host.install(plugin, config={"directory": str(tmp_path)})
            host.test_event_storage = host.context(PLUGIN_ID).storage
        workspace = await host._workspace("test")
        runtime = await start_runtime(workspace)
        try:
            yield host, workspace, runtime
        finally:
            (tmp_path / "release-open").touch()
            (tmp_path / "allow-close").touch()
            await asyncio.wait_for(runtime.shutdown_all(), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("load", [False, True])
async def test_empty_factory_and_queries_never_construct_manager(
    tmp_path,
    monkeypatch,
    load,
):
    constructions = []
    original = DriverManager.__init__

    def observe(self, *args, **kwargs):
        constructions.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(DriverManager, "__init__", observe)
    async with live_runtime(tmp_path, load=load) as (_, _, runtime):
        assert type(runtime).__name__ == "LazyDriverService"
        assert await runtime.list_capabilities() == []
        assert await runtime.list_drivers() == []
        await runtime.remove_transient_drivers("unused")
        await runtime.shutdown_all()
        assert runtime.manager is None
        assert runtime.watcher is None
        assert not constructions


@pytest.mark.asyncio
async def test_concurrent_first_sources_share_one_manager(
    tmp_path,
    monkeypatch,
):
    constructions = []
    original = DriverManager.__init__

    def observe(self, *args, **kwargs):
        constructions.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(DriverManager, "__init__", observe)
    async with live_runtime(tmp_path) as (host, _, runtime):
        await asyncio.gather(
            *(runtime.upsert_driver(card(str(i))) for i in range(8)),
        )
        assert len(constructions) == 1
        assert runtime.manager is constructions[0]
        assert len(events(host, "opened")) == 8
        assert len(await runtime.list_capabilities()) == 8
        for i in range(8):
            await runtime.delete_driver(str(i))
        assert runtime.manager is None
        assert len(events(host, "closed")) == 8


@pytest.mark.asyncio
async def test_disabled_source_persists_without_constructing_manager(tmp_path):
    async with live_runtime(tmp_path) as (host, _, runtime):
        await runtime.upsert_driver(card(enabled=False))
        assert await runtime.card_store.load("same", protocol="mcp") == card(
            enabled=False,
        )
        assert await runtime.list_capabilities() == []
        assert runtime.manager is None
        assert events(host, "create") == []
        assert runtime.watcher is not None


@pytest.mark.asyncio
async def test_last_source_disabled_reclaims_manager_but_keeps_watching(
    tmp_path,
):
    async with live_runtime(tmp_path) as (host, _, runtime):
        await runtime.upsert_driver(card())
        first = runtime.manager
        assert first is not None
        await runtime.upsert_driver(card(enabled=False))
        assert runtime.manager is None
        assert runtime.watcher is not None
        assert len(events(host, "closed")) == 1
        await runtime.upsert_driver(card())
        assert runtime.manager is not first
        assert len(events(host, "opened")) == 2


@pytest.mark.asyncio
async def test_failed_shutdown_retains_workspace_service_owner_for_retry(
    tmp_path,
):
    async with live_runtime(tmp_path) as (host, workspace, runtime):
        await runtime.upsert_driver(card(fail_close=True))
        manager = runtime.manager
        with pytest.raises(Exception, match="stop|close|clean|fail"):
            await workspace._service_manager.stop_all(final=True)
        assert workspace.driver_manager is runtime
        assert runtime.manager is manager
        assert events(host, "closed") == []
        (tmp_path / "allow-close").touch()
        await workspace._service_manager.stop_all(final=True)
        assert len(events(host, "closed")) == 1
        assert runtime.manager is None


@pytest.mark.asyncio
async def test_failed_last_source_cleanup_retains_manager_for_retry(tmp_path):
    async with live_runtime(tmp_path) as (host, _, runtime):
        await runtime.upsert_driver(card(fail_close=True))
        manager = runtime.manager
        with pytest.raises(Exception, match="stop|close|clean|fail"):
            await runtime.delete_driver("same")
        assert runtime.manager is manager
        assert events(host, "closed") == []
        (tmp_path / "allow-close").touch()
        await runtime.shutdown_all()
        assert runtime.manager is None
        assert len(events(host, "closed")) == 1


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_open_without_publishing_stale_manager(
    tmp_path,
):
    async with live_runtime(tmp_path) as (host, _, runtime):
        opening = asyncio.create_task(
            runtime.upsert_driver(card(wait_open=True)),
        )
        try:
            await wait_until(lambda: bool(events(host, "open")))
            await asyncio.wait_for(runtime.shutdown_all(), 1)
            result = await asyncio.wait_for(
                asyncio.gather(opening, return_exceptions=True),
                1,
            )
            assert isinstance(result[0], BaseException)
            assert runtime.manager is None
            assert await runtime.list_capabilities() == []
            assert len(events(host, "closed")) == 1
        finally:
            (tmp_path / "release-open").touch()
            opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)


@pytest.mark.asyncio
async def test_actual_workspace_same_id_replacement_does_not_reuse_manager(
    tmp_path,
):
    from qwenpaw.app.workspace import Workspace

    async with live_runtime(tmp_path) as (host, workspace, runtime):
        await runtime.upsert_driver(card())
        old = runtime.manager
        replacement = Workspace(
            workspace.agent_id,
            str(workspace.workspace_dir),
        )
        replacement.set_app_services(host._app_services)
        host._workspaces[workspace.agent_id] = replacement
        second = None
        try:
            await runtime.shutdown_all()
            second = await start_runtime(replacement)
            assert second is not runtime
            assert second.manager is not old
            assert len(await second.list_capabilities()) == 1
            with pytest.raises(
                Exception,
                match="stale|stop|replac|closed|unavailable",
            ):
                await runtime.upsert_driver(card("obsolete"))
            assert len(events(host, "opened")) == 2
        finally:
            if second is not None:
                await second.shutdown_all()


@pytest.mark.asyncio
async def test_disabling_mcp_preserves_separately_owned_other_protocol(
    tmp_path,
):
    import json

    async with live_runtime(tmp_path) as (host, _, runtime):
        other_dir = tmp_path / "other-plugin"
        other_dir.mkdir()
        other_plugin = fake_plugin(other_dir)
        manifest = other_plugin / "plugin.json"
        data = json.loads(manifest.read_text())
        data["id"] = "other-driver-test"
        manifest.write_text(json.dumps(data))
        await host.load(
            other_plugin,
            config={
                "directory": str(tmp_path),
                "protocols": ["other"],
            },
        )
        await runtime.upsert_driver(card())
        await runtime.upsert_driver(card("unrelated", protocol="other"))
        manager = runtime.manager
        await host.set_enabled(PLUGIN_ID, False)
        assert runtime.manager is manager
        capabilities = await runtime.list_capabilities()
        assert [item.driver_name for item in capabilities] == ["unrelated"]
        assert len(events(host, "closed")) == 1
        await host.set_enabled(PLUGIN_ID, True)
        assert sorted(
            item.driver_name for item in await runtime.list_capabilities()
        ) == ["same", "unrelated"]
        assert runtime.manager is manager


def test_unused_factory_does_not_import_concrete_qwenpaw_mcp(tmp_path):
    import os
    import subprocess
    import sys

    script = """
import asyncio, sys
from qwenpaw.app.workspace import Workspace
from qwenpaw.app.workspace.service_factories import create_driver_service
from qwenpaw.plugins.registry import PluginRegistry
from types import SimpleNamespace
async def check():
    ws = Workspace("unused", sys.argv[1])
    PluginRegistry().set_workspace_manager(
        SimpleNamespace(agents={"unused": ws}))
    runtime = await create_driver_service(ws, None, lambda value: None)
    assert await runtime.list_capabilities() == []
    await runtime.shutdown_all()
    concrete = [name for name in sys.modules if name.startswith((
        "qwenpaw.drivers.handlers.mcp", "qwenpaw.drivers.transports.mcp",
        "qwenpaw.app.mcp.manager"))]
    assert not concrete, concrete
asyncio.run(check())
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path / "unused")],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_disabled_plugin_preserves_config_without_manager_or_scan(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.drivers.storage import (
        AsyncDriverCardStore,
        card_path,
        dump_card,
    )

    constructions = []
    snapshots = []
    original_init = DriverManager.__init__
    original_snapshot = AsyncDriverCardStore.snapshot

    def observe_init(self, *args, **kwargs):
        constructions.append(self)
        original_init(self, *args, **kwargs)

    async def observe_snapshot(self, *args, **kwargs):
        snapshots.append(self)
        return await original_snapshot(self, *args, **kwargs)

    monkeypatch.setattr(DriverManager, "__init__", observe_init)
    monkeypatch.setattr(AsyncDriverCardStore, "snapshot", observe_snapshot)
    plugin = fake_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(plugin, config={"directory": str(tmp_path)})
        await host.set_enabled(PLUGIN_ID, False)
        workspace = await host._workspace("test")
        saved = card_path(
            workspace.workspace_dir / "drivers",
            "same",
            protocol="mcp",
        )
        dump_card(card(), saved)
        before = saved.read_bytes()
        runtime = await start_runtime(workspace)
        try:
            assert runtime.manager is None
            assert runtime.watcher is None
            assert await runtime.list_capabilities() == []
            assert saved.read_bytes() == before
            assert not constructions
            assert not snapshots
        finally:
            await runtime.shutdown_all()


@pytest.mark.asyncio
async def test_replacement_during_first_open_rejects_old_source(tmp_path):
    from qwenpaw.app.workspace import Workspace

    async with live_runtime(tmp_path) as (host, workspace, runtime):
        opening = asyncio.create_task(
            runtime.upsert_driver(card(wait_open=True)),
        )
        second = None
        try:
            await wait_until(lambda: bool(events(host, "open")))
            old = runtime.manager
            replacement = Workspace(
                workspace.agent_id,
                str(workspace.workspace_dir),
            )
            replacement.set_app_services(host._app_services)
            host._workspaces[workspace.agent_id] = replacement
            await asyncio.wait_for(runtime.shutdown_all(), 1)
            outcomes = await asyncio.wait_for(
                asyncio.gather(opening, return_exceptions=True),
                1,
            )
            assert isinstance(outcomes[0], BaseException)
            assert runtime.manager is None
            (tmp_path / "release-open").touch()
            second = await start_runtime(replacement)
            assert second.manager is not old
            assert len(await second.list_capabilities()) == 1
            assert len(events(host, "opened")) == 1
            assert len(events(host, "closed")) == 1
        finally:
            (tmp_path / "release-open").touch()
            opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)
            if second is not None:
                await second.shutdown_all()


@pytest.mark.asyncio
async def test_config_queries_and_disabled_saves_work_without_plugin(tmp_path):
    from fastapi import HTTPException
    from qwenpaw.drivers.errors import DriverNotFoundError
    from qwenpaw.app.driver_config_service import DriverConfigService

    async with live_runtime(tmp_path, load=False) as (_, workspace, runtime):
        service = DriverConfigService(workspace)
        assert service.card_store is runtime.card_store
        assert service.credential_store is runtime.credential_store
        source = card(enabled=False)
        await service.save_card(source)
        await asyncio.wait_for(
            asyncio.gather(*service._reload_tasks),
            1,
        )
        assert await service.load_card("same", protocol="mcp") == source
        assert await service.list_cards(protocol="mcp") == [source]
        assert await runtime.list_capabilities() == []
        with pytest.raises(HTTPException) as unavailable:
            await service.list_driver_capabilities(
                "same",
                protocol="mcp",
                kind="tool",
            )
        assert unavailable.value.status_code == 503
        with pytest.raises(DriverNotFoundError):
            await runtime.list_driver_capabilities("same")
        assert runtime.manager is None
        assert runtime.watcher is None


@pytest.mark.asyncio
async def test_multi_agent_publication_opens_only_current_workspace(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.app.workspace import Workspace
    from qwenpaw.drivers.storage import card_path, dump_card

    plugin = fake_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(plugin, config={"directory": str(tmp_path)})
        host.test_event_storage = host.context(PLUGIN_ID).storage
        configured = await host._workspace("test")
        dump_card(
            card(),
            card_path(
                configured.workspace_dir / "drivers",
                "same",
                protocol="mcp",
            ),
        )
        manager = MultiAgentManager()
        host._loader.registry.set_workspace_manager(manager)
        prepared = []
        constructions = []
        original_init = DriverManager.__init__

        def observe_init(self, *args, **kwargs):
            constructions.append((self, manager.agents.get("test")))
            original_init(self, *args, **kwargs)

        class DriverWorkspace(Workspace):
            """Keep real lifecycle and drivers; omit unrelated services."""

            def _register_services(self):
                super()._register_services()
                descriptors = self._service_manager.descriptors
                self._service_manager.descriptors = {
                    "driver_manager": descriptors["driver_manager"],
                }

            async def start(self):
                await super().start()
                prepared.append(
                    (
                        self,
                        self.driver_manager.manager,
                        manager.agents.get(self.agent_id) is self,
                    ),
                )

        def create(agent_id, workspace_dir):
            workspace = DriverWorkspace(agent_id, workspace_dir)
            workspace.set_app_services(host._app_services)
            return workspace

        monkeypatch.setattr(manager, "_create_workspace", create)
        monkeypatch.setattr(DriverManager, "__init__", observe_init)
        try:
            first = await manager.get_agent("test")
            assert manager.agents["test"] is first
            assert len(await first.driver_manager.list_capabilities()) == 1
            first_actual = first.driver_manager.manager
            assert constructions == [(first_actual, first)]
            assert prepared == [(first, None, False)]
            assert await manager.reload_agent("test") is True
            second = manager.agents["test"]
            assert second is not first
            assert second.driver_manager.manager is not first_actual
            assert len(await second.driver_manager.list_capabilities()) == 1
            assert constructions[-1] == (second.driver_manager.manager, second)
            assert prepared[-1] == (second, None, False)
            assert len(events(host, "opened")) == 2
            with pytest.raises(Exception, match="stop|stale|replac|closed"):
                await first.driver_manager.upsert_driver(card("obsolete"))
        finally:
            await asyncio.wait_for(manager.stop_all(), 3)


@pytest.mark.asyncio
async def test_empty_requests_do_not_activate_and_explicit_off_is_not_bypassed(
    tmp_path,
):
    from qwenpaw.app.driver_runtime_service import LazyDriverService
    from qwenpaw.plugins import SDKError

    calls = []

    async def explicitly_disabled(protocol):
        calls.append(protocol)
        raise SDKError("MCP explicitly disabled")

    async with PluginTestHost(tmp_path / "host") as host:
        workspace = await host._workspace("test")
        runtime = LazyDriverService(
            workspace,
            registry=host._loader.registry,
            ensure_protocol=explicitly_disabled,
        )
        workspace._service_manager.services["driver_manager"] = runtime
        try:
            await runtime.start()
            assert await runtime.list_capabilities() == []
            await runtime.replace_transient_drivers("empty", [])
            await runtime.remove_transient_drivers("empty")
            assert not calls
            assert not runtime.cards_dir.exists()
            with pytest.raises(SDKError, match="explicitly disabled"):
                await runtime.upsert_driver(card())
            assert calls == ["mcp"]
            assert runtime.manager is None
        finally:
            await runtime.shutdown_all()


@pytest.mark.asyncio
async def test_migration_default_card_does_not_establish_monitoring(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.drivers.storage import (
        AsyncDriverCardStore,
        card_path,
        dump_card,
    )

    snapshots = []
    original = AsyncDriverCardStore.snapshot

    async def observe(self, *args, **kwargs):
        snapshots.append(self)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncDriverCardStore, "snapshot", observe)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(fake_plugin(tmp_path))
        workspace = await host._workspace("test")
        import json
        from pathlib import Path

        fixture = (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "mcp_plugin_upgrade"
            / "default-v2.json"
        )
        default = DriverCard(**json.loads(fixture.read_text())["cards"][0])
        path = card_path(
            workspace.workspace_dir / "drivers",
            "anysearch",
            protocol="mcp",
        )
        dump_card(default, path)
        before = path.read_bytes()
        runtime = await start_runtime(workspace)
        try:
            assert runtime.manager is None
            assert runtime.watcher is None
            assert not snapshots
            assert await runtime.list_capabilities() == []
            assert path.read_bytes() == before
        finally:
            await runtime.shutdown_all()
