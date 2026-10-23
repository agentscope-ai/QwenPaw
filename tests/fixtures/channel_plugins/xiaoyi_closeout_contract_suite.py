"""Remaining old configuration/validation oracles at their new real owners."""
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def private_platform(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/xiaoyi"))
    return importlib.import_module("qwenpaw_channel_xiaoyi.platform").XiaoYiPlatform


async def unused_callback(*_):
    raise AssertionError("Invalid/constructor-only case must not enter external effects")


def test_original_constructor_configuration_structures_and_workspace_media(private_platform, tmp_path):
    config = dict(enabled=True, ak="test_ak", sk="test_sk", agent_id="test_agent", task_timeout_ms=5000, bot_prefix="[Test] ", media_dir=str(tmp_path / "media"))
    platform = private_platform(config, unused_callback, unused_callback)
    assert platform.config["enabled"] is True
    assert platform.ak == "test_ak"
    assert platform.sk == "test_sk"
    assert platform.agent_id == "test_agent"
    assert platform.task_timeout_ms == 5000
    assert platform.config["bot_prefix"] == "[Test] "
    assert platform._media_dir == tmp_path / "media"
    assert isinstance(platform._session_task_map, dict)
    assert platform._conn_primary is None and platform._conn_backup is None
    assert platform.connected is False
    assert platform._reconnect_attempts == 0
    assert isinstance(platform._session_server_map, dict)
    workspace = tmp_path / "workspace"
    scoped = private_platform({"workspace_dir": str(workspace)}, unused_callback, unused_callback)
    assert scoped._media_dir == workspace / "media"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,label", [("ak", "AK"), ("sk", "SK"), ("agent_id", "Agent ID")])
async def test_original_missing_credential_validation_precedes_any_network(private_platform, field, label, tmp_path):
    config = dict(ak="test_ak", sk="test_sk", agent_id="test_agent", workspace_dir=str(tmp_path / "workspace"))
    config[field] = ""
    states = []
    async def state_changed(state):
        states.append(state)
    platform = private_platform(config, unused_callback, state_changed)
    try:
        with pytest.raises(ValueError, match=label):
            await platform.start()
        assert platform.connected is False
        assert platform._conn_primary is None and platform._conn_backup is None
        assert not platform._media_dir.exists()
        assert states == []
    finally:
        await platform.stop()
    assert states == ["disconnected"]


@pytest.mark.parametrize("kind", ["object", "dict"])
def test_original_config_factory_values_preserved_by_official_factory(kind, tmp_path):
    from qwenpaw.config.config import XiaoYiConfig
    from qwenpaw.plugins.official_channels import bundled_channel_source
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.__version__ import __version__

    prefix = "config" if kind == "object" else "dict"
    raw = {"enabled": True, "ak": prefix + "_ak", "sk": prefix + "_sk", "agent_id": prefix + "_agent", "task_timeout_ms": 60000 if kind == "object" else 30000, "bot_prefix": "[Config] " if kind == "object" else "[Dict] "}
    config = XiaoYiConfig(**raw) if kind == "object" else raw
    with bundled_channel_source("xiaoyi") as source:
        description = describe_channel(source, PluginManifest.from_dict(json.loads((source / "plugin.json").read_bytes())))
        proxy = description.create_proxy(Runtime.run, config, python_executable=sys.executable, support_root=ROOT / "src", instance_id="xiaoyi-original-config", generation=1, qwenpaw_version=__version__, workspace_dir=tmp_path / "workspace")
        values = proxy._launch_spec.config
        assert proxy.enabled is True
        assert values["ak"] == raw["ak"] and values["sk"] == raw["sk"]
        assert values["agent_id"] == raw["agent_id"]
        assert values["task_timeout_ms"] == raw["task_timeout_ms"]
        assert values["bot_prefix"] == raw["bot_prefix"]
        # Exact original request-builder business values are host-owned now.
        request = proxy.build_agent_request_from_native({"channel_id": "xiaoyi", "sender_id": "user_123", "content_parts": [{"type": "text", "text": "Hello"}], "meta": {"session_id": "session_123", "task_id": "task_123"}})
        assert request.user_id == "user_123" and request.channel == "xiaoyi"
        assert request.channel_meta == {"session_id": "session_123", "task_id": "task_123"}
        empty = proxy.build_agent_request_from_native({})
        assert empty.channel == "xiaoyi" and empty.user_id == ""
