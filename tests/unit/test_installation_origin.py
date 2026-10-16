# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Installation provenance survives restarts without name-based guessing."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.installation_origin import (
    origin_from_platform_url,
    read_plugin_origin,
    validated_origin,
    write_plugin_origin,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://platform.agentscope.io/plugins/owner/demo",
        "https://platform.agentscope.io.evil.test/plugins/owner/demo",
        "https://platform.agentscope.io@evil.test/plugins/owner/demo",
        "https://platform.agentscope.io/plugins/owner/demo?redirect=evil",
        "https://platform.agentscope.io/plugins/owner/%2e%2e",
        "https://platform.agentscope.io/plugins/owner%2fother/demo",
        "https://platform.agentscope.io/plugins/owner/demo/arbitrary",
        "https://github.com/owner/demo",
        "https://[broken/plugins/owner/demo",
        "https://platform.agentscope.io:443/plugins/owner/demo",
        "https://platform.agentscope.io/plugins/owner/demo#fragment",
        "https://platform.agentscope.io/plugins/owner/demo/archive/zip/..",
        "https://platform.agentscope.io/skills/owner/demo",
    ],
)
def test_noncanonical_sources_do_not_claim_platform_origin(url):
    assert origin_from_platform_url(url, "plugin") is None


def test_origin_identity_is_owner_scoped_and_type_scoped():
    one = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/alice/demo/archive/zip/master",
        "app",
        "1.2.3",
    )
    two = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/bob/demo",
        "plugin",
    )
    assert one["resource_id"] == "@alice/demo"
    assert one["resource_type"] == "app"
    assert one["installed_version"] == "1.2.3"
    assert one["resource_id"] != two["resource_id"]
    assert validated_origin(one) == one
    assert validated_origin({**one, "resource_id": "@bob/demo"}) is None
    assert validated_origin({"provider": "qwenpaw", "name": "demo"}) is None
    assert validated_origin({**one, "source_url": "https://[broken"}) is None


def test_plugin_origin_records_reject_corruption_and_wrong_local_id(tmp_path):
    origin = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/alice/demo",
        "plugin",
    )
    write_plugin_origin(tmp_path, "demo", origin)
    record_path = next((tmp_path / ".installation-origins").glob("*.json"))
    record_path.write_text(json.dumps({"local_id": "other", "origin": origin}))
    assert read_plugin_origin(tmp_path, "demo") is None
    record_path.write_text("not json")
    assert read_plugin_origin(tmp_path, "demo") is None
    record_path.write_text("[]")
    assert read_plugin_origin(tmp_path, "demo") is None


@pytest.mark.asyncio
async def test_failed_replacement_clears_previous_platform_origin(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import loader as loader_module

    plugins_dir = tmp_path / "plugins"
    installed = plugins_dir / "demo"
    installed.mkdir(parents=True)
    source = tmp_path / "replacement"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo", "version": "2.0.0"}),
    )
    origin = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/alice/demo",
        "plugin",
    )
    write_plugin_origin(plugins_dir, "demo", origin)

    def fail_copy(source_dir, target_dir):
        del source_dir
        target_dir.mkdir()
        raise OSError("copy interrupted")

    monkeypatch.setattr(loader_module.shutil, "copytree", fail_copy)
    loader = loader_module.PluginLoader(plugin_dirs=[plugins_dir])
    with pytest.raises(OSError, match="copy interrupted"):
        await loader.load_plugin_from_path(source, force=True)
    assert not installed.exists()
    assert read_plugin_origin(plugins_dir, "demo") is None


@pytest.mark.asyncio
async def test_failed_runtime_load_does_not_record_platform_origin(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    source = tmp_path / "package"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo", "version": "1.0.0"}),
    )
    plugins_dir = tmp_path / "plugins"
    loader = PluginLoader(plugin_dirs=[plugins_dir])
    monkeypatch.setattr(
        loader,
        "load_plugin",
        AsyncMock(side_effect=RuntimeError("load failed")),
    )
    with pytest.raises(RuntimeError, match="load failed"):
        await loader.load_plugin_from_path(
            source,
            installation_source=(
                "https://platform.agentscope.io/plugins/alice/demo"
            ),
        )
    assert read_plugin_origin(plugins_dir, "demo") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_type, is_pawapp",
    [("frontend", False), ("app", True), ("frontend", True)],
)
async def test_plugin_install_restart_upgrade_and_local_replacement(
    tmp_path,
    monkeypatch,
    plugin_type,
    is_pawapp,
):
    from qwenpaw.app.routers import plugins, pawapps
    from qwenpaw.config import utils as config_utils
    from qwenpaw.plugins.architecture import PluginRecord
    from qwenpaw.plugins.loader import PluginLoader

    plugins_dir = tmp_path / "plugins"
    source_dir = tmp_path / "package"
    source_dir.mkdir()
    manifest = {
        "id": "local-demo",
        "name": "Same display name",
        "version": "1.2.3",
        "type": plugin_type,
        "meta": (
            {"pawapp": {"category": "productivity"}} if is_pawapp else {}
        ),
        "installation_origin": {"provider": "agentscope-platform"},
    }
    (source_dir / "plugin.json").write_text(json.dumps(manifest))
    loader = PluginLoader(plugin_dirs=[plugins_dir])

    async def fake_load(package_manifest, target_dir, config):
        del config
        record = PluginRecord(package_manifest, target_dir, True)
        loader._loaded_plugins[package_manifest.id] = record
        return record

    async def fake_unload(plugin_id, delete_files=False):
        del delete_files
        loader._loaded_plugins.pop(plugin_id)

    monkeypatch.setattr(loader, "load_plugin", fake_load)
    monkeypatch.setattr(loader, "_unload_plugin_unlocked", fake_unload)
    monkeypatch.setattr(config_utils, "get_plugins_dir", lambda: plugins_dir)
    source_url = (
        "https://platform.agentscope.io/plugins/alice/demo/archive/zip/master"
    )
    await loader.load_plugin_from_path(
        source_dir,
        installation_source=source_url,
    )
    stored = read_plugin_origin(plugins_dir, "local-demo")
    assert stored["resource_id"] == "@alice/demo"
    assert stored["resource_type"] == ("app" if is_pawapp else "plugin")
    assert stored["installed_version"] == "1.2.3"
    # Startup listing reads installer metadata, independent of loaded state.
    assert (
        plugins._list_plugins_from_disk()[0]["installation_origin"] == stored
    )
    if is_pawapp:
        assert (
            pawapps._scan_installed_apps_fallback()[0]["installation_origin"]
            == stored
        )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                plugin_loader=loader,
            ),
        ),
    )
    assert (await plugins.list_plugins(request))[0][
        "installation_origin"
    ] == stored

    manifest["version"] = "2.0.0"
    (source_dir / "plugin.json").write_text(json.dumps(manifest))
    await loader.load_plugin_from_path(
        source_dir,
        force=True,
        installation_source=source_url,
    )
    assert (
        read_plugin_origin(plugins_dir, "local-demo")["installed_version"]
        == "2.0.0"
    )
    # The identical local id/package, including its claimed origin, is local.
    await loader.load_plugin_from_path(source_dir, force=True)
    assert read_plugin_origin(plugins_dir, "local-demo") is None
    assert plugins._list_plugins_from_disk()[0]["installation_origin"] is None
    if is_pawapp:
        assert (
            pawapps._scan_installed_apps_fallback()[0]["installation_origin"]
            is None
        )


@pytest.mark.asyncio
async def test_uninstall_removes_origin_record(tmp_path, monkeypatch):
    from qwenpaw.plugins.architecture import PluginManifest, PluginRecord
    from qwenpaw.plugins.loader import PluginLoader

    plugins_dir = tmp_path / "plugins"
    installed = plugins_dir / "demo"
    installed.mkdir(parents=True)
    manifest = PluginManifest.from_dict(
        {"id": "demo", "name": "Demo", "version": "1.0.0"},
    )
    loader = PluginLoader(plugin_dirs=[plugins_dir])
    loader._loaded_plugins[manifest.id] = PluginRecord(
        manifest,
        installed,
        True,
    )
    monkeypatch.setattr(loader, "_cleanup_plugin_tools", lambda *a: None)
    write_plugin_origin(
        plugins_dir,
        "demo",
        origin_from_platform_url(
            "https://platform.agentscope.io/plugins/alice/demo",
            "plugin",
        ),
    )
    await loader.unload_plugin("demo", delete_files=True)
    assert not installed.exists()
    assert read_plugin_origin(plugins_dir, "demo") is None


@pytest.mark.parametrize("is_pawapp", [False, True])
def test_offline_cli_install_replace_and_uninstall_origin(
    tmp_path,
    monkeypatch,
    is_pawapp,
):
    from click.testing import CliRunner

    from qwenpaw.cli import plugin_commands
    from qwenpaw.config import utils as config_utils

    plugins_dir = tmp_path / "plugins"
    source_dir = tmp_path / "package"
    source_dir.mkdir()
    (source_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo",
                "version": "1.0.0",
                "type": "frontend",
                "meta": {"pawapp": {"category": "tools"}} if is_pawapp else {},
            },
        ),
    )
    monkeypatch.setattr(config_utils, "get_plugins_dir", lambda: plugins_dir)
    monkeypatch.setattr(plugin_commands, "_is_running", lambda: False)
    monkeypatch.setattr(
        plugin_commands,
        "_download_plugin_from_url",
        lambda url: (source_dir, None),
    )
    monkeypatch.setattr(
        plugin_commands,
        "_sync_tool_plugin_to_agents",
        lambda m: None,
    )
    monkeypatch.setattr(
        plugin_commands,
        "_remove_tool_plugin_from_agents",
        lambda m: None,
    )
    runner = CliRunner()
    source_url = (
        "https://platform.agentscope.io/plugins/alice/demo/archive/zip/master"
    )
    installed = runner.invoke(plugin_commands.install, [source_url])
    assert installed.exit_code == 0, installed.output
    origin = read_plugin_origin(plugins_dir, "demo")
    assert origin["resource_type"] == ("app" if is_pawapp else "plugin")
    assert origin["resource_id"] == "@alice/demo"
    assert origin["installed_version"] == "1.0.0"
    replaced = runner.invoke(
        plugin_commands.install,
        [str(source_dir), "--force"],
    )
    assert replaced.exit_code == 0, replaced.output
    assert read_plugin_origin(plugins_dir, "demo") is None
    # Reinstalling from the platform restores provenance; uninstall removes it.
    installed = runner.invoke(plugin_commands.install, [source_url, "--force"])
    assert installed.exit_code == 0, installed.output
    assert read_plugin_origin(plugins_dir, "demo") is not None
    removed = runner.invoke(plugin_commands.uninstall, ["demo"], input="y\n")
    assert removed.exit_code == 0, removed.output
    assert not (plugins_dir / "demo").exists()
    assert read_plugin_origin(plugins_dir, "demo") is None


@pytest.mark.asyncio
async def test_skill_identity_survives_pool_workspace_reconcile_and_rename(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.agents.skill_system import hub, pool_service, registry, store
    from qwenpaw.agents.skill_system import workspace_service
    from qwenpaw.app.routers import skills as skills_api

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(registry, "import_builtin_skills", lambda **kw: {})
    monkeypatch.setattr(
        pool_service,
        "scan_skill_dir_or_raise",
        lambda *a: None,
    )
    monkeypatch.setattr(
        workspace_service,
        "scan_skill_dir_or_raise",
        lambda *a: None,
    )

    async def fake_bundle(url, version):
        del version
        return {
            "name": "Same display name",
            "files": {
                "SKILL.md": (
                    "---\nname: demo\ndescription: Example\nversion: 1.4.0\n"
                    "---\n# Example\n"
                ),
            },
        }, url

    monkeypatch.setattr(hub, "_resolve_bundle_from_url", fake_bundle)
    source_url = "https://platform.agentscope.io/skills/@alice/demo"
    result = await hub.import_pool_skill_from_hub(
        bundle_url=source_url,
        target_name="local-renamed",
    )
    expected = result.installation_origin
    assert expected["resource_id"] == "@alice/demo"
    assert expected["installed_version"] == "1.4.0"
    registry.reconcile_pool_manifest()
    assert (
        store.read_skill_pool_manifest()["skills"][result.name][
            "installation_origin"
        ]
        == expected
    )
    assert (
        skills_api._build_pool_skill_specs()[0].installation_origin.resource_id
        == "@alice/demo"
    )

    workspace = tmp_path / "agents" / "tester"
    workspace.mkdir(parents=True)
    pool = pool_service.SkillPoolService()
    downloaded = pool.download_to_workspace(result.name, workspace)
    assert downloaded["success"] is True
    registry.reconcile_workspace_manifest(workspace)
    assert (
        store.read_skill_manifest(workspace)["skills"][result.name][
            "installation_origin"
        ]
        == expected
    )
    assert (
        skills_api._build_workspace_skill_specs(workspace)[
            0
        ].installation_origin.resource_id
        == "@alice/demo"
    )
    # A pool edit/rename changes the local name, not the remote association.
    renamed = pool.save_pool_skill(
        skill_name=result.name,
        target_name="renamed-again",
        content="---\nname: demo\ndescription: Edited\n---\n# Edited\n",
    )
    assert renamed["success"] is True
    registry.reconcile_pool_manifest()
    assert (
        store.read_skill_pool_manifest()["skills"]["renamed-again"][
            "installation_origin"
        ]
        == expected
    )
    registry.reconcile_workspace_manifest(workspace)
    assert (
        store.read_skill_manifest(workspace)["skills"][result.name][
            "installation_origin"
        ]
        == expected
    )
    # A same-named local replacement has no recoverable remote identity.
    local = workspace_service.SkillService(workspace)
    assert local.disable_skill(result.name)["success"] is True
    assert local.delete_skill(result.name)
    assert (
        local.create_skill(
            result.name,
            "---\nname: demo\ndescription: Local\n---\n# Local\n",
        )
        == result.name
    )
    registry.reconcile_workspace_manifest(workspace)
    assert (
        skills_api._build_workspace_skill_specs(workspace)[
            0
        ].installation_origin
        is None
    )


def test_pool_sync_replaces_provenance_in_both_directions(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.agents.skill_system import pool_service, registry, store
    from qwenpaw.agents.skill_system import workspace_service

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(registry, "import_builtin_skills", lambda **kw: {})
    monkeypatch.setattr(
        pool_service,
        "scan_skill_dir_or_raise",
        lambda *a: None,
    )
    monkeypatch.setattr(
        workspace_service,
        "scan_skill_dir_or_raise",
        lambda *a: None,
    )
    content = "---\nname: demo\ndescription: Example\n---\n# Body\n"
    origin = origin_from_platform_url(
        "https://platform.agentscope.io/skills/@alice/demo",
        "skill",
    )
    workspace = tmp_path / "agents" / "tester"
    workspace.mkdir(parents=True)
    service = workspace_service.SkillService(workspace)
    pool = pool_service.SkillPoolService()

    service.create_skill("demo", content, installation_origin=origin)
    assert pool.upload_from_workspace(workspace, "demo")["success"] is True
    registry.reconcile_pool_manifest()
    assert (
        store.read_skill_pool_manifest()["skills"]["demo"][
            "installation_origin"
        ]
        == origin
    )
    # Replacing the pool entry from a local workspace clears platform identity.
    assert service.delete_skill("demo")
    service.create_skill("demo", content)
    assert (
        pool.upload_from_workspace(workspace, "demo", overwrite=True)[
            "success"
        ]
        is True
    )
    registry.reconcile_pool_manifest()
    assert (
        store.read_skill_pool_manifest()["skills"]["demo"][
            "installation_origin"
        ]
        is None
    )
    # Replacing a platform workspace entry from that local pool also clears it.
    assert service.delete_skill("demo")
    service.create_skill("demo", content, installation_origin=origin)
    assert (
        pool.download_to_workspace("demo", workspace, overwrite=True)[
            "success"
        ]
        is True
    )
    registry.reconcile_workspace_manifest(workspace)
    assert (
        store.read_skill_manifest(workspace)["skills"]["demo"][
            "installation_origin"
        ]
        is None
    )


def test_legacy_skill_labels_and_package_claims_do_not_create_origin(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.agents.skill_system import pool_service, registry
    from qwenpaw.agents.skill_system import workspace_service

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(registry, "import_builtin_skills", lambda **kw: {})
    monkeypatch.setattr(
        pool_service,
        "scan_skill_dir_or_raise",
        lambda *a: None,
    )
    monkeypatch.setattr(
        workspace_service,
        "scan_skill_dir_or_raise",
        lambda *a: None,
    )
    claimed_origin = origin_from_platform_url(
        "https://platform.agentscope.io/skills/@alice/demo",
        "skill",
    )
    content = (
        "---\nname: demo\ndescription: Example\n"
        f"installation_origin: {json.dumps(claimed_origin)}\n"
        "---\n# Body\n"
    )
    workspace = tmp_path / "agents" / "tester"
    workspace.mkdir(parents=True)
    service = workspace_service.SkillService(workspace)
    pool = pool_service.SkillPoolService()
    service.create_skill("demo", content, installed_from="qwenpaw")
    pool.create_skill("demo", content, installed_from="qwenpaw")
    registry.reconcile_workspace_manifest(workspace)
    registry.reconcile_pool_manifest()
    assert service.list_all_skills()[0].installation_origin is None
    assert pool.list_all_skills()[0].installation_origin is None


@pytest.mark.asyncio
async def test_workspace_hub_installs_have_independent_remote_ids(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.agents.skill_system import hub, store, workspace_service

    monkeypatch.setattr(
        workspace_service,
        "scan_skill_dir_or_raise",
        lambda *a: None,
    )

    async def fake_bundle(url, version):
        del version
        return {
            "name": "demo",
            "files": {
                "SKILL.md": (
                    "---\nname: demo\ndescription: Example\n---\n# Body\n"
                ),
            },
        }, url

    monkeypatch.setattr(hub, "_resolve_bundle_from_url", fake_bundle)
    for owner in ("alice", "bob"):
        result = await hub.install_skill_from_hub(
            workspace_dir=tmp_path,
            bundle_url=f"https://platform.agentscope.io/skills/@{owner}/demo",
            target_name=f"{owner}-local",
        )
        assert result.installation_origin["resource_id"] == f"@{owner}/demo"
        assert "installed_version" not in result.installation_origin
    entries = store.read_skill_manifest(tmp_path)["skills"]
    assert (
        entries["alice-local"]["installation_origin"]
        != entries["bob-local"]["installation_origin"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", [True, False])
async def test_native_installer_preserves_source_and_recovery_options(
    tmp_path,
    monkeypatch,
    remote,
):
    """The shared installer keeps provenance alongside PawPort recovery."""
    from qwenpaw.app.routers import plugins
    from qwenpaw.config import utils as config_utils

    source_dir = tmp_path / "package"
    source_dir.mkdir()
    source_url = (
        "https://platform.agentscope.io/plugins/alice/demo/archive/zip/master"
    )
    loader = SimpleNamespace(load_plugin_from_path=AsyncMock())
    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=loader))
    monkeypatch.setattr(plugins, "_async_download", AsyncMock())
    monkeypatch.setattr(
        plugins,
        "_extract_downloaded_plugin_zip",
        lambda *_: source_dir,
    )
    monkeypatch.setattr(
        config_utils,
        "get_plugins_dir",
        lambda: tmp_path / "plugins",
    )
    owner = {"owner": "pawport", "provider": "codex", "source_id": "demo"}
    await plugins.install_plugin_source(
        f"  {source_url if remote else source_dir}  ",
        app=app,
        force=True,
        reload_agents=False,
        pawport_owner=owner,
        recover_incomplete=True,
    )
    kwargs = loader.load_plugin_from_path.call_args.kwargs
    assert kwargs["source_path"] == source_dir
    assert kwargs["installation_source"] == (source_url if remote else "")
    assert kwargs["force"] is True
    assert kwargs["pawport_owner"] == owner
    assert kwargs["recover_incomplete"] is True
