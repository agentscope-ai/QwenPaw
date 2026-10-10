# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Clean unload, provision inventory, and boot dependency policy."""

from __future__ import annotations

import json
import sys
from importlib.machinery import SourceFileLoader
from importlib.metadata import PackageNotFoundError
from types import ModuleType
from pathlib import Path
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.dependency_gate import (
    DependencyGate,
    hits_imported_host_package,
)
from qwenpaw.plugins.lifecycle import (
    LifecycleDelegate,
    PluginInstance,
    PluginState,
    UnloadMode,
)
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import (
    load_inventory,
    provision_files,
    record_escape_provision,
    recover_migrating_inventory,
    record_tool_factory,
    save_inventory,
    teardown_created_locations,
)
from qwenpaw.plugins.safe_fs import safe_remove


@pytest.fixture()
def plugin_dir(tmp_path: Path) -> Path:
    root = tmp_path / "ok-plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "ok-plugin",
                "version": "1.0.0",
                "name": "OK",
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "class _P:\n"
        "    def register(self, api):\n"
        "        api.register_startup_hook('h', lambda: None)\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    return root


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    requirements: str | None = None,
    register_body: str = "pass",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "name": plugin_id,
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "class _P:\n"
        f"    def register(self, api):\n"
        f"        {register_body}\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    if requirements is not None:
        (root / "requirements.txt").write_text(
            requirements,
            encoding="utf-8",
        )
    return root


class TestDependencyGate:
    def test_satisfied_is_zero_network(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("packaging>=24.0\n", encoding="utf-8")
        decision = DependencyGate().evaluate(
            req,
            allow_install=True,
            plugin_id="p",
        )
        assert decision.already_satisfied
        assert not decision.allow_install

    def test_boot_missing_does_not_install(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text(
            "definitely-not-a-real-pkg-xyz==9.9.9\n",
            encoding="utf-8",
        )
        decision = DependencyGate().evaluate(
            req,
            allow_install=False,
            plugin_id="p",
        )
        assert decision.missing
        assert not decision.allow_install
        assert not decision.require_restart

    def test_unsatisfied_httpx_requires_restart(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("httpx==0.0.1\n", encoding="utf-8")
        decision = DependencyGate().evaluate(
            req,
            allow_install=True,
            plugin_id="p",
        )
        assert decision.require_restart
        assert not decision.allow_install
        assert hits_imported_host_package(Requirement("httpx==0.0.1"))

    @pytest.mark.parametrize(
        "package,frozen",
        [
            ("openai", False),
            ("agentscope", False),
            ("reme-ai", False),
            ("apscheduler", False),
            ("openai", True),
        ],
    )
    def test_conflicting_core_dependency_is_blocked(
        self,
        tmp_path: Path,
        package: str,
        frozen: bool,
    ):
        requirements = tmp_path / "requirements.txt"
        declaration = f"{package}<0.1"
        requirements.write_text(declaration + "\n", encoding="utf-8")
        with (
            patch(
                "qwenpaw.plugins.dependency_gate._dist_version",
                return_value="2.0.0",
            ),
            patch(
                "qwenpaw.plugins.dependency_gate._is_frozen",
                return_value=frozen,
            ),
        ):
            decision = DependencyGate().evaluate(
                requirements,
                allow_install=True,
                plugin_id="test-plugin",
            )
        assert not decision.allow_install
        assert not decision.already_satisfied
        assert decision.host_conflicts == [declaration]
        assert decision.require_restart

    def test_satisfied_core_dependency_needs_no_install(
        self,
        tmp_path: Path,
    ):
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("openai>=1\n", encoding="utf-8")
        with patch(
            "qwenpaw.plugins.dependency_gate._dist_version",
            return_value="2.0.0",
        ):
            decision = DependencyGate().evaluate(
                requirements,
                allow_install=True,
                plugin_id="test-plugin",
            )
        assert decision.already_satisfied
        assert not decision.allow_install
        assert not decision.host_conflicts
        assert not decision.require_restart

    def test_reme_distribution_detects_loaded_module_without_metadata(self):
        with (
            patch.dict(sys.modules, {"reme": ModuleType("reme")}),
            patch(
                "qwenpaw.plugins.dependency_gate._dist_version",
                side_effect=PackageNotFoundError("reme-ai"),
            ),
            patch(
                "qwenpaw.plugins.dependency_gate._is_frozen",
                return_value=False,
            ),
        ):
            assert hits_imported_host_package(Requirement("reme-ai<0.1"))


class TestProvisionFiles:
    def test_create_keep_migrate_and_recover(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "qwenpaw.constant.WORKING_DIR",
            tmp_path / "work",
        )
        src = tmp_path / "src"
        src.mkdir()
        (src / "note.md").write_text("v1\n", encoding="utf-8")
        dest = tmp_path / "dest"
        assert provision_files("pid", src, dest, "1.0.0") == "create"
        assert (dest / "note.md").read_text(encoding="utf-8") == "v1\n"

        (src / "note.md").write_text("v2\n", encoding="utf-8")
        assert provision_files("pid", src, dest, "1.0.0") == "keep"
        assert (dest / "note.md").read_text(encoding="utf-8") == "v1\n"

        (dest / "note.md").write_text("user\n", encoding="utf-8")
        assert provision_files("pid", src, dest, "2.0.0") == "migrate"
        assert (dest / "note.md").read_text(encoding="utf-8") == "user\n"
        assert (dest / "note.md.new").read_text(encoding="utf-8") == "v2\n"

        data = load_inventory("pid")
        loc = data["locations"][str(dest)]
        loc["migrating"] = {
            "backup_path": str(tmp_path / "missing.bak"),
            "target_version": "3.0.0",
            "prev_version": "2.0.0",
            "prev_factory_hashes": {},
        }
        save_inventory("pid", data)
        assert recover_migrating_inventory("pid") == ["pid"]
        restored = load_inventory("pid")["locations"][str(dest)]
        assert restored["migrating"] is None

    def test_uninstall_clears_created_and_inventory(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "qwenpaw.constant.WORKING_DIR",
            tmp_path / "work",
        )
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("x\n", encoding="utf-8")
        dest = tmp_path / "created"
        provision_files("gone", src, dest, "1.0.0")
        record_tool_factory("gone", "t", {"description": "d"})
        teardown_created_locations("gone")
        assert not dest.exists()
        inventory = tmp_path / "work" / "plugin_provisions" / "gone.json"
        assert not inventory.exists()


class TestPluginInstanceLedger:
    def test_unloading_rejects_new_register(self):
        inst = PluginInstance("p")
        inst.state = PluginState.UNLOADING
        with pytest.raises(RuntimeError, match="unloading"):
            inst.record_runtime("x")

    @pytest.mark.asyncio
    async def test_shutdown_skips_install_and_noncritical(self):
        inst = PluginInstance("p")
        ran: list[str] = []
        inst.record_runtime(
            "conn",
            lambda: ran.append("conn"),
            shutdown_critical=True,
            kind="custody",
        )
        inst.record_runtime(
            "patch",
            lambda: ran.append("patch"),
            shutdown_critical=False,
            kind="effect",
        )
        inst.record_install("disk", lambda: ran.append("disk"))

        report = await inst.dispose(UnloadMode.SHUTDOWN)
        assert report.clean
        assert ran == ["conn"]


@pytest.mark.asyncio
async def test_boot_missing_deps_is_failed_without_install(
    tmp_path: Path,
    fresh_registry,
):
    root = _write_plugin(
        tmp_path / "missing-dep",
        "missing-dep",
        requirements="definitely-not-a-real-pkg-xyz==9.9.9\n",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    with patch.object(
        loader,
        "_install_requirements_locked",
        side_effect=AssertionError("must not install on boot"),
    ):
        record = await loader.load_plugin(
            PluginManifest.from_dict(
                json.loads((root / "plugin.json").read_text(encoding="utf-8")),
            ),
            root,
            allow_install=False,
        )
    assert record.status == "failed"
    assert record.enabled is False
    assert any("missing-dep" in d for d in record.diagnostics)


@pytest.mark.asyncio
async def test_user_install_rejects_httpx_upgrade(
    tmp_path: Path,
    fresh_registry,
):
    root = _write_plugin(
        tmp_path / "httpx-up",
        "httpx-up",
        requirements="httpx==0.0.1\n",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    with patch.object(
        loader,
        "_install_requirements_locked",
        side_effect=AssertionError("site must not be written"),
    ):
        with pytest.raises(RuntimeError, match="Restart"):
            await loader.load_plugin(
                PluginManifest.from_dict(
                    json.loads(
                        (root / "plugin.json").read_text(encoding="utf-8"),
                    ),
                ),
                root,
                allow_install=True,
            )


@pytest.mark.asyncio
async def test_unload_mode_leaves_agent_json_and_removes_manifest(
    tmp_path: Path,
    fresh_registry,
    plugin_dir: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    agent_json = tmp_path / "agent.json"
    agent_json.write_text('{"keep": true}\n', encoding="utf-8")
    plugins_cfg = tmp_path / "config.plugins"
    plugins_cfg.write_text('{"ok-plugin": {}}\n', encoding="utf-8")
    before_agent = agent_json.read_bytes()
    before_cfg = plugins_cfg.read_bytes()

    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, plugin_dir)
    assert "ok-plugin" in loader.registry.get_all_plugin_manifests()

    report = await loader.unload_plugin(
        "ok-plugin",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert report.mode is UnloadMode.UNLOAD
    assert not report.leftovers
    assert "ok-plugin" not in loader.registry.get_all_plugin_manifests()
    assert agent_json.read_bytes() == before_agent
    assert plugins_cfg.read_bytes() == before_cfg


@pytest.mark.asyncio
async def test_uninstall_failed_plugin_clears_provisions(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    plugin_id = "failed-one"
    root = _write_plugin(
        tmp_path / plugin_id,
        plugin_id,
        requirements="definitely-not-a-real-pkg-xyz==9.9.9\n",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    record = await loader.load_plugin(
        PluginManifest.from_dict(
            json.loads((root / "plugin.json").read_text(encoding="utf-8")),
        ),
        root,
        allow_install=False,
    )
    assert record.status == "failed"
    record_tool_factory(plugin_id, "t", {"description": "d"})
    inventory = tmp_path / "work" / "plugin_provisions" / f"{plugin_id}.json"
    assert inventory.is_file()

    await loader.unload_plugin(
        plugin_id,
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert not inventory.exists()
    assert plugin_id not in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_uninstall_rechecks_leftover_created_dests(
    tmp_path: Path,
    fresh_registry,
    plugin_dir: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "kept.txt").write_text("x\n", encoding="utf-8")
    dest = tmp_path / "created-dir"
    provision_files("ok-plugin", src, dest, "1.0.0")
    assert dest.exists()

    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, plugin_dir)

    monkeypatch.setattr(
        "qwenpaw.plugins.provision.shutil.rmtree",
        lambda *args, **kwargs: None,
    )
    report = await loader.unload_plugin(
        "ok-plugin",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert dest.exists()
    assert any("inventory leftover" in err for err in report.errors)
    assert report.clean is False


@pytest.mark.asyncio
async def test_uninstall_without_loaded_instance_clears_provisions(
    tmp_path: Path,
    fresh_registry,
    plugin_dir: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x\n", encoding="utf-8")
    dest = tmp_path / "created"
    provision_files("ok-plugin", src, dest, "1.0.0")

    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, plugin_dir)
    await loader.unload_plugin(
        "ok-plugin",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert loader.get_loaded_plugin("ok-plugin") is None
    assert dest.exists()

    report = await loader.unload_plugin(
        "ok-plugin",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert report.mode is UnloadMode.UNINSTALL
    assert not dest.exists()
    inventory = tmp_path / "work" / "plugin_provisions" / "ok-plugin.json"
    assert not inventory.exists()
    assert not plugin_dir.exists()


@pytest.mark.asyncio
async def test_cloudpaw_uninstall_replays_relative_import_cleanup(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(sys, "path", list(sys.path))
    source = Path(__file__).parents[3] / "plugins" / "bundle" / "cloudpaw"
    root = tmp_path / "plugins" / "cloudpaw"
    root.mkdir(parents=True)
    for name in ("plugin.json", "agents_setup.py", "constants.py"):
        (root / name).write_bytes((source / name).read_bytes())
    calls = []
    original_exec = SourceFileLoader.exec_module

    def exec_module(loader, module):
        original_exec(loader, module)
        if Path(module.__file__) == root / "agents_setup.py":
            # Execute real relative imports, but replace destructive cleanup.
            module.uninstall_agents = lambda: calls.append(
                module.BUILTIN_ORCHESTRATION_AGENT_ID,
            )

    monkeypatch.setattr(SourceFileLoader, "exec_module", exec_module)
    finders = tuple(sys.meta_path)
    import_paths = list(sys.path)
    record_escape_provision("cloudpaw", "agents", kind="cloudpaw_agents")
    loader = PluginLoader(plugin_dirs=[root.parent])
    loader.registry = fresh_registry
    report = await loader.unload_plugin("cloudpaw", mode=UnloadMode.UNINSTALL)

    assert report.clean and report.quiescent
    assert not report.errors
    assert calls == ["cloud-orchestrator"]
    assert not load_inventory("cloudpaw").get("provisions")
    assert not root.exists()
    assert tuple(sys.meta_path) == finders
    assert sys.path == import_paths
    assert not any(
        str(getattr(module, "__file__", "")).startswith(str(root))
        for module in sys.modules.values()
    )


@pytest.mark.asyncio
async def test_uninstall_never_enabled_preserves_declared_user_directory(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    dest = tmp_path / "declared-dest"
    dest.mkdir()
    user_file = dest / "user.txt"
    user_file.write_text("user content\n", encoding="utf-8")
    root = tmp_path / "disk-only"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "disk-only",
                "version": "1.0.0",
                "name": "disk-only",
                "entry": {"backend": "main.py"},
                "meta": {"provisions": [str(dest)]},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "class _P:\n"
        "    def register(self, api):\n"
        "        pass\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    report = await loader.lifecycle.unload(
        "disk-only",
        UnloadMode.UNINSTALL,
        delete_files=True,
    )
    assert not report.clean
    assert report.quiescent and not report.needs_restart
    assert any("candidate:" in err for err in report.errors)
    assert user_file.read_text(encoding="utf-8") == "user content\n"
    assert not root.exists()


@pytest.mark.asyncio
async def test_uninstall_unlinks_replaced_owned_directory(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    source = tmp_path / "factory"
    source.mkdir()
    (source / "SKILL.md").write_text("plugin", encoding="utf-8")
    dest = tmp_path / "plugin-data"
    plugin_id = "symlink-ownership"
    root = _write_plugin(
        tmp_path / plugin_id,
        plugin_id,
        register_body=(
            f"assert api.provision_files({str(source)!r}, {str(dest)!r}, '1') "
            "== 'create'"
        ),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((root / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, root)
    assert record.status == "active"
    assert load_inventory(plugin_id)["locations"][str(dest)]["owned"]
    moved = tmp_path / "moved-plugin-data"
    dest.rename(moved)
    user_dir = tmp_path / "user-data"
    user_dir.mkdir()
    private = user_dir / "private.txt"
    private.write_text("private", encoding="utf-8")
    dest.symlink_to(user_dir, target_is_directory=True)

    report = await loader.unload_plugin(plugin_id, mode=UnloadMode.UNINSTALL)

    assert report.clean and report.quiescent
    assert not report.errors
    assert private.read_text(encoding="utf-8") == "private"
    assert (moved / "SKILL.md").read_text(encoding="utf-8") == "plugin"
    assert not dest.is_symlink()
    assert not load_inventory(plugin_id)["locations"]


def test_safe_remove_unlinks_dangling_symlink(tmp_path: Path):
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "missing", target_is_directory=True)
    safe_remove(link)
    assert not link.is_symlink()


@pytest.mark.asyncio
async def test_startup_rollback_preserves_user_directory(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    source = tmp_path / "factory"
    source.mkdir()
    (source / "factory.txt").write_text("factory\n", encoding="utf-8")
    user_dir = tmp_path / "user-data"
    user_dir.mkdir()
    user_file = user_dir / "important.txt"
    user_file.write_bytes(b"user data\x00\n")
    owned_dir = tmp_path / "plugin-data"
    plugin_id = "rollback-ownership"
    assert not load_inventory(plugin_id)["locations"]
    root = _write_plugin(
        tmp_path / plugin_id,
        plugin_id,
        register_body=(
            "def _boom():\n"
            f"            src = {str(source)!r}\n"
            f"            user = {str(user_dir)!r}\n"
            f"            owned = {str(owned_dir)!r}\n"
            "            assert api.provision_files(src, user, '1') "
            "== 'keep'\n"
            "            assert api.provision_files(src, owned, '1') "
            "== 'create'\n"
            "            raise RuntimeError('startup-rollback-boom')\n"
            "        api.register_startup_hook('boom', _boom)"
        ),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((root / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, root)
    await loader.run_all_startup_hooks()
    record = loader.get_loaded_plugin(plugin_id)
    assert record is not None
    assert record.status == "failed"
    assert any("startup-rollback-boom" in d for d in record.diagnostics)
    assert user_dir.is_dir()
    assert user_file.read_bytes() == b"user data\x00\n"
    assert sorted(path.name for path in user_dir.iterdir()) == [
        "important.txt",
    ]
    assert not owned_dir.exists()
    assert not load_inventory(plugin_id)["locations"]


@pytest.mark.asyncio
async def test_startup_failure_marks_failed_and_continues(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    boom = _write_plugin(
        tmp_path / "boom-p",
        "boom-p",
        register_body=(
            "def _boom():\n"
            "            raise RuntimeError('startup-boom')\n"
            "        api.register_startup_hook('boom', _boom)"
        ),
    )
    _write_plugin(
        tmp_path / "ok-p",
        "ok-p",
        register_body="api.register_startup_hook('ok', lambda: None)",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    boom_manifest = PluginManifest.from_dict(
        json.loads((boom / "plugin.json").read_text(encoding="utf-8")),
    )
    ok_root = tmp_path / "ok-p"
    ok_manifest = PluginManifest.from_dict(
        json.loads((ok_root / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(boom_manifest, boom)
    await loader.load_plugin(ok_manifest, ok_root)
    await loader.run_all_startup_hooks()

    boom_record = loader.get_loaded_plugin("boom-p")
    ok_record = loader.get_loaded_plugin("ok-p")
    assert boom_record is not None
    assert boom_record.status == "failed"
    assert any("startup-boom" in item for item in boom_record.diagnostics)
    assert ok_record is not None
    assert ok_record.status == "active"
    leftover_hooks = [
        hook.plugin_id for hook in loader.registry.get_startup_hooks()
    ]
    assert "boom-p" not in leftover_hooks
    assert "ok-p" in leftover_hooks


@pytest.mark.asyncio
async def test_delegate_default_owns_commit():
    delegate = LifecycleDelegate()
    assert delegate.owns_commit("any") is True
    assert delegate.owns_dependency_env("any") is True
    receipt = await delegate.notify_unload("any", UnloadMode.UNLOAD)
    assert receipt.ok


def test_projection_failed_records_diagnostic(fresh_registry):
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.workspace_projector import ProjectionError

    api = PluginApi("p", {}, {"id": "p"})
    api.set_registry(fresh_registry)
    inst = PluginInstance("p")
    api.bind_instance(inst)
    with pytest.raises(ProjectionError, match="slash_command"):
        api._projection_failed("slash_command", ValueError("taken"))
    assert inst.diagnostics
    assert "slash_command" in inst.diagnostics[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("record_user_location", [True, False])
async def test_uninstall_with_inventory_preserves_declared_user_directory(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    record_user_location: bool,
):
    """An empty owned-path list must not trigger manifest-based deletion."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    root = _write_plugin(tmp_path / "disk-user", "disk-user")
    dest = tmp_path / "user-directory"
    dest.mkdir()
    original = b"user content\n\x00\xff"
    user_file = dest / "user.dat"
    user_file.write_bytes(original)
    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["meta"] = {"provisions": [{"dest": str(dest)}]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    if record_user_location:
        factory = root / "factory"
        factory.mkdir()
        (factory / "default.txt").write_text("default", encoding="utf-8")
        provision_files("disk-user", factory, dest, "1.0.0")
        assert (
            load_inventory("disk-user")["locations"][str(dest)]["owned"]
            is False
        )
    else:
        save_inventory("disk-user", {"locations": {}, "provisions": []})
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    monkeypatch.setattr(loader, "_drop_uninstalled_settings", AsyncMock())
    report = await loader.unload_plugin("disk-user", mode=UnloadMode.UNINSTALL)
    assert dest.is_dir()
    assert user_file.read_bytes() == original
    assert report.clean
    assert not any("candidate:" in error for error in report.errors)
    assert not root.exists()
