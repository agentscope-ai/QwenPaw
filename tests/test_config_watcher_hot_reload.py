# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
import json
from pathlib import Path

import pytest

from copaw.config.utils import load_config
from copaw.config.watcher import ConfigWatcher


class _DummyChannel:
    def __init__(self, channel: str):
        self.channel = channel

    def clone(self, _config):
        return _DummyChannel(self.channel)


class _DummyManager:
    def __init__(self):
        self.remove_calls: list[str] = []
        self.add_calls: list[str] = []
        self.replace_calls: list[str] = []
        self._channels: dict[str, _DummyChannel] = {}

    async def get_channel(self, _channel_name: str):
        return self._channels.get(_channel_name)

    async def replace_channel(self, channel_obj) -> None:
        self.replace_calls.append(channel_obj.channel)
        self._channels[channel_obj.channel] = channel_obj

    async def remove_channel(self, channel_name: str) -> bool:
        self.remove_calls.append(channel_name)
        return self._channels.pop(channel_name, None) is not None

    async def add_channel(self, channel_name: str, channel_config) -> bool:
        del channel_config
        self.add_calls.append(channel_name)
        if channel_name in self._channels:
            return False
        self._channels[channel_name] = _DummyChannel(channel_name)
        return True


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_watcher_removes_channel_when_custom_key_deleted(tmp_path: Path):
    config_path = tmp_path / "config.json"
    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
                "plugin_x": {"enabled": True, "bot_prefix": "x"},
            },
        },
    )

    mgr = _DummyManager()
    mgr._channels["plugin_x"] = _DummyChannel("plugin_x")
    watcher = ConfigWatcher(
        channel_manager=mgr,
        poll_interval=0.1,
        config_path=config_path,
    )
    watcher._snapshot()

    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
            },
        },
    )
    watcher._last_mtime = 0.0
    await watcher._check()

    assert "plugin_x" in mgr.remove_calls
    assert "plugin_x" not in mgr.add_calls


@pytest.mark.asyncio
async def test_watcher_removes_channel_when_custom_key_set_to_null(
    tmp_path: Path,
):
    config_path = tmp_path / "config.json"
    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
                "plugin_x": {"enabled": True},
            },
        },
    )

    mgr = _DummyManager()
    mgr._channels["plugin_x"] = _DummyChannel("plugin_x")
    watcher = ConfigWatcher(
        channel_manager=mgr,
        poll_interval=0.1,
        config_path=config_path,
    )
    watcher._snapshot()

    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
                "plugin_x": None,
            },
        },
    )
    watcher._last_mtime = 0.0
    await watcher._check()

    assert "plugin_x" in mgr.remove_calls
    assert "plugin_x" not in mgr.add_calls


@pytest.mark.asyncio
async def test_watcher_adds_channel_when_custom_key_appears(tmp_path: Path):
    config_path = tmp_path / "config.json"
    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
            },
        },
    )

    mgr = _DummyManager()
    watcher = ConfigWatcher(
        channel_manager=mgr,
        poll_interval=0.1,
        config_path=config_path,
    )
    watcher._snapshot()

    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
                "plugin_x": {"enabled": True},
            },
        },
    )
    watcher._last_mtime = 0.0
    await watcher._check()

    assert "plugin_x" in mgr.add_calls
    assert "plugin_x" not in mgr.remove_calls
    assert await mgr.get_channel("plugin_x") is not None


@pytest.mark.asyncio
async def test_watcher_add_success_should_not_fallthrough_to_reload(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    config_path = tmp_path / "config.json"
    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
            },
        },
    )

    mgr = _DummyManager()
    watcher = ConfigWatcher(
        channel_manager=mgr,
        poll_interval=0.1,
        config_path=config_path,
    )
    watcher._snapshot()

    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
                "plugin_x": {"enabled": True},
            },
        },
    )
    watcher._last_mtime = 0.0
    with caplog.at_level("ERROR"):
        await watcher._check()

    assert "plugin_x" in mgr.add_calls
    assert "plugin_x" not in mgr.replace_calls
    assert await mgr.get_channel("plugin_x") is not None
    assert not any(
        "failed to reload channel 'plugin_x'" in rec.getMessage()
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_watcher_skips_add_for_non_enabled_builtin_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
                "discord": {"enabled": False},
            },
        },
    )

    mgr = _DummyManager()
    watcher = ConfigWatcher(
        channel_manager=mgr,
        poll_interval=0.1,
        config_path=config_path,
    )
    watcher._snapshot()

    _write_json(
        config_path,
        {
            "channels": {
                "console": {"enabled": True},
                "discord": {"enabled": True},
            },
        },
    )
    monkeypatch.setattr(
        "copaw.config.watcher.get_available_channels",
        lambda: ("console",),
    )
    watcher._last_mtime = 0.0
    await watcher._check()

    assert "discord" not in mgr.add_calls


def test_load_config_treats_builtin_null_as_disabled(tmp_path: Path):
    config_path = tmp_path / "config.json"
    _write_json(
        config_path,
        {
            "channels": {
                "discord": None,
            },
        },
    )

    cfg = load_config(config_path)
    assert cfg.channels.discord.enabled is False
