# -*- coding: utf-8 -*-
"""Feishu static registration and real host factory, without SDK work."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
import asyncio
import socket
import subprocess
import sys
import threading
import pytest
from c6_artifacts import description, proxy, unused_process
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.config.config import FeishuConfig


def test_register_without_platform_sdk(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Static registration started external work")

    for target, name in [
        (socket.socket, "connect"),
        (threading.Thread, "start"),
        (subprocess.Popen, "__init__"),
        (asyncio.BaseEventLoop, "create_task"),
    ]:
        monkeypatch.setattr(target, name, forbidden)
    record = description("feishu")
    channel = proxy("feishu", {"enabled": True})
    assert isinstance(channel, BaseChannel) and channel.channel == "feishu"
    assert record.descriptor.entrypoint.module == "feishu.driver"
    assert "lark_oapi" not in sys.modules
    assert channel.channel_process.health_snapshot()["pid"] is None


def test_from_config_preserves_settings(tmp_path):
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="test-secret",
        encrypt_key="encryption",
        verification_token="verification",
        domain="lark",
        bot_prefix="[bot]",
        dm_policy="allowlist",
        group_policy="allowlist",
        allow_from=["ou_allowed"],
        deny_message="denied",
        require_mention=True,
        streaming_enabled=True,
        share_session_in_group=True,
        auto_collapse_thinking=True,
        access_control_dm=True,
        access_control_group=True,
        show_tool_calls=False,
        show_thinking=False,
        tool_result_max_length=0,
    )
    original = config.model_dump()
    callback = object()
    channel = proxy(
        "feishu",
        config,
        on_reply_sent=callback,
        no_text_debounce=False,
        workspace_dir=tmp_path,
    )
    for key, value in original.items():
        if key != "no_text_debounce":
            assert channel._launch_spec.config[key] == value, key
    assert (
        channel._process is unused_process
        and channel._on_reply_sent is callback
    )
    assert channel.allow_from == {"ou_allowed"}
    assert channel._display_config.show_tool_calls is False
    assert channel._display_config.show_thinking is False
    assert channel._display_config.tool_result_max_length == 0
    assert (
        channel._no_text_debounce is False and config.model_dump() == original
    )
    assert not (tmp_path / "media").exists()


def test_config_snapshot_and_display_override():
    config = FeishuConfig(allow_from=["original"])
    display = ChannelDisplayConfig(show_tool_calls=False)
    first = proxy("feishu", config, display_config=display)
    second = proxy("feishu", config)
    config.allow_from.append("later")
    first._launch_spec.config["allow_from"].append("first-only")
    assert second.allow_from == {"original"}
    assert first._display_config is display
    assert second._display_config.show_tool_calls is True


@pytest.mark.parametrize("domain", ["feishu", "lark", "https://gateway.test"])
def test_explicit_media_path_and_domain(tmp_path, domain):
    channel = proxy("feishu", {"domain": domain, "media_dir": str(tmp_path)})
    assert channel._launch_spec.config["domain"] == domain
    assert channel._launch_spec.config["media_dir"] == str(tmp_path)
