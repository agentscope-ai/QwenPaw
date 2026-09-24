# -*- coding: utf-8 -*-
"""Tests for lazy channel-class resolution in the registry."""

import sys

from qwenpaw.app.channels import registry as channel_registry
from qwenpaw.app.channels.registry import (
    get_available_keys,
    get_channel_class,
)


def _channel_modules_loaded() -> set[str]:
    return {
        name
        for name in sys.modules
        if name.startswith("qwenpaw.app.channels.")
        and not name.endswith(("registry", "base", "manager"))
    }


def test_get_available_keys_imports_no_channel_modules():
    before = _channel_modules_loaded()
    keys = get_available_keys()
    after = _channel_modules_loaded()

    assert "console" in keys
    assert "feishu" in keys
    assert after <= before  # nothing new imported


def test_get_channel_class_imports_only_the_requested_channel():
    before = _channel_modules_loaded()
    cls = get_channel_class("console")
    after = _channel_modules_loaded()

    assert cls is not None
    assert cls.__name__ == "ConsoleChannel"
    # only the console channel module may appear
    added = after - before
    assert all(".console" in name or ".base" in name for name in added)


def test_get_channel_class_caches_per_key():
    first = get_channel_class("console")
    second = get_channel_class("console")

    assert first is second


def test_get_channel_class_unknown_key_returns_none():
    assert get_channel_class("no-such-channel") is None


def test_registry_backcompat_still_returns_all():
    # full registry keeps working for callers that genuinely want all
    reg = channel_registry.get_channel_registry()

    assert "console" in reg
    assert "feishu" in reg
