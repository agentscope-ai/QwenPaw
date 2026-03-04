# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib

from copaw.app.channels import registry


def test_get_channel_registry_skips_failed_builtin_import(
    monkeypatch,
) -> None:
    """A failing optional builtin import should not crash registry loading."""
    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None):
        if name == ".feishu" and package == registry.__package__:
            raise ImportError("simulated feishu import failure")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    loaded = registry.get_channel_registry()
    assert "console" in loaded
    assert "feishu" not in loaded
    assert "feishu" in registry.BUILTIN_CHANNEL_KEYS

