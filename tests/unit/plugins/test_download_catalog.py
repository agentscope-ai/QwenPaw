# -*- coding: utf-8 -*-
"""Unit tests for src/qwenpaw/plugins/download_catalog.py."""

from __future__ import annotations

import pytest

from qwenpaw.plugins.download_catalog import _is_entry_compatible
from qwenpaw.__version__ import __version__


@pytest.fixture
def current_label() -> str:
    major = __version__.split(".", 1)[0]
    return f"{major}.x"


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


def test_entry_with_min_version_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "min_version": "2.0.0",
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_min_version_incompatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "min_version": "3.0.0",
    }
    assert _is_entry_compatible(entry) is False


def test_entry_with_min_max_version() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "min_version": "1.1.6",
        "max_version": "2.1.0",
    }
    assert _is_entry_compatible(entry) is True


def test_entry_without_version_constraints_is_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
    }
    assert _is_entry_compatible(entry) is True
