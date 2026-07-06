# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position
"""Unit tests for scripts/pack/generate_plugin_metadata.py:get_version."""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts/pack to the path so we can import the module
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent.parent.parent
        / "scripts"
        / "pack",
    ),
)

from generate_plugin_metadata import get_version  # noqa: E402


def test_structured_qwenpaw_version_passthrough() -> None:
    manifest = {"qwenpaw_version": {"min": "1.1.6", "max": "2.1.0"}}
    assert get_version(manifest) == {"min": "1.1.6", "max": "2.1.0"}


def test_structured_qwenpaw_version_only_min() -> None:
    manifest = {"qwenpaw_version": {"min": "2.0.0"}}
    assert get_version(manifest) == {"min": "2.0.0"}


def test_structured_qwenpaw_version_strips_leading_v() -> None:
    manifest = {"qwenpaw_version": {"min": "v1.0.0", "max": "v2.0.0"}}
    assert get_version(manifest) == {"min": "1.0.0", "max": "2.0.0"}


def test_structured_qwenpaw_version_strips_whitespace() -> None:
    manifest = {"qwenpaw_version": {"min": " 1.0.0 ", "max": " 2.0.0\t"}}
    assert get_version(manifest) == {"min": "1.0.0", "max": "2.0.0"}


def test_legacy_min_and_max() -> None:
    manifest = {"min_version": "1.1.0", "max_version": "2.0.0"}
    assert get_version(manifest) == {"min": "1.1.0", "max": "2.0.0"}


def test_legacy_only_min() -> None:
    manifest = {"min_version": "1.1.0"}
    assert get_version(manifest) == {"min": "1.1.0"}


def test_legacy_only_max() -> None:
    manifest = {"max_version": "2.0.0"}
    assert get_version(manifest) == {"max": "2.0.0"}


def test_legacy_strips_leading_v() -> None:
    manifest = {"min_version": "v1.0.0", "max_version": "V2.0.0"}
    assert get_version(manifest) == {"min": "1.0.0", "max": "2.0.0"}


def test_legacy_strips_whitespace() -> None:
    manifest = {"min_version": " 1.0.0 ", "max_version": "\t2.0.0 "}
    assert get_version(manifest) == {"min": "1.0.0", "max": "2.0.0"}


def test_no_constraints_returns_none() -> None:
    manifest = {"id": "demo", "version": "1.0.0"}
    assert get_version(manifest) is None


def test_non_dict_qwenpaw_version_falls_to_legacy() -> None:
    """Non-dict qwenpaw_version is ignored; falls back to min/max."""
    manifest = {
        "qwenpaw_version": "invalid",
        "min_version": "1.0.0",
    }
    assert get_version(manifest) == {"min": "1.0.0"}


def test_non_dict_qwenpaw_version_no_legacy_returns_none() -> None:
    manifest = {"qwenpaw_version": "invalid"}
    assert get_version(manifest) is None


def test_prerelease_version_string_in_legacy() -> None:
    """Pre-release suffix like '1.0.0-rc1' passes through as-is."""
    manifest = {"min_version": "1.0.0-rc1", "max_version": "2.0.0-beta"}
    assert get_version(manifest) == {
        "min": "1.0.0-rc1",
        "max": "2.0.0-beta",
    }


def test_extra_keys_in_qwenpaw_version_ignored() -> None:
    """Only 'min' and 'max' keys are retained."""
    manifest = {
        "qwenpaw_version": {
            "min": "1.0.0",
            "max": "2.0.0",
            "note": "should be ignored",
        },
    }
    assert get_version(manifest) == {"min": "1.0.0", "max": "2.0.0"}
