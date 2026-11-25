# -*- coding: utf-8 -*-
"""Harness discovery and migration through private host integration points."""

import json

import pytest

from qwenpaw.plugins.testing import PluginTestHost
from .test_sdk_harness import package


async def test_boot_discovery_preserves_failed_harness_across_load_phases(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        plugins = host.root / "plugins"
        plugins.mkdir(exist_ok=True)
        root = package(plugins)
        marker = tmp_path / "entry-executed"
        (root / "main.py").write_text(
            "from pathlib import Path\n"
            f"marker = Path({str(marker)!r})\n"
            "marker.write_text(marker.read_text() + 'x' "
            "if marker.exists() else 'x')\n"
            "raise RuntimeError('entry failed')\n",
            encoding="utf-8",
        )

        await host._loader.load_all_plugins(types=["channel"])
        assert host.list_harnesses()[0]["status"] == "disabled"
        assert not marker.exists()

        await host._loader.load_all_plugins()
        record = host._loader.get_loaded_plugin("author-owner")
        assert record.status == "failed"
        for types in (["channel"], None):
            await host._loader.load_all_plugins(types=types)
            assert host.list_harnesses()[0]["status"] == "failed"
            assert host._loader.get_loaded_plugin("author-owner") is record
        assert marker.read_text() == "x"


@pytest.mark.parametrize("missing_dependency", [False, True])
async def test_offline_migration_prepares_saved_harness_without_execution(
    tmp_path,
    monkeypatch,
    missing_dependency,
):
    from qwenpaw.plugins.harness_migration import migrate_legacy_harnesses

    async with PluginTestHost(tmp_path / "host") as host:
        await host._workspace("default")
        workspace = await host._workspace("legacy")
        agent_path = workspace.workspace_dir / "agent.json"
        agent = json.loads(agent_path.read_text(encoding="utf-8"))
        agent.update(backend="codex", backend_settings={"model": "saved"})
        agent_path.write_text(json.dumps(agent), encoding="utf-8")
        config_path = host.root / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.setdefault("plugins", {})["qwenpaw-harness-codex"] = {
            "enabled": False,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        before = config_path.read_bytes(), agent_path.read_bytes()
        prepared = tmp_path / "prepared"
        prepared.mkdir()
        root = package(prepared, "qwenpaw-harness-codex")
        (root / "main.py").write_text(
            "raise AssertionError('offline migration executed entry')\n",
            encoding="utf-8",
        )
        if missing_dependency:
            (root / "requirements.txt").write_text(
                "qwenpaw-offline-migration-absent==1\n",
                encoding="utf-8",
            )

        def forbid_process(*_args, **_kwargs):
            pytest.fail("Offline migration launched a dependency installer")

        monkeypatch.setattr("subprocess.Popen", forbid_process)
        preview = (await migrate_legacy_harnesses(prepared))["plugins"][0]
        assert preview["agents"] == ["legacy"]
        assert preview["enabled"] is False
        assert preview["missing_dependencies"] == (
            ["qwenpaw-offline-migration-absent==1"]
            if missing_dependency
            else []
        )
        assert preview["action"] == (
            "prepare-dependencies" if missing_dependency else "install"
        )
        assert preview["result"] == "not-applied"
        target = host.root / "plugins" / "qwenpaw-harness-codex"
        assert not target.exists()

        applied = (await migrate_legacy_harnesses(prepared, apply=True))[
            "plugins"
        ][0]
        assert applied["result"] == (
            "not-prepared" if missing_dependency else "installed"
        )
        assert target.is_dir() == (not missing_dependency)
        if not missing_dependency:
            for name in ("main.py", "plugin.json"):
                assert (target / name).read_bytes() == (
                    root / name
                ).read_bytes()
        assert (config_path.read_bytes(), agent_path.read_bytes()) == before
        assert host._loader.get_loaded_plugin("qwenpaw-harness-codex") is None
