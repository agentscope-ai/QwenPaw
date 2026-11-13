# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position
"""Unit tests for scripts/pack/generate_plugin_metadata.py."""

from __future__ import annotations

import json
import runpy
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

# Add scripts/pack to the path so we can import the module
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent.parent.parent
        / "scripts"
        / "pack",
    ),
)

from generate_plugin_metadata import (  # noqa: E402
    _iter_tree_relpaths,
    _normalize_pack_exclude,
    _zip_plugin,
    build_official_channel_bundle,
    discover_and_pack,
    get_version,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_official_channel_publication_matches_bundled_content(tmp_path):
    inventory = runpy.run_path(
        str(REPO_ROOT / "src/qwenpaw/plugins/official_channel_catalog.py"),
    )["OFFICIAL_CHANNELS"]
    owners = {row["plugin_id"] for row in inventory}
    public = tmp_path / "public"
    index, failed = discover_and_pack(
        REPO_ROOT / "plugins",
        public,
        "/files/plugins",
        only=list(owners),
    )
    assert not failed
    entries = {entry["plugin_id"]: entry for entry in index["files"].values()}
    assert set(entries) == owners
    assert entries["azure-bot"]["url"].startswith(
        "/files/plugins/channel/azure-bot/",
    )

    bundled = tmp_path / "bundled"
    bundle_index = json.loads(
        build_official_channel_bundle(
            REPO_ROOT,
            bundled,
            host_version="2.3.0",
        ).read_text(),
    )
    for row in bundle_index["plugins"]:
        entry = entries[row["plugin_id"]]
        assert entry["platform"] == "channel"
        assert entry["version"] == row["version"]
        with (
            zipfile.ZipFile(
                public / "channel" / row["plugin_id"] / entry["filename"],
            ) as online,
            zipfile.ZipFile(bundled / row["filename"]) as offline,
        ):
            assert {name: online.read(name) for name in online.namelist()} == {
                name: offline.read(name) for name in offline.namelist()
            }


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


# --- pack_exclude ---------------------------------------------------------


def _make_plugin_tree(root: Path) -> Path:
    """Create a plugin dir with runtime files and dev-only files."""
    plugin_dir = root / "demo-plugin"
    files = [
        "plugin.json",
        "requirements.txt",
        "backend/main.py",
        "backend/api/router.py",
        "backend/tests/test_api.py",
        "backend/pytest.ini",
        "e2e/test_shell.py",
        "ui/dist/index.js",
        "ui/src/App.tsx",
        "ui/package.json",
    ]
    for rel in files:
        path = plugin_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return plugin_dir


def _demo_manifest() -> dict:
    return {
        "id": "demo-plugin",
        "version": "1.0.0",
        "entry": {
            "backend": "backend/main.py",
            "frontend": "ui/dist/index.js",
        },
        "pack_exclude": [
            "backend/tests",
            "backend/pytest.ini",
            "e2e",
            "ui/src",
            "ui/package.json",
        ],
    }


def test_normalize_pack_exclude_missing_returns_empty() -> None:
    assert not _normalize_pack_exclude({})


def test_normalize_pack_exclude_non_list_ignored() -> None:
    assert not _normalize_pack_exclude({"pack_exclude": "backend/tests"})


def test_normalize_pack_exclude_strips_slashes_and_backslashes() -> None:
    manifest = {"pack_exclude": ["e2e/", "ui\\src", "/scripts"]}
    assert _normalize_pack_exclude(manifest) == [
        "e2e",
        "ui/src",
        "scripts",
    ]


def test_normalize_pack_exclude_drops_traversal_and_empty() -> None:
    manifest = {"pack_exclude": ["../secrets", "a/../../b", "", "."]}
    assert not _normalize_pack_exclude(manifest)


def test_pack_exclude_never_drops_manifest_or_entries(
    tmp_path: Path,
) -> None:
    """plugin.json and entry files survive even a hostile pack_exclude."""
    plugin_dir = _make_plugin_tree(tmp_path)
    manifest = _demo_manifest()
    manifest["pack_exclude"] = [
        "plugin.json",
        "backend/main.py",
        "ui/dist/index.js",
    ]
    rels = _iter_tree_relpaths(plugin_dir, manifest)
    assert "plugin.json" in rels
    assert "backend/main.py" in rels
    assert "ui/dist/index.js" in rels


def test_pack_exclude_exact_prefix_no_sibling_bleed(tmp_path: Path) -> None:
    """'e2e' must not exclude a sibling like 'e2e-extra/'."""
    plugin_dir = _make_plugin_tree(tmp_path)
    extra = plugin_dir / "e2e-extra" / "keep.py"
    extra.parent.mkdir(parents=True)
    extra.write_text("x", encoding="utf-8")
    rels = _iter_tree_relpaths(plugin_dir, _demo_manifest())
    assert "e2e-extra/keep.py" in rels
    assert "e2e/test_shell.py" not in rels


def test_zip_plugin_applies_pack_exclude(tmp_path: Path) -> None:
    plugin_dir = _make_plugin_tree(tmp_path)
    manifest = _demo_manifest()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    out_zip = tmp_path / "out" / "demo-plugin-1.0.0.zip"
    _zip_plugin(plugin_dir, out_zip, manifest)
    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
    assert "demo-plugin/backend/main.py" in names
    assert "demo-plugin/ui/dist/index.js" in names
    assert "demo-plugin/plugin.json" in names
    assert not any("backend/tests" in n for n in names)
    assert not any("/e2e/" in n for n in names)
    assert not any("ui/src" in n for n in names)


def test_zip_plugin_missing_entry_leaves_no_artifact(tmp_path: Path) -> None:
    plugin_dir = _make_plugin_tree(tmp_path)
    manifest = _demo_manifest()
    (plugin_dir / "ui/dist/index.js").unlink()
    out_zip = tmp_path / "out" / "demo-plugin-1.0.0.zip"

    with pytest.raises(FileNotFoundError, match="ui/dist/index.js"):
        _zip_plugin(plugin_dir, out_zip, manifest)

    assert not out_zip.exists()


def test_zip_plugin_without_manifest_packs_everything(
    tmp_path: Path,
) -> None:
    """Backwards compatibility: no manifest arg means no pack_exclude."""
    plugin_dir = _make_plugin_tree(tmp_path)
    out_zip = tmp_path / "out" / "demo-plugin-1.0.0.zip"
    _zip_plugin(plugin_dir, out_zip)
    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
    assert "demo-plugin/backend/tests/test_api.py" in names
    assert "demo-plugin/ui/src/App.tsx" in names


def _copy_harness_plugins(root: Path) -> Path:
    plugins_root = root / "plugins"
    for vendor in ("codex", "qoder"):
        shutil.copytree(
            REPO_ROOT / "plugins" / "harness" / vendor,
            plugins_root / "harness" / vendor,
            ignore=shutil.ignore_patterns(
                "node_modules",
                "dist",
                "__pycache__",
                ".pytest_cache",
            ),
        )
        # Backend unit CI has no frontend build. Supply only the declared
        # entry; compiled bundles are covered by the Harness packaging job.
        frontend_entry = (
            plugins_root / "harness" / vendor / "frontend/dist/index.js"
        )
        frontend_entry.parent.mkdir(parents=True)
        frontend_entry.write_text("export {};\n", encoding="utf-8")
    return plugins_root


def test_real_harness_archives_contain_own_entries_and_frontends(
    tmp_path: Path,
) -> None:
    plugins_root = _copy_harness_plugins(tmp_path)
    dist = tmp_path / "dist"
    index, failed = discover_and_pack(plugins_root, dist, "/files/plugins")

    assert not failed
    expected = {"codex", "qoder"}
    assert set(index["platforms"]["harness"]["versions"]) == {
        f"qwenpaw-harness-{vendor}-1.0.0" for vendor in expected
    }
    for vendor in expected:
        plugin_id = f"qwenpaw-harness-{vendor}"
        archive_path = dist / "harness" / plugin_id / f"{plugin_id}-1.0.0.zip"
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            requirements = archive.read(
                f"{plugin_id}/requirements.txt",
            ).decode()
        assert f"{plugin_id}/plugin.json" in names
        assert f"{plugin_id}/main.py" in names
        assert f"{plugin_id}/io_helpers.py" in names
        assert f"{plugin_id}/frontend/dist/index.js" in names
        assert not any(
            part in {"_shared", "node_modules", "__pycache__"}
            for name in names
            for part in Path(name).parts
        )
        assert not any(
            name.startswith(f"{plugin_id}/frontend/src/") for name in names
        )
        assert not any(
            name.startswith(f"{plugin_id}/tests/") for name in names
        )
        other = (expected - {vendor}).pop()
        assert not any(other in name for name in names)
        assert other not in requirements
        assert index["files"][f"{plugin_id}-1.0.0"]["platform"] == "harness"


def test_private_channel_zip_preserves_runtime_and_source_manifest(tmp_path):
    """Local zipper supports private previews while honoring exclusions."""
    plugin_dir = tmp_path / "channel-preview"
    plugin_dir.mkdir()
    manifest = {
        "id": "channel-preview",
        "version": "0.1.0",
        "type": "channel",
        "publish": False,
        "entry": {"backend": "plugin.py"},
        "pack_exclude": ["tests"],
    }
    manifest_bytes = json.dumps(manifest).encode()
    (plugin_dir / "plugin.json").write_bytes(manifest_bytes)
    (plugin_dir / "plugin.py").write_text("from .channel import Channel\n")
    (plugin_dir / "channel.py").write_text("class Channel: pass\n")
    (plugin_dir / "requirements.txt").write_text("example-sdk>=1.0\n")
    (plugin_dir / "tests").mkdir()
    (plugin_dir / "tests/test_channel.py").write_text("assert True\n")
    archive = tmp_path / "preview.zip"

    _zip_plugin(plugin_dir, archive, manifest)

    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert set(zipped.namelist()) == {
            "channel-preview/plugin.json",
            "channel-preview/plugin.py",
            "channel-preview/channel.py",
            "channel-preview/requirements.txt",
        }
        assert zipped.read("channel-preview/plugin.json") == manifest_bytes
    assert (plugin_dir / "plugin.json").read_bytes() == manifest_bytes


def test_release_content_digest_uses_delivered_paths_and_bytes(tmp_path):
    import os
    from generate_plugin_metadata import plugin_content_digest

    source = _make_plugin_tree(tmp_path)
    manifest = _demo_manifest()
    original = plugin_content_digest(source, manifest)
    os.utime(source / "backend/main.py", (100, 100))
    (source / "ui/src/App.tsx").write_text("excluded change")
    assert plugin_content_digest(source, manifest) == original
    (source / "backend/main.py").rename(source / "backend/renamed.py")
    assert plugin_content_digest(source, manifest) != original
    (source / "backend/renamed.py").rename(source / "backend/main.py")
    (source / "backend/main.py").write_text("delivered change")
    assert plugin_content_digest(source, manifest) != original


@pytest.mark.parametrize(
    "version,changed,allowed",
    [
        ("1.0.0", False, True),
        ("1.0.0", True, False),
        ("1.0.1", True, True),
        ("0.9.0", False, False),
    ],
)
def test_pr_version_guard_covers_private_bundled_channels(
    tmp_path,
    version,
    changed,
    allowed,
):
    from check_plugin_versions import check_pr

    for side in ("base", "candidate"):
        project = tmp_path / side
        scripts = project / "scripts/pack"
        scripts.mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "scripts/pack/generate_plugin_metadata.py",
            scripts,
        )
        catalog = project / "src/qwenpaw/plugins/official_channel_catalog.py"
        catalog.parent.mkdir(parents=True)
        catalog.write_text(
            "OFFICIAL_CHANNELS = ({'plugin_id': 'example', "
            "'source_dir': 'example', 'channel_key': 'example'},)\n",
        )
        plugin = project / "plugins/channel/example"
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "example",
                    "type": "channel",
                    "publish": False,
                    "version": version if side == "candidate" else "1.0.0",
                    "entry": {"backend": "main.py"},
                },
            ),
        )
        (plugin / "main.py").write_text(
            "changed" if side == "candidate" and changed else "original",
        )
    if allowed:
        check_pr(tmp_path / "base", tmp_path / "candidate")
    else:
        with pytest.raises(ValueError, match="example"):
            check_pr(tmp_path / "base", tmp_path / "candidate")


@pytest.mark.parametrize("failure", [None, "content", "read", "race"])
def test_immutable_release_keeps_original_artifact_and_identity(
    tmp_path,
    failure,
):
    import hashlib
    from check_plugin_versions import check_release

    class Store:
        def __init__(self):
            self.objects = {}

        def read(self, key):
            if failure == "read":
                raise PermissionError("remote read denied")
            return self.objects.get(key)

        def create(self, key, data, *, public=False):
            if failure == "race" and key.endswith(".json"):
                record = json.loads(data)
                record["content_sha256"] = "0" * 64
                self.objects[key] = json.dumps(record).encode()
            return self.objects.setdefault(key, data)

    source = _make_plugin_tree(tmp_path)
    manifest = _demo_manifest()
    (source / "plugin.json").write_text(json.dumps(manifest))
    archive = tmp_path / "dist/tool/demo-plugin/demo-plugin-1.0.0.zip"
    _zip_plugin(source, archive, manifest)
    original = archive.read_bytes()
    index_path = tmp_path / "dist/index.json"
    index_path.write_text(
        json.dumps(
            {
                "product": "plugins",
                "files": {archive.stem: {}},
            },
        ),
    )
    store = Store()
    if failure in {"read", "race"}:
        with pytest.raises((PermissionError, ValueError)):
            check_release(tmp_path / "dist", store, publish=True)
        assert not any(key.endswith(".zip") for key in store.objects)
        return
    check_release(tmp_path / "dist", store, publish=True)
    before = dict(store.objects)
    if failure == "content":
        (source / "backend/main.py").write_text("new release content")
    # Same bytes with different ZIP metadata must reuse the published ZIP.
    _zip_plugin(source, archive, manifest, deterministic=True)
    index_path.write_text(
        json.dumps(
            {
                "product": "plugins",
                "files": {
                    archive.stem: {
                        "sha256": hashlib.sha256(
                            archive.read_bytes(),
                        ).hexdigest(),
                    },
                },
            },
        ),
    )
    if failure == "content":
        with pytest.raises(ValueError, match="demo-plugin"):
            check_release(tmp_path / "dist", store, publish=True)
        assert store.objects == before
    else:
        check_release(tmp_path / "dist", store, publish=True)
        assert store.objects == before
        assert (
            store.objects[
                "files/plugins/tool/demo-plugin/demo-plugin-1.0.0.zip"
            ]
            == original
        )
        published = json.loads(index_path.read_text())["files"][archive.stem]
        assert published["sha256"] == hashlib.sha256(original).hexdigest()
        assert published["size_bytes"] == len(original)


@pytest.mark.parametrize("dependency", ["data_ref", "harness_script"])
def test_pr_version_guard_rebuilds_external_frontend_inputs(
    tmp_path,
    monkeypatch,
    dependency,
):
    import check_plugin_versions as guard

    plugin_id = "qwenpaw-data" if dependency == "data_ref" else "example"
    kind = "apps" if dependency == "data_ref" else "harness"
    relative = (
        ".github/workflows/qwenpaw-data-release.yml"
        if dependency == "data_ref"
        else "scripts/pack/build_harness_frontends.sh"
    )
    for side, pin in (("base", "v1"), ("candidate", "v2")):
        project = tmp_path / side
        scripts = project / "scripts/pack"
        scripts.mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "scripts/pack/generate_plugin_metadata.py",
            scripts,
        )
        workflow = project / relative
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(
            "ref: ${{ github.event.inputs.data_ref || '" + pin + "' }}\n",
        )
        plugin = project / "plugins" / kind / plugin_id
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": plugin_id,
                    "version": "1.0.0",
                    "entry": {"frontend": "frontend/dist/index.js"},
                },
            ),
        )

    def build(root, path):
        # Stand in only for the external npm build; comparison stays real.
        entry = path / "frontend/dist/index.js"
        entry.parent.mkdir(parents=True)
        entry.write_text((root / relative).read_text())

    monkeypatch.setattr(guard, "_build_frontend", build)
    with pytest.raises(ValueError, match=plugin_id + ".*version increase"):
        guard.check_pr(tmp_path / "base", tmp_path / "candidate", build=True)


@pytest.mark.parametrize("bumped", [(), ("codex",), ("codex", "qoder")])
def test_pr_version_guard_rebuilds_shared_harness_frontends(
    tmp_path,
    monkeypatch,
    bumped,
):
    import check_plugin_versions as guard

    for side, color in (("base", "red"), ("candidate", "blue")):
        root = tmp_path / side
        scripts = root / "scripts/pack"
        scripts.mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "scripts/pack/generate_plugin_metadata.py",
            scripts,
        )
        shared = root / "plugins/harness/_shared/ui/Settings.css"
        shared.parent.mkdir(parents=True)
        shared.write_text(f".harness-settings {{ color: {color}; }}")
        for name in ("codex", "qoder", "unrelated"):
            kind = "apps" if name == "unrelated" else "harness"
            plugin = root / "plugins" / kind / ("fixture-" + name)
            entry = plugin / "frontend/dist/index.js"
            entry.parent.mkdir(parents=True)
            entry.write_text("previous build")
            (plugin / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": name,
                        "version": "1.0.1"
                        if side == "candidate" and name in bumped
                        else "1.0.0",
                        "entry": {"frontend": "frontend/dist/index.js"},
                    },
                ),
            )

    rebuilt = set()

    def build(root, path):
        # Replace only npm; input discovery and publication comparison stay real.
        assert path.parent.name == "harness", "Unrelated app rebuilt"
        rebuilt.add(path.name.removeprefix("fixture-"))
        (path / "frontend/dist/index.js").write_bytes(
            (root / "plugins/harness/_shared/ui/Settings.css").read_bytes(),
        )

    monkeypatch.setattr(guard, "_build_frontend", build)
    if len(bumped) == 2:
        guard.check_pr(tmp_path / "base", tmp_path / "candidate", build=True)
    else:
        with pytest.raises(ValueError, match="version increase") as error:
            guard.check_pr(
                tmp_path / "base",
                tmp_path / "candidate",
                build=True,
            )
        for name in {"codex", "qoder"} - set(bumped):
            assert name + ": published content changed" in str(error.value)
    assert rebuilt == {"codex", "qoder"}


@pytest.mark.parametrize(
    "version,catalog_present",
    [("2.2.2", False), ("2.3.0", False), ("2.2.2", True)],
)
def test_immutable_release_distinguishes_legacy_hosts_from_broken_bundles(
    tmp_path,
    version,
    catalog_present,
):
    from check_plugin_versions import check_release

    with zipfile.ZipFile(
        tmp_path / "qwenpaw-2.2.2-py3-none-any.whl",
        "w",
    ) as wheel:
        wheel.writestr(
            "qwenpaw-2.2.2.dist-info/METADATA",
            f"Name: qwenpaw\nVersion: {version}\n",
        )
        if catalog_present:
            wheel.writestr("qwenpaw/plugins/official_channel_catalog.py", "")

    def no_remote():
        raise AssertionError("Legacy host must not contact the identity store")

    if catalog_present or version == "2.3.0":
        with pytest.raises(ValueError, match="channel index"):
            check_release(tmp_path, no_remote, dry_run=True)
    else:
        check_release(tmp_path, no_remote, dry_run=True)
