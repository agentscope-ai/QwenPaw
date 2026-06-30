# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel
"""Unit tests for scripts/pack/generate_plugin_metadata.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "pack" / "generate_plugin_metadata.py"


def _load_script_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "generate_plugin_metadata",
        SCRIPT_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_plugin_metadata"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> Any:
    return _load_script_module()


def test_build_metadata_includes_qwenpaw_version(
    script: Any,
    tmp_path: Path,
) -> None:
    manifest = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "qwenpaw_version": {"min": "1.1.6", "max": "2.1.0"},
    }
    zip_path = tmp_path / "demo-1.0.0.zip"
    zip_path.write_bytes(b"fake")

    metadata = script._build_metadata(
        manifest,
        file_id="demo-1.0.0",
        plugin_id="demo",
        version="1.0.0",
        kind="tool",
        zip_path=zip_path,
        cdn_path="/files/plugins/tool/demo/demo-1.0.0.zip",
    )

    assert metadata["qwenpaw_version"] == {"min": "1.1.6", "max": "2.1.0"}
    assert "min_version" not in metadata


def test_build_metadata_falls_back_to_min_max_version(
    script: Any,
    tmp_path: Path,
) -> None:
    manifest = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "min_version": "1.1.6",
        "max_version": "2.1.0",
    }
    zip_path = tmp_path / "demo-1.0.0.zip"
    zip_path.write_bytes(b"fake")

    metadata = script._build_metadata(
        manifest,
        file_id="demo-1.0.0",
        plugin_id="demo",
        version="1.0.0",
        kind="tool",
        zip_path=zip_path,
        cdn_path="/files/plugins/tool/demo/demo-1.0.0.zip",
    )

    assert metadata["min_version"] == "1.1.6"
    assert metadata["max_version"] == "2.1.0"
    assert "qwenpaw_version" not in metadata
