# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "pack-tauri"
    / "generate_update_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "generate_update_manifest",
    _SCRIPT,
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


@pytest.mark.parametrize(
    ("python_version", "tauri_version"),
    [
        ("2.0.0", "2.0.0"),
        ("2.0.0.post1", "2.0.0+post.1"),
        ("2.0.0.post2", "2.0.0+post.2"),
        ("2.0.0a1", "2.0.0-alpha.1"),
        ("2.0.0rc1.dev2", "2.0.0-rc.1.dev.2"),
        ("2.0.0.post1.dev2", "2.0.0-dev.2+post.1"),
    ],
)
def test_to_semver_preserves_pep440_post_release_ordering(
    python_version: str,
    tauri_version: str,
):
    assert _MODULE.to_semver(python_version) == tauri_version
