# -*- coding: utf-8 -*-
"""Install targets must always remain child directories of the plugin root."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.loader import PluginLoader


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
