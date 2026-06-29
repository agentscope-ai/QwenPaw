# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel
"""Unit tests for scripts/pack/generate_plugin_metadata.py."""

from __future__ import annotations

import importlib.util
import json
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


def test_derive_compat_labels_uses_explicit_value(script: Any) -> None:
    assert script._derive_compat_labels(
        {"qwenpaw_compat_labels": ["2.x"]}
    ) == ["2.x"]
    assert script._derive_compat_labels(
        {"qwenpaw_compat_labels": ["1.x", "2.x"]}
    ) == ["1.x", "2.x"]


def test_derive_compat_labels_derives_from_min_version(script: Any) -> None:
    assert script._derive_compat_labels({"min_version": "1.1.5"}) == ["1.x"]
    assert script._derive_compat_labels({"min_version": "2.0.0"}) == ["2.x"]


def test_derive_compat_labels_defaults_to_1x(script: Any) -> None:
    assert script._derive_compat_labels({}) == ["1.x"]


def test_discover_and_pack_groups_by_compat_label(
    script: Any,
    tmp_path: Path,
) -> None:
    plugins_root = tmp_path / "plugins"

    v1_dir = plugins_root / "tool" / "v1-tool"
    v1_dir.mkdir(parents=True)
    (v1_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "v1-tool",
                "version": "1.0.0",
                "min_version": "1.1.0",
            }
        )
    )
    (v1_dir / "main.py").write_text("print('v1')")

    v2_dir = plugins_root / "bundle" / "v2-bundle"
    v2_dir.mkdir(parents=True)
    (v2_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "v2-bundle",
                "version": "2.0.0",
                "qwenpaw_compat_labels": ["2.x"],
            }
        )
    )
    (v2_dir / "plugin.py").write_text("print('v2')")

    dist_root = tmp_path / "dist"
    index, per_label = script.discover_and_pack(
        plugins_root, dist_root, "/files/plugins"
    )

    assert "v1-tool-1.0.0" in index["files"]
    assert "v2-bundle-2.0.0" in index["files"]
    v1_labels = index["files"]["v1-tool-1.0.0"]["qwenpaw_compat_labels"]
    v2_labels = index["files"]["v2-bundle-2.0.0"]["qwenpaw_compat_labels"]
    assert v1_labels == ["1.x"]
    assert v2_labels == ["2.x"]

    assert "1.x" in per_label
    assert "2.x" in per_label
    assert "v1-tool-1.0.0" in per_label["1.x"]["files"]
    assert "v2-bundle-2.0.0" in per_label["2.x"]["files"]
    assert "v2-bundle-2.0.0" not in per_label["1.x"]["files"]
    assert "v1-tool-1.0.0" not in per_label["2.x"]["files"]


def test_discover_and_pack_skips_publish_false(
    script: Any,
    tmp_path: Path,
) -> None:
    plugins_root = tmp_path / "plugins"
    plugin_dir = plugins_root / "tool" / "unpublished"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "unpublished",
                "version": "1.0.0",
                "publish": False,
            }
        )
    )

    dist_root = tmp_path / "dist"
    index, per_label = script.discover_and_pack(
        plugins_root, dist_root, "/files/plugins"
    )

    assert "unpublished-1.0.0" not in index["files"]
    assert not per_label


def test_build_metadata_includes_compat_labels(
    script: Any,
    tmp_path: Path,
) -> None:
    manifest = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "min_version": "2.0.0",
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

    assert metadata["qwenpaw_compat_labels"] == ["2.x"]
