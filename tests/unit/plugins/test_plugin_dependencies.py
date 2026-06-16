# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest


def _write_plugin(root: Path, plugin_id: str = "needs-deps") -> Path:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "name": "Needs Deps",
                "version": "1.0.0",
                "entry": {"backend": "plugin.py"},
            },
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        textwrap.dedent(
            """
            class Plugin:
                def register(self, api):
                    pass

            plugin = Plugin()
            """,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "requirements.txt").write_text(
        "example-wheel-only>=1.0\n",
        encoding="utf-8",
    )
    return plugin_dir


@pytest.mark.asyncio
async def test_tauri_startup_skips_plugin_with_unprepared_dependencies(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    plugin_dir = _write_plugin(tmp_path)
    monkeypatch.setenv("QWENPAW_TAURI_BACKEND", "1")

    loader = PluginLoader([tmp_path])
    loaded = await loader.load_all_plugins()

    assert loaded == {}
    skipped = loader.get_skipped_plugin_states()
    assert skipped[plugin_dir.name].status == "needs_repair"
    assert skipped[plugin_dir.name].reason == (
        "dependencies_not_prepared_for_current_desktop"
    )


def test_repair_dependencies_writes_manifest_and_activates_path(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import dependencies

    plugin_dir = _write_plugin(tmp_path)
    deps_root = tmp_path / "deps"
    monkeypatch.setattr(dependencies, "plugin_deps_root", lambda: deps_root)
    monkeypatch.setattr(
        dependencies,
        "find_dependency_installer",
        lambda: dependencies.DependencyInstaller(
            kind="python",
            command_prefix=["python", "-m", "pip"],
            python="python",
        ),
    )

    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        timeout: int,
        plugin_id: str,
    ):
        assert timeout == 300
        assert plugin_id == plugin_dir.name
        calls.append(cmd)
        target = Path(cmd[cmd.index("--target") + 1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "dummy_dep.py").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    state = dependencies.install_dependencies(
        plugin_dir,
        plugin_dir.name,
        fake_run,
    )

    assert state.ready
    assert state.install_json and state.install_json.exists()
    assert state.site_packages and str(state.site_packages) in __import__(
        "sys",
    ).path
    manifest = json.loads(state.install_json.read_text(encoding="utf-8"))
    assert manifest["plugin_id"] == plugin_dir.name
    assert manifest["runtime_id"] == dependencies.current_runtime_id()
    assert calls and "--only-binary=:all:" in calls[0]


def test_dependency_state_marks_hash_mismatch_as_needs_repair(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import dependencies

    plugin_dir = _write_plugin(tmp_path)
    deps_root = tmp_path / "deps"
    monkeypatch.setattr(dependencies, "plugin_deps_root", lambda: deps_root)

    def fake_run(
        cmd: list[str],
        *,
        timeout: int,
        plugin_id: str,
    ):
        assert timeout == 300
        assert plugin_id == plugin_dir.name
        target = Path(cmd[cmd.index("--target") + 1])
        target.mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        dependencies,
        "find_dependency_installer",
        lambda: dependencies.DependencyInstaller(
            kind="python",
            command_prefix=["python", "-m", "pip"],
            python="python",
        ),
    )
    dependencies.install_dependencies(plugin_dir, plugin_dir.name, fake_run)

    (plugin_dir / "requirements.txt").write_text(
        "example-wheel-only>=2.0\n",
        encoding="utf-8",
    )
    state = dependencies.dependency_state(plugin_dir, plugin_dir.name)

    assert state.status == "needs_repair"
    assert state.reason == "dependencies_not_prepared_for_current_desktop"
