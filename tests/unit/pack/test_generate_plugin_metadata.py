# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Required-file validation in the plugin pack pipeline.

A plugin whose declared ``entry`` files or ``pack_requires`` artifacts are
missing on disk must fail the pack loudly instead of shipping a broken zip.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_FILE = (
    REPOSITORY_ROOT / "scripts" / "pack" / "generate_plugin_metadata.py"
)


def _load_packer():
    spec = importlib.util.spec_from_file_location(
        "generate_plugin_metadata_under_test",
        SCRIPT_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packer = _load_packer()


def _write_plugin(
    plugins_root: Path,
    manifest: dict,
    files: list[str],
) -> Path:
    plugin_dir = plugins_root / "apps" / manifest["id"]
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    for rel in files:
        target = plugin_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("content", encoding="utf-8")
    return plugin_dir


def _manifest(**overrides) -> dict:
    manifest = {
        "id": "demo",
        "version": "1.0.0",
        "entry": {
            "backend": "backend/main.py",
            "frontend": "ui/dist/index.js",
        },
    }
    manifest.update(overrides)
    return manifest


def test_complete_plugin_packs_and_reports_no_failures(tmp_path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        _manifest(pack_requires=["ui/dist/vendor/index.html"]),
        ["backend/main.py", "ui/dist/index.js", "ui/dist/vendor/index.html"],
    )

    index, failed = packer.discover_and_pack(
        plugins_root,
        tmp_path / "dist",
        "/files/plugins",
    )

    assert failed == []
    assert "demo-1.0.0" in index["files"]
    assert (tmp_path / "dist" / "apps" / "demo" / "demo-1.0.0.zip").is_file()


def test_missing_entry_file_fails_the_pack(tmp_path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        _manifest(),
        ["backend/main.py"],  # ui/dist/index.js is never built
    )

    index, failed = packer.discover_and_pack(
        plugins_root,
        tmp_path / "dist",
        "/files/plugins",
    )

    assert failed == ["demo"]
    assert index["files"] == {}
    assert not (tmp_path / "dist" / "apps" / "demo").exists()


def test_missing_pack_requires_artifact_fails_the_pack(
    tmp_path,
    capsys,
) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        _manifest(
            pack_requires=["ui/dist/vendor/index.html"],
            pack_requires_hint="Run scripts/vendor.sh first.",
        ),
        ["backend/main.py", "ui/dist/index.js"],
    )

    index, failed = packer.discover_and_pack(
        plugins_root,
        tmp_path / "dist",
        "/files/plugins",
    )

    assert failed == ["demo"]
    assert index["files"] == {}
    captured = capsys.readouterr()
    assert "ui/dist/vendor/index.html" in captured.err
    assert "Run scripts/vendor.sh first." in captured.err


def test_required_relpaths_merges_entries_and_drops_unsafe() -> None:
    required = packer._required_relpaths(
        _manifest(
            pack_requires=[
                "ui/dist/index.js",  # duplicate of the entry
                "ui/dist/vendor/index.html",
                "../outside.txt",  # traversal is ignored
                "",  # empty is ignored
            ],
        ),
    )

    assert required == [
        "backend/main.py",
        "ui/dist/index.js",
        "ui/dist/vendor/index.html",
    ]
