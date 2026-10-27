# -*- coding: utf-8 -*-
"""Install targets must always remain child directories of the plugin root."""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from pathlib import Path

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.updates import (
    marker_path,
    recover_interrupted_updates,
    write_updating_marker,
)

from .timing import WAIT_TIMEOUT


def _snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _residual_install(
    tmp_path,
    registry,
    monkeypatch,
    manifest_kind="missing",
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    target, source = tmp_path / "plugins/demo", tmp_path / "source"
    (target / "data").mkdir(parents=True)
    (target / "data/private.txt").write_bytes(b"residual user data\x00")
    if manifest_kind != "missing":
        (target / "plugin.json").write_text(
            {
                "invalid": "{broken manifest",
                "required": "{}",
                "shape": "[]",
            }[manifest_kind],
        )
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "version": "2.0.0",
                "entry": {"backend": "main.py"},
            },
        ),
    )
    (source / "main.py").write_text(
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        async def start():\n"
        "            if api.config.get('fail'):\n"
        "                raise RuntimeError('incoming startup failed')\n"
        "        api.register_startup_hook('start', start)\n"
        "plugin = Plugin()\n",
    )
    loader = PluginLoader([target.parent])
    loader.registry = registry
    return loader, source, target


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manifest_kind",
    ["missing", "invalid", "required", "shape"],
)
async def test_force_install_preserves_residual_directory_backup(
    tmp_path,
    fresh_registry,
    monkeypatch,
    manifest_kind,
):
    loader, source, target = _residual_install(
        tmp_path,
        fresh_registry,
        monkeypatch,
        manifest_kind,
    )
    original = _snapshot(target)
    with pytest.raises(ValueError, match="already exists"):
        await loader.load_plugin_from_path(source)
    assert _snapshot(target) == original
    try:
        record = await loader.load_plugin_from_path(source, force=True)
        assert record.status == "active" and record.source_path == target
        backups = [
            path
            for path in target.parent.iterdir()
            if path != target and (path / "data/private.txt").is_file()
        ]
        assert len(backups) == 1
        backup = backups[0]
        assert _snapshot(backup) == original
        assert str(backup) in "\n".join(record.diagnostics)
        recovery = recover_interrupted_updates()
        assert "demo" not in recovery.blocked
        assert _snapshot(backup) == original
        assert (
            json.loads((target / "plugin.json").read_text())["version"]
            == "2.0.0"
        )
    finally:
        await loader.lifecycle.unload("demo", UnloadMode.UNLOAD)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["startup", "cancel"])
async def test_force_install_failure_restores_residual_without_loading_it(
    tmp_path,
    fresh_registry,
    monkeypatch,
    failure,
):
    loader, source, target = _residual_install(
        tmp_path,
        fresh_registry,
        monkeypatch,
    )
    original = _snapshot(target)
    if failure == "startup":
        with pytest.raises(
            RuntimeError,
            match="incoming startup failed",
        ) as raised:
            await loader.load_plugin_from_path(
                source,
                force=True,
                config={"fail": True},
            )
        assert "previous service was restored" not in str(raised.value)
    else:
        loop = asyncio.get_running_loop()
        cancelled = threading.Event()
        move = shutil.move
        operation = None

        def cancel():
            operation.cancel()
            cancelled.set()

        def move_then_cancel(src, dest, *args, **kwargs):
            result = move(src, dest, *args, **kwargs)
            if Path(src).name.endswith(".staging") and Path(dest) == target:
                loop.call_soon_threadsafe(cancel)
                assert cancelled.wait(WAIT_TIMEOUT * 2)
            return result

        monkeypatch.setattr(shutil, "move", move_then_cancel)
        operation = asyncio.create_task(
            loader.load_plugin_from_path(source, force=True),
        )
        with pytest.raises(asyncio.CancelledError):
            await operation
    assert _snapshot(target) == original
    record = loader.get_loaded_plugin("demo")
    assert record is None or record.status == "failed"
    assert not marker_path("demo").exists()
    if failure == "startup":
        try:
            record = await loader.load_plugin_from_path(
                source,
                force=True,
                config={},
            )
            assert record.status == "active"
        finally:
            await loader.lifecycle.unload("demo", UnloadMode.UNLOAD)


@pytest.mark.parametrize("state", ["staging", "swapped", "committed"])
def test_residual_swap_boot_recovery_preserves_the_right_copy(
    tmp_path,
    fresh_registry,
    monkeypatch,
    state,
):
    _, source, target = _residual_install(
        tmp_path,
        fresh_registry,
        monkeypatch,
    )
    original = _snapshot(target)
    identity = target.stat()
    backup, staging = target.with_name(".demo.bak"), target.with_name(
        "demo.staging",
    )
    shutil.copytree(source, staging)
    if state != "staging":
        target.rename(backup)
        shutil.copytree(source, target)
    write_updating_marker(
        "demo",
        backup_path=backup,
        target_path=target,
        staging_path=staging,
        status="committed" if state == "committed" else "prepared",
        phase="staging" if state == "staging" else "swapping",
        preserve_backup=True,
        old_identity=(identity.st_dev, identity.st_ino),
    )
    recovery = recover_interrupted_updates()
    assert not recovery.failures
    assert not marker_path("demo").exists() and not staging.exists()
    if state == "committed":
        assert _snapshot(target) == _snapshot(source)
        assert _snapshot(backup) == original
    else:
        assert _snapshot(target) == original
        assert not backup.exists()


@pytest.mark.asyncio
async def test_dot_plugin_id_cannot_replace_the_plugin_root(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "plugins"
    source = tmp_path / "source"
    install_root.mkdir()
    source.mkdir()
    marker = install_root / "keep.txt"
    marker.write_text("must survive", encoding="utf-8")
    loader = PluginLoader([install_root])

    with pytest.raises(ValueError, match="safe child"):
        # pylint: disable-next=protected-access
        await loader._load_plugin_from_path_unlocked(
            source,
            PluginManifest(id=".", version="0.1.0"),
            install_dir=install_root,
        )

    assert marker.read_text(encoding="utf-8") == "must survive"


@pytest.mark.asyncio
async def test_existing_plugin_target_is_not_replaced_without_force(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "plugins"
    source = tmp_path / "source"
    target = install_root / "demo"
    install_root.mkdir()
    source.mkdir()
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("must survive", encoding="utf-8")
    loader = PluginLoader([install_root])

    with pytest.raises(ValueError, match="already exists"):
        # pylint: disable-next=protected-access
        await loader._load_plugin_from_path_unlocked(
            source,
            PluginManifest(id="demo", version="0.1.0"),
            install_dir=install_root,
        )

    assert marker.read_text(encoding="utf-8") == "must survive"


@pytest.mark.asyncio
async def test_pawport_plugin_failure_cleans_its_prepared_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_root = tmp_path / "plugins"
    source = tmp_path / "source"
    install_root.mkdir()
    source.mkdir()
    (source / "plugin.json").write_text(
        '{"id":"demo","version":"0.1.0","entry":{}}',
        encoding="utf-8",
    )
    (source / "requirements.txt").write_text(
        "demo-dependency",
        encoding="utf-8",
    )
    loader = PluginLoader([install_root])
    monkeypatch.setattr(
        loader,
        "_install_requirements_locked",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("install failed")),
    )

    with pytest.raises(RuntimeError, match="install failed"):
        await loader.load_plugin_from_path(
            source,
            install_dir=install_root,
            pawport_owner={
                "owner": "pawport",
                "provider": "codex",
                "source_id": "demo@local",
            },
            recover_incomplete=True,
        )

    assert not (install_root / "demo").exists()
