# -*- coding: utf-8 -*-
"""Chrome plugin integration contracts grouped by runtime boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# test_chrome_selfcontained_plugin.py

PLUGIN = Path("plugins/bundle/chrome")


def _python_files() -> list[Path]:
    return [
        path
        for path in PLUGIN.rglob("*.py")
        if "node_modules" not in path.parts
    ]


@pytest.mark.integration
@pytest.mark.p1
def test_chrome_plugin_bundle_is_self_contained() -> None:
    required = (
        "assets/extensions/chrome/manifest.json",
        "assets/extensions/chrome/service_worker.js",
        "assets/scripts/nm_host.py",
        "api/routes.py",
        "extension_setup.py",
        "plugin.py",
        "transport/state.py",
    )

    for relative_path in required:
        path = PLUGIN / relative_path
        assert path.is_file() and path.stat().st_size > 0

    assert not (PLUGIN / "main.py").exists()
    assert not (PLUGIN / "action_runtime").exists()
    assert not (PLUGIN / "backend").exists()
    assert not (PLUGIN / "engine_impl.py").exists()


@pytest.mark.integration
@pytest.mark.p1
def test_chrome_plugin_manifest_uses_standard_plugin_entries() -> None:
    manifest = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    extension_manifest = json.loads(
        (PLUGIN / "assets/extensions/chrome/manifest.json").read_text(
            encoding="utf-8",
        ),
    )

    assert manifest["entry"] == {
        "backend": "plugin.py",
        "frontend": "dist/index.js",
    }
    assert "setup" not in manifest
    assert "meta" not in manifest
    assert (PLUGIN / "dist/index.js").stat().st_size > 0
    assert "browser_core_release" not in extension_manifest
