# -*- coding: utf-8 -*-
"""Native registered channel restart/restore checks, without running an Agent."""

import json
from pathlib import Path
import sys

import pytest

SHARED = Path(__file__).resolve().parents[1] / "shared_dependencies"
sys.path.insert(0, str(SHARED))
from upgrade_suite import (
    isolated_loader,
    channel_source,
    distribution,
    tree_bytes,
    upgrade_manager,
)


async def loaded_consumer(loader, site, tmp_path):
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
    from qwenpaw.app.task_tracker import TaskTracker
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.config import config as config_model
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    class Workspace:
        pass

    ws = Workspace()
    ws.agent_id = "consumer-workspace"
    ws.workspace_dir = tmp_path / "workspace"
    ws.workspace_dir.mkdir()
    channels = config_model.ChannelConfig.model_validate(
        {
            "console": {"enabled": False},
            "old_consumer": {
                "enabled": True,
                "proof": "preserve-configuration",
            },
        }
    )
    ws._config = load_config().model_copy(update={"channels": channels})
    ws.config = ws._config
    ws.task_tracker = TaskTracker()
    ws.chat_manager = ChatManager(
        repo=JsonChatRepository(ws.workspace_dir / "chats.json")
    )

    async def no_agent_requests(_request):
        if False:
            yield None

    ws.channel_manager = ChannelManager.from_config(
        no_agent_requests,
        ws._config,
        workspace_dir=ws.workspace_dir,
        defer_process_channels=True,
    )
    ws.channel_manager.set_workspace(ws)
    loader.registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [ws]
    )
    await ws.channel_manager.start_all()
    source = channel_source(
        tmp_path / "loaded-consumer",
        name="old_consumer",
        requirements="upgrade-sdk>=1,<3\n",
    )
    descriptor_path = source / "channel.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["config_schema"]["properties"]["proof"] = {"type": "string"}
    descriptor["config_fields"].append("proof")
    descriptor_path.write_text(json.dumps(descriptor))
    (source / "driver.py").write_text(
        "import os,upgrade_sdk\n"
        "class Driver:\n"
        "    def bind(self,context):\n"
        "        self.context=context\n"
        "        context.peer.register_method('fixture.version',self.version)\n"
        "    async def version(self,params,request): return {'version':upgrade_sdk.VERSION,'proof':self.config['proof'],'pid':os.getpid()}\n"
        "    async def start(self,config):\n"
        "        self.config=config\n"
        "        await self.context.set_platform_state('connected')\n"
        "    async def stop(self): await self.context.set_platform_state('disconnected')\n"
    )
    record = await loader.load_plugin_from_path(source)
    assert record.status == "active", record.diagnostics
    channel = await ws.channel_manager.get_channel("old_consumer")
    assert channel is not None
    actual = await channel.channel_process.call(
        "fixture.version", {}, timeout=3
    )
    assert (
        actual["version"] == "1.0"
        and actual["proof"] == "preserve-configuration"
    )
    return ws, channel, actual


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_ok", [True, False])
async def test_live_consumer_requires_exact_stop_proof_before_any_package_write(
    isolated_loader,
    tmp_path,
    monkeypatch,
    stop_ok,
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    ws, channel, initial = await loaded_consumer(loader, site, tmp_path)
    process = channel.channel_process
    lease = channel._runtime_lease
    before = tree_bytes(site)
    native_stop = process.stop
    stops = []

    async def stop():
        assert (
            tree_bytes(site) == before
        ), "Dependency bytes changed before old process stopped"
        stops.append(lease)
        if not stop_ok:
            from qwenpaw.plugins.execution import StopResult

            return StopResult(False, None, False)
        return await native_stop()

    monkeypatch.setattr(process, "stop", stop)
    try:
        manager = upgrade_manager(loader)
        operation = await manager.stage(channel_source(tmp_path / "incoming"))
        assert any(
            row["instance_id"] == lease.instance_id
            and row["generation"] == lease.generation
            for row in operation["affected_instances"]
        )
        assert tree_bytes(site) == before
        applied = await manager.apply(operation["id"])
        if stop_ok:
            assert applied["status"] == "succeeded", applied
            assert stops == [lease]
            assert lease not in loader.registry.runtime_owners.leases()
            assert process.health_snapshot()["pid"] is None
            restarted = await ws.channel_manager.get_channel("old_consumer")
            assert restarted is not None and restarted is not channel
            actual = await restarted.channel_process.call(
                "fixture.version", {}, timeout=3
            )
            assert actual["version"] == "2.0"
            assert actual["proof"] == "preserve-configuration"
            assert actual["pid"] != initial["pid"]
            assert loader.get_loaded_plugin("old_consumer").status == "active"
        else:
            assert applied["status"] != "succeeded", applied
            assert tree_bytes(site) == before
            assert lease in loader.registry.runtime_owners.leases()
            assert (
                await process.call("fixture.version", {}, timeout=2) == initial
            )
            assert not (destination / "upgrade_fixture").exists()
    finally:
        monkeypatch.setattr(process, "stop", native_stop)
        await loader.unload_plugin("old_consumer")
        await ws.channel_manager.stop_all()


@pytest.mark.asyncio
async def test_consumer_admitted_after_review_makes_plan_stale_before_stop_or_write(
    isolated_loader, tmp_path, monkeypatch
):
    loader, _, site, destination = isolated_loader
    distribution(site, "upgrade-sdk", "1.0")
    manager = upgrade_manager(loader)
    operation = await manager.stage(channel_source(tmp_path / "incoming"))
    assert operation["affected_instances"] == []
    ws, channel, initial = await loaded_consumer(loader, site, tmp_path)
    before = tree_bytes(site)
    process = channel.channel_process
    native_stop = process.stop
    stops = []

    async def stop():
        stops.append(True)
        return await native_stop()

    monkeypatch.setattr(process, "stop", stop)
    try:
        applied = await manager.apply(operation["id"])
        assert applied["status"] == "failed", applied
        assert applied["error"]["code"] == "DEPENDENCY_PLAN_STALE", applied
        assert stops == []
        assert tree_bytes(site) == before
        assert await process.call("fixture.version", {}, timeout=2) == initial
        assert not (destination / "upgrade_fixture").exists()
    finally:
        monkeypatch.setattr(process, "stop", native_stop)
        await loader.unload_plugin("old_consumer")
        await ws.channel_manager.stop_all()
