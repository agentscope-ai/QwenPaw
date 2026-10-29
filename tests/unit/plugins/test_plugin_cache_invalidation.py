# -*- coding: utf-8 -*-
"""Tests for best-effort import-cache invalidation in the plugin namespace (#8473).

On a host whose interpreter is CPython 3.11.9+ but whose
``importlib.metadata`` is older (Debian 12 ships 3.11.2),
``importlib.invalidate_caches()`` raises ``TypeError``:
``MetadataPathFinder.invalidate_caches() missing 1 required positional
argument: 'cls'``. The call sat in ``PluginNamespaceFinder.register()``,
which runs once per backend plugin during startup, so one raising stdlib call
took out the whole plugin system instead of one plugin.
"""

import importlib

import pytest

from qwenpaw.plugins import module_isolation
from qwenpaw.plugins.module_isolation import PluginNamespaceFinder

_BROKEN_CACHE_ERROR = (
    "MetadataPathFinder.invalidate_caches() missing 1 required positional argument: 'cls'"
)


def _break_invalidate_caches(monkeypatch):
    """Make ``importlib.invalidate_caches()`` raise like the old stdlib does."""

    def _boom():
        raise TypeError(_BROKEN_CACHE_ERROR)

    monkeypatch.setattr(importlib, "invalidate_caches", _boom)


@pytest.mark.parametrize(
    ("module_name", "plugin_builtins"),
    [
        ("plugin_one", {"utils": object()}),
        ("plugin_two", {"utils": object()}),
    ],
)
def test_register_survives_a_failing_cache_invalidation(
    monkeypatch,
    module_name,
    plugin_builtins,
):
    """A failing cache refresh must not stop a plugin from registering."""
    _break_invalidate_caches(monkeypatch)

    finder = PluginNamespaceFinder()
    finder.register(module_name, plugin_builtins)

    assert finder.is_registered(module_name)
    assert finder.builtins_for(module_name) == plugin_builtins


def test_cache_refresh_is_still_attempted(monkeypatch):
    """The refresh is not skipped: it is still called, and still best effort."""
    calls = []
    monkeypatch.setattr(
        module_isolation.importlib,
        "invalidate_caches",
        lambda: calls.append(1),
    )

    module_isolation._invalidate_import_caches()

    assert calls == [1]


def test_cache_refresh_swallows_the_failure(monkeypatch):
    """The helper reports the failure in the log instead of raising."""
    _break_invalidate_caches(monkeypatch)

    module_isolation._invalidate_import_caches()
