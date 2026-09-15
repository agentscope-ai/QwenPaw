# -*- coding: utf-8 -*-
"""Unit tests for lazy built-in channel registry loading."""

from __future__ import annotations

# pylint: disable=protected-access

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qwenpaw.app.channels import manager as manager_mod
from qwenpaw.app.channels import registry as registry_mod
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.channels.registry import (
    _BUILTIN_SPECS,
    _REQUIRED_CHANNEL_KEYS,
    _LazyChannelClass,
    _import_channel_class,
    _load_builtin_channels,
    clear_builtin_channel_cache,
    get_channel_registry,
)
from qwenpaw.config.config import ChannelConfig, ConsoleConfig, FeishuConfig

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_DIR = _REPO_ROOT / "src"


class _DummyChannel(BaseChannel):
    """Minimal BaseChannel subclass used to validate lazy import."""

    channel = "dummy"


class _ImportlibStub:
    """Replace registry.importlib without touching the stdlib module."""

    def __init__(self, import_module):
        self.import_module = import_module


@pytest.fixture(autouse=True)
def _reset_builtin_cache():
    clear_builtin_channel_cache()
    yield
    clear_builtin_channel_cache()


def test_load_builtin_channels_imports_only_required(monkeypatch):
    imported: list[str] = []

    def _fake_import(key, module_name, class_name):
        imported.append(module_name)
        if module_name != ".console":
            raise AssertionError(f"unexpected eager import: {module_name}")
        return _DummyChannel

    monkeypatch.setattr(registry_mod, "_import_channel_class", _fake_import)

    loaded = _load_builtin_channels()

    assert imported == [".console"]
    assert set(loaded) == set(_BUILTIN_SPECS)
    assert loaded["console"] is _DummyChannel
    for key in _BUILTIN_SPECS:
        if key in _REQUIRED_CHANNEL_KEYS:
            continue
        assert isinstance(loaded[key], _LazyChannelClass)
        assert loaded[key]._cls is None


def test_lazy_channel_resolves_on_first_attribute_access(monkeypatch):
    calls: list[str] = []

    def _fake_import(key, module_name, class_name):
        calls.append(module_name)
        return _DummyChannel

    monkeypatch.setattr(registry_mod, "_import_channel_class", _fake_import)

    proxy = _LazyChannelClass("feishu", ".feishu", "FeishuChannel")
    assert proxy._cls is None
    assert calls == []

    assert proxy.channel == "dummy"
    assert calls == [".feishu"]
    assert proxy._cls is _DummyChannel
    assert proxy.channel == "dummy"
    assert calls == [".feishu"]


def test_lazy_from_config_delegates_to_real_class(monkeypatch):
    class _FactoryChannel(_DummyChannel):
        @classmethod
        def from_config(cls, process, config, **_kwargs):
            return SimpleNamespace(
                channel=cls.channel,
                process=process,
                config=config,
            )

    monkeypatch.setattr(
        registry_mod,
        "_import_channel_class",
        lambda key, module_name, class_name: _FactoryChannel,
    )

    proxy = _LazyChannelClass("feishu", ".feishu", "FeishuChannel")
    process = object()
    created = proxy.from_config(process=process, config={"enabled": True})
    assert created.channel == "dummy"
    assert created.process is process
    assert created.config == {"enabled": True}


def test_required_channel_import_failure_is_raised(monkeypatch):
    def _boom(key, module_name, class_name):
        raise ImportError("console module missing")

    monkeypatch.setattr(registry_mod, "_import_channel_class", _boom)

    with pytest.raises(ImportError, match="console module missing"):
        _load_builtin_channels()


def test_import_channel_class_rejects_non_channel(monkeypatch):
    def _fake_import(name, package=None):
        module = ModuleType("qwenpaw.app.channels.feishu")
        module.FeishuChannel = object
        return module

    monkeypatch.setattr(
        registry_mod, "importlib", _ImportlibStub(_fake_import)
    )

    with pytest.raises(TypeError, match="not a BaseChannel subtype"):
        _import_channel_class("feishu", ".feishu", "FeishuChannel")


def test_from_config_console_only_does_not_resolve_other_channels(
    monkeypatch,
):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    lazy_feishu = _LazyChannelClass("feishu", ".feishu", "FeishuChannel")

    monkeypatch.setattr(
        manager_mod,
        "get_channel_registry",
        lambda: {"console": ConsoleChannel, "feishu": lazy_feishu},
    )
    monkeypatch.setattr(
        manager_mod,
        "get_available_channels",
        lambda: ("console", "feishu"),
    )

    config = SimpleNamespace(
        channels=ChannelConfig(
            console=ConsoleConfig(enabled=True),
            feishu=FeishuConfig(enabled=False, app_id="x", app_secret="y"),
        ),
        show_tool_details=True,
    )
    manager = ChannelManager.from_config(
        process=MagicMock(),
        config=config,
    )

    assert [ch.channel for ch in manager.channels] == ["console"]
    assert lazy_feishu._cls is None


def test_from_config_skips_channel_when_lazy_import_fails(monkeypatch):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    def _boom(key, module_name, class_name):
        raise ImportError("lark_oapi missing")

    monkeypatch.setattr(registry_mod, "_import_channel_class", _boom)
    lazy_feishu = _LazyChannelClass("feishu", ".feishu", "FeishuChannel")

    monkeypatch.setattr(
        manager_mod,
        "get_channel_registry",
        lambda: {"console": ConsoleChannel, "feishu": lazy_feishu},
    )
    monkeypatch.setattr(
        manager_mod,
        "get_available_channels",
        lambda: ("console", "feishu"),
    )

    config = SimpleNamespace(
        channels=ChannelConfig(
            console=ConsoleConfig(enabled=True),
            feishu=FeishuConfig(enabled=True, app_id="x", app_secret="y"),
        ),
        show_tool_details=True,
    )
    manager = ChannelManager.from_config(
        process=MagicMock(),
        config=config,
    )

    assert [ch.channel for ch in manager.channels] == ["console"]


def test_from_env_skips_channel_when_lazy_import_fails(monkeypatch):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    def _boom(key, module_name, class_name):
        raise ImportError("lark_oapi missing")

    monkeypatch.setattr(registry_mod, "_import_channel_class", _boom)
    lazy_feishu = _LazyChannelClass("feishu", ".feishu", "FeishuChannel")

    monkeypatch.setattr(
        manager_mod,
        "get_channel_registry",
        lambda: {"console": ConsoleChannel, "feishu": lazy_feishu},
    )
    monkeypatch.setattr(
        manager_mod,
        "get_available_channels",
        lambda: ("console", "feishu"),
    )

    manager = ChannelManager.from_env(process=MagicMock())
    assert [ch.channel for ch in manager.channels] == ["console"]


def test_get_channel_registry_keys_include_unresolved_optional_channels(
    monkeypatch,
):
    imported: list[str] = []

    def _fake_import(key, module_name, class_name):
        imported.append(module_name)
        if module_name != ".console":
            raise AssertionError(f"unexpected eager import: {module_name}")
        return _DummyChannel

    monkeypatch.setattr(registry_mod, "_import_channel_class", _fake_import)
    monkeypatch.setattr(registry_mod, "_get_plugin_channels", lambda: {})

    registry = get_channel_registry()
    assert set(registry) == set(_BUILTIN_SPECS)
    assert imported == [".console"]


def test_registry_load_does_not_import_heavy_channel_sdks():
    """Fresh process: only console is imported when building the registry."""
    script = r"""
import sys
from qwenpaw.app.channels.registry import (
    _REQUIRED_CHANNEL_KEYS,
    _BUILTIN_SPECS,
    clear_builtin_channel_cache,
    get_channel_registry,
)

clear_builtin_channel_cache()
registry = get_channel_registry()
assert set(_BUILTIN_SPECS).issubset(set(registry))
assert "console" in registry

heavy = ("lark_oapi", "telegram", "slack_bolt", "aibot")
imported_heavy = [name for name in heavy if name in sys.modules]
assert imported_heavy == [], imported_heavy

optional_pkgs = (
    "qwenpaw.app.channels.feishu",
    "qwenpaw.app.channels.feishu.channel",
    "qwenpaw.app.channels.telegram",
    "qwenpaw.app.channels.telegram.channel",
    "qwenpaw.app.channels.slack",
    "qwenpaw.app.channels.slack.channel",
    "qwenpaw.app.channels.wecom",
    "qwenpaw.app.channels.wecom.channel",
)
imported_optional = [name for name in optional_pkgs if name in sys.modules]
assert imported_optional == [], imported_optional

assert "qwenpaw.app.channels.console" in sys.modules
console_cls = registry["console"]
assert getattr(console_cls, "channel", None) == "console"
for key in _BUILTIN_SPECS:
    if key in _REQUIRED_CHANNEL_KEYS:
        continue
    proxy = registry[key]
    assert getattr(proxy, "_cls", "missing") is None
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_SRC_DIR), env.get("PYTHONPATH", "")],
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert completed.returncode == 0, (
        completed.stdout + "\n" + completed.stderr
    )
