# -*- coding: utf-8 -*-
import importlib
from types import SimpleNamespace

import pytest

from qwenpaw._version_compat import check_plugin_version_compat

version_module = importlib.import_module("qwenpaw.__version__")


def _manifest(min_version: str) -> SimpleNamespace:
    return SimpleNamespace(
        qwenpaw_version=SimpleNamespace(min=min_version, max="3.0.0"),
        min_version="0.0.0",
        max_version="",
    )


@pytest.mark.parametrize(
    ("current", "compatible"),
    [
        ("2.1.1a1", False),
        ("2.1.1b1", False),
        ("2.1.1b2", True),
        ("2.1.1rc1", True),
        ("2.1.1", True),
    ],
)
def test_prerelease_minimum_preserves_pep440_ordering(
    monkeypatch: pytest.MonkeyPatch,
    current: str,
    compatible: bool,
) -> None:
    monkeypatch.setattr(version_module, "__version__", current)

    result, _ = check_plugin_version_compat(_manifest("2.1.1b2"))

    assert result is compatible


def test_stable_minimum_still_accepts_same_release_prerelease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_module, "__version__", "2.1.1a1")

    result, _ = check_plugin_version_compat(_manifest("2.1.1"))

    assert result is True
