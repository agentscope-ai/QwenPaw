"""Formal bundled descriptions select trusted host data before worker start.

This verifies factory policy, not a live worker, adoption or actual Agent flow.
"""

from copy import deepcopy
import json
import sys

import pytest

import official_g1_suite as core

registry = core.registry
saved_host = core.saved_host


@pytest.mark.parametrize("key", sorted(core.source_inventory()))
def test_formal_bundled_owner_automatically_selects_only_its_host_context(
    saved_host,
    registry,
    tmp_path,
    monkeypatch,
    key,
):
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.official_channels import bundled_channel_source

    host_cwd = tmp_path / "host-cwd"
    host_cwd.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(host_cwd)
    monkeypatch.setenv("HOME", str(home))
    host_env = {
        "QQ_API_BASE": "https://api.invalid",
        "QQ_TOKEN_URL": "https://token.invalid",
        "QQ_PORTAL_HOST": "portal.invalid",
        "DASHSCOPE_API_KEY": "test-host-key",
    }
    for name, value in host_env.items():
        monkeypatch.setenv(name, value)
    owner, _ = core.source_inventory()[key]
    config = {"enabled": False}
    if key in {"matrix", "azure_bot"}:
        config["legacy_state_dir"] = "client-must-not-authorize"
    if key == "imessage":
        config.update(db_path="messages.sqlite", media_dir="relative-media")
    if key == "wechat":
        config.update(
            bot_token_file="relative-token", media_dir="relative-media"
        )
    saved = deepcopy(config)

    async def never_agent(_request):
        raise AssertionError("constructor must not execute Agent")
        yield

    with bundled_channel_source(owner) as source:
        manifest = PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text())
        )
        description = describe_channel(source, manifest)
        assert description.plugin_id == owner
        assert description.descriptor.channel_key == key
        proxy = description.create_proxy(
            never_agent,
            config,
            python_executable=sys.executable,
            support_root=core.ROOT / "src",
            instance_id="formal-context-" + key,
            generation=1,
            qwenpaw_version="2.2.2b4",
            workspace_dir=tmp_path / "workspace",
        )
        spec = proxy._launch_spec
        assert spec.plugin_id == owner and spec.workspace_id == str(
            (tmp_path / "workspace").resolve()
        )
        assert proxy.channel_process.health_snapshot()["pid"] is None
        assert spec.private_env == (
            {
                name: host_env[name]
                for name in (
                    "QQ_API_BASE",
                    "QQ_TOKEN_URL",
                    "QQ_PORTAL_HOST",
                )
            }
            if key == "qq"
            else {}
        )
        if key in {"matrix", "azure_bot"}:
            assert spec.config["legacy_state_dir"] == str(saved_host.parent)
        elif key == "sip":
            assert spec.config["dashscope_api_key"] == "test-host-key"
        elif key == "imessage":
            assert spec.config["db_path"] == str(host_cwd / "messages.sqlite")
            assert spec.config["media_dir"] == str(host_cwd / "relative-media")
        elif key == "wechat":
            assert spec.config["bot_token_file"] == str(
                host_cwd / "relative-token"
            )
            assert spec.config["media_dir"] == str(host_cwd / "relative-media")
        else:
            assert "legacy_state_dir" not in spec.config
        assert "private_env" not in spec.config
        assert config == saved


def test_formal_sip_explicit_key_keeps_priority_over_host_fallback(
    saved_host,
    registry,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.official_channels import bundled_channel_source

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-host-key")
    config = {"enabled": False, "dashscope_api_key": "explicit-test-key"}
    saved = deepcopy(config)

    async def never_agent(_request):
        raise AssertionError("constructor must not execute Agent")
        yield

    with bundled_channel_source("sip") as source:
        manifest = PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text())
        )
        proxy = describe_channel(source, manifest).create_proxy(
            never_agent,
            config,
            python_executable=sys.executable,
            support_root=core.ROOT / "src",
            instance_id="formal-sip-explicit",
            generation=1,
            qwenpaw_version="2.2.2b4",
        )
        assert (
            proxy._launch_spec.config["dashscope_api_key"]
            == "explicit-test-key"
        )
        assert proxy._launch_spec.private_env == {}
        assert proxy.channel_process.health_snapshot()["pid"] is None
        assert config == saved
