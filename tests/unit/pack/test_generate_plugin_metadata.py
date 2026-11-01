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
import zipfile

import pytest

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
    category: str = "apps",
) -> Path:
    plugin_dir = plugins_root / category / manifest["id"]
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


@pytest.mark.parametrize(
    "category,manifest,files",
    [
        ("apps", _manifest(), ["backend/main.py"]),
        (
            "channel",
            _manifest(
                id="demo-channel",
                version="0.1.0",
                type="channel",
                entry={"backend": "plugin.py"},
            ),
            [],
        ),
    ],
    ids=["app-frontend", "channel-backend"],
)
def test_missing_entry_file_fails_the_pack(
    tmp_path,
    category,
    manifest,
    files,
) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(plugins_root, manifest, files, category=category)

    index, failed = packer.discover_and_pack(
        plugins_root,
        tmp_path / "dist",
        "/files/plugins",
    )

    assert failed == [manifest["id"]]
    assert index["files"] == {}
    assert not (tmp_path / "dist" / category / manifest["id"]).exists()


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


def _write_channel(plugins_root: Path, plugin_id="demo-channel", **settings):
    """Create a channel source without depending on a real platform SDK."""
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "type": "channel",
        "entry": {"backend": "plugin.py"},
        **settings,
    }
    plugin_dir = _write_plugin(plugins_root, manifest, [], category="channel")
    (plugin_dir / "plugin.py").write_text(
        "plugin = object()\n",
        encoding="utf-8",
        newline="\n",
    )
    return plugin_dir


def test_channel_discovery_builds_archive_and_channel_metadata(tmp_path):
    plugins_root = tmp_path / "plugins"
    _write_channel(plugins_root)
    _write_channel(plugins_root, "private-channel", publish=False)

    index, failed = packer.discover_and_pack(
        plugins_root,
        tmp_path / "dist",
        "/files/plugins",
    )

    assert failed == []
    assert set(index["files"]) == {"demo-channel-0.1.0"}
    metadata = index["files"]["demo-channel-0.1.0"]
    assert metadata["platform"] == "channel"
    assert (
        metadata["url"]
        == "/files/plugins/channel/demo-channel/demo-channel-0.1.0.zip"
    )
    assert index["platforms"]["channel"]["versions"] == ["demo-channel-0.1.0"]
    archive = tmp_path / "dist/channel/demo-channel/demo-channel-0.1.0.zip"
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert set(zipped.namelist()) == {
            "demo-channel/plugin.json",
            "demo-channel/plugin.py",
        }
        assert zipped.read("demo-channel/plugin.py") == b"plugin = object()\n"
    assert not (tmp_path / "dist/channel/private-channel").exists()
