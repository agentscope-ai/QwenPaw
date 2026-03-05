# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import types

import pytest

from copaw.app.channels import registry


def test_get_channel_registry_skips_optional_builtin_import_error(
    monkeypatch: pytest.MonkeyPatch,
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


def test_get_channel_registry_skips_optional_builtin_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-import errors from optional builtins should also be tolerated."""
    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None):
        if name == ".feishu" and package == registry.__package__:
            raise RuntimeError("simulated feishu runtime failure")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    loaded = registry.get_channel_registry()
    assert "console" in loaded
    assert "feishu" not in loaded


def test_get_channel_registry_skips_optional_builtin_missing_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional builtin with unexpected module contents should be skipped."""
    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None):
        if name == ".feishu" and package == registry.__package__:
            return types.SimpleNamespace()
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    loaded = registry.get_channel_registry()
    assert "console" in loaded
    assert "feishu" not in loaded


def test_get_channel_registry_raises_for_required_console_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Console channel is required and should fail fast when unavailable."""
    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None):
        if name == ".console" and package == registry.__package__:
            raise ImportError("simulated console import failure")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    with pytest.raises(ImportError, match="simulated console import failure"):
        registry.get_channel_registry()
