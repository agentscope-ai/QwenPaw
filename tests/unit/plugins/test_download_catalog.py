# -*- coding: utf-8 -*-
"""Unit tests for src/qwenpaw/plugins/download_catalog.py."""

from __future__ import annotations

from qwenpaw.plugins.download_catalog import _is_entry_compatible


def test_entry_with_qwenpaw_version_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {"min": "1.1.6", "max": "2.1.0"},
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_qwenpaw_version_incompatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {"min": "0.1.0", "max": "1.1.0"},
    }
    assert _is_entry_compatible(entry) is False


def test_entry_with_only_min_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {"min": "2.0.0"},
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_only_min_incompatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {"min": "3.0.0"},
    }
    assert _is_entry_compatible(entry) is False


def test_entry_without_version_constraints_is_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_malformed_qwenpaw_version_is_compatible() -> None:
    """Non-dict qwenpaw_version is treated as no constraint."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": "not-a-dict",
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_empty_dict_qwenpaw_version() -> None:
    """Empty dict qwenpaw_version triggers compat check with defaults."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {},
    }
    # Empty dict is isinstance(dict) but has no min/max, should
    # still pass through PluginManifest validation or fallback gracefully
    result = _is_entry_compatible(entry)
    assert isinstance(result, bool)
