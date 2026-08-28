# -*- coding: utf-8 -*-
"""Tests for selective built-in channel imports."""

from __future__ import annotations

from qwenpaw.app.channels import registry


def test_channel_keys_do_not_import_builtin_modules(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_get_plugin_channels", lambda: {})

    def fail_import(*_args, **_kwargs):
        raise AssertionError("built-in channel module was imported")

    monkeypatch.setattr(registry.importlib, "import_module", fail_import)

    keys = registry.get_channel_keys()

    assert "console" in keys
    assert "dingtalk" in keys


def test_channel_class_imports_only_requested_builtin(monkeypatch) -> None:
    registry.clear_builtin_channel_cache()
    imported: list[str] = []
    original_import = registry.importlib.import_module

    def record_import(name: str, package: str | None = None):
        imported.append(name)
        return original_import(name, package=package)

    monkeypatch.setattr(registry.importlib, "import_module", record_import)

    channel_class = registry.get_channel_class("console")

    assert channel_class is not None
    assert imported == [".console"]
