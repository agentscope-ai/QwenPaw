# -*- coding: utf-8 -*-
"""Unit tests for src/qwenpaw/app/routers/plugins.py helpers."""

from __future__ import annotations

from qwenpaw.app.routers.plugins import (
    _current_qwenpaw_compat_label,
    _plugin_has_compat_label,
)
from qwenpaw.__version__ import __version__


def test_current_qwenpaw_compat_label_matches_version() -> None:
    major = __version__.split(".", 1)[0]
    assert _current_qwenpaw_compat_label() == f"{major}.x"


def test_plugin_has_compat_label_without_labels() -> None:
    assert _plugin_has_compat_label({}, "2.x") is True
    assert _plugin_has_compat_label({"version": "1.0.0"}, "2.x") is True


def test_plugin_has_compat_label_with_matching_label() -> None:
    plugin = {"qwenpaw_compat_labels": ["1.x", "2.x"]}
    assert _plugin_has_compat_label(plugin, "2.x") is True


def test_plugin_has_compat_label_without_matching_label() -> None:
    plugin = {"qwenpaw_compat_labels": ["1.x"]}
    assert _plugin_has_compat_label(plugin, "2.x") is False


def test_plugin_has_compat_label_ignores_empty_list() -> None:
    plugin = {"qwenpaw_compat_labels": []}
    assert _plugin_has_compat_label(plugin, "2.x") is True
