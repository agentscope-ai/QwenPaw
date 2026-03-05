# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
import json
from pathlib import Path

import pytest

from copaw.config.utils import load_config
from copaw.config.watcher import ConfigWatcher


class _DummyManager:
    def __init__(self):
        self.remove_calls: list[str] = []
        self.add_calls: list[str] = []
        self.replace_calls: list[str] = []

    async def get_channel(self, _channel_name: str):
        return None

    async def replace_channel(self, channel_obj) -> None:
        self.replace_calls.append(channel_obj.channel)

    async def remove_channel(self, channel_name: str) -> bool:
        self.remove_calls.append(channel_name)
        return True

    async def add_channel(self, channel_name: str, channel_config) -> bool:
        del channel_config
        self.add_calls.append(channel_name)
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
