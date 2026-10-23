"""Real descriptor/manager selection; no child or vendor imports required."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from extension_sample import sample_source
from catalog_suite import registry

__all__ = ["registry"]
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
@pytest.mark.parametrize("construction", ["default", "deferred", "workspace"])
async def test_process_construction_is_deferred_only_by_host_policy(
    tmp_path, monkeypatch, registry, construction
):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
    from qwenpaw.app.workspace.service_factories import create_channel_service
    from qwenpaw.config import Config
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import (
        ChannelRuntimeSettings,
        describe_channel,
    )

    source = sample_source(tmp_path / "incoming")
    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text())
    )
    settings = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=frozenset({"sample_chat"}),
    )
    registry.configure_channel_runtime(settings)
    registry.register_channel_descriptor(
        manifest.id,
        describe_channel(source, manifest),
        runtime_settings=settings,
    )
    monkeypatch.setenv("QWENPAW_ENABLED_CHANNELS", "console,sample_chat")
    config = Config.model_validate(
        {
            "channels": {
                "console": {"enabled": True},
                "sample_chat": {"enabled": True},
            }
        }
    )
    work = tmp_path / "workspace"
    work.mkdir()

    async def process(_request):
        raise AssertionError("Construction must not execute an Agent")
        yield

    published = []
    if construction == "workspace":
        ws = SimpleNamespace(
            _config=config,
            workspace_dir=work,
            stream_query=process,
            agent_id="construction-test",
        )
        manager = await create_channel_service(ws, None, published.append)
        assert published == [manager]
        assert manager._workspace is ws
    else:
        options = (
            {"defer_process_channels": True}
            if construction == "deferred"
            else {}
        )
        manager = ChannelManager.from_config(
            process, config, workspace_dir=work, **options
        )
    try:
        assert await manager.get_channel("console") is not None
        channel = await manager.get_channel("sample_chat")
        leases = registry.runtime_owners.leases()
        if construction == "default":
            assert isinstance(channel, IsolatedChannelProxy)
            assert channel.channel_process.health_snapshot()["pid"] is None
            assert len(leases) == 1
            assert registry.runtime_owners.resource(leases[0]) is channel
            assert leases[0].key.name == "sample_chat"
            assert leases[0].key.scope_id == str(work.resolve())
        else:
            assert channel is None
            assert leases == ()
        assert not any(
            name == "sample_chat" or name.startswith("sample_chat.")
            for name in sys.modules
        )
    finally:
        await manager.stop_all()
    assert registry.runtime_owners.leases() == ()
