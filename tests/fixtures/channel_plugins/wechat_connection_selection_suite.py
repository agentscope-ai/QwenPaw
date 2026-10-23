"""Real manager/proxy connection budgets with controlled catalog ownership."""

import json
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.manager import instantiate_channel
from qwenpaw.app.channels import registry as channel_registry
from qwenpaw.plugins import official_channel_catalog as catalog
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import (
    ChannelRuntimeSettings,
    describe_channel,
)
from qwenpaw.plugins.ownership import RuntimeStopReceipt
from qwenpaw.plugins.registry import PluginRegistry

from extension_sample import ROOT, sample_source


@pytest.mark.parametrize(
    "owner,key,official,trusted,expected",
    [
        ("wechat", "wechat", True, None, 330.0),
        ("wechat", "wechat", True, 0.8, 0.8),
        ("wechat", "wechat", False, None, None),
        ("vendor_owner", "wechat", False, None, None),
        ("wechat", "independent_connection_owner", False, None, None),
    ],
)
def test_manager_selects_only_official_exact_owner_key_and_trusted_override(
    tmp_path, monkeypatch, owner, key, official, trusted, expected
):
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    monkeypatch.setattr(
        channel_registry,
        "BUILTIN_CHANNEL_KEYS",
        channel_registry.BUILTIN_CHANNEL_KEYS - {"wechat"},
    )
    monkeypatch.setattr(
        catalog,
        "OFFICIAL_CHANNELS",
        tuple(
            row for row in catalog.OFFICIAL_CHANNELS
            if row["channel_key"] != "wechat"
            and row["plugin_id"] != "wechat"
        )
        + (
            ({"channel_key": "wechat", "plugin_id": "wechat"},)
            if official
            else ()
        ),
    )
    source = sample_source(tmp_path / "incoming", key)
    # The real WeChat host adds its retained auth fields before validating
    # the closed descriptor. Keep that production schema in this fixture.
    if key == "wechat":
        descriptor_path = source / "channel.json"
        descriptor = json.loads(descriptor_path.read_text())
        official_descriptor = json.loads(
            (ROOT / "plugins/channel/wechat/channel.json").read_text()
        )
        descriptor["config_schema"] = official_descriptor["config_schema"]
        descriptor["config_fields"] = official_descriptor["config_fields"]
        descriptor_path.write_text(json.dumps(descriptor))
    manifest = PluginManifest.from_dict(
        {**json.loads((source / "plugin.json").read_text()), "id": owner}
    )
    description = describe_channel(source, manifest)
    settings = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        startup_timeout=0.15,
        connection_timeout=trusted,
    )
    registry = PluginRegistry()
    registry.register_channel_descriptor(
        owner, description, runtime_settings=settings
    )
    channel = None
    try:
        channel = instantiate_channel(
            key,
            SimpleNamespace(channels={key: {"enabled": True}}),
            process=None,
            workspace_dir=tmp_path / "workspace",
        )
        assert channel._connection_timeout == expected
        assert channel._launch_spec.startup_timeout == 0.15
        assert "connection_timeout" not in channel._launch_spec.config
        assert (
            "connection_timeout"
            not in description.descriptor.config_schema["properties"]
        )
        assert channel.channel_process.health_snapshot()["pid"] is None
    finally:
        if channel is not None:
            registry.runtime_owners.release(
                channel._runtime_lease,
                RuntimeStopReceipt(True, "construction had no child"),
            )
        registry.unregister_channel(key)
