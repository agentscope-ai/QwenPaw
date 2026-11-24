# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Skill metadata and deletion follow persistent directory ownership."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.skill_system.registry import reconcile_workspace_manifest
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.architecture import PluginManifest, PluginRecord
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import (
    delete_inventory,
    load_inventory,
    save_inventory,
)
from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture
def skills(tmp_path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    registry = PluginRegistry()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    info = {"workspace_dir": str(workspace), "agent_id": "agent"}
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.registry.list_workspaces",
        lambda: [info],
    )
    root = tmp_path / "plugins" / "demo"
    source = root / "skills"
    (source / "my-search").mkdir(parents=True)
    (source / "my-search" / "SKILL.md").write_text(
        "---\nname: my-search\ndescription: Search\n---\nFactory v1\n",
        encoding="utf-8",
    )
    manifest_data = {"id": "demo", "name": "Demo", "version": "1.0.0"}
    (root / "plugin.json").write_text(json.dumps(manifest_data))
    loader = PluginLoader([tmp_path / "plugins"])
    loader.registry = registry
    monkeypatch.setattr(loader, "_drop_uninstalled_settings", AsyncMock())
    inst = loader.lifecycle.ensure_instance("demo")
    api = PluginApi("demo", {}, manifest_data)
    api.set_registry(registry)
    api.bind_instance(inst)
    return SimpleNamespace(
        api=api,
        loader=loader,
        inst=inst,
        root=root,
        source=source,
        workspace=workspace,
        info=info,
        dest=workspace / "skills" / "my-search",
        manifest_path=workspace / "skill.json",
        manifest=PluginManifest.from_dict(manifest_data),
    )


def install(skills):
    skills.api._install_skills_into_workspace(
        skills.info,
        skills.source,
        "plugin:demo",
        True,
        ["console"],
    )


def read_entry(skills):
    return json.loads(skills.manifest_path.read_text())["skills"]["my-search"]


def set_user_state(skills, source="custom"):
    reconcile_workspace_manifest(skills.workspace)
    payload = json.loads(skills.manifest_path.read_text())
    payload["skills"]["my-search"].update(
        source=source,
        enabled=False,
        channels=["qq"],
    )
    skills.manifest_path.write_text(json.dumps(payload))


def make_user_skill(skills):
    skills.dest.mkdir(parents=True)
    (skills.dest / "SKILL.md").write_text(
        "---\nname: my-search\ndescription: User search\n---\nUser version\n",
        encoding="utf-8",
    )
    set_user_state(skills)


def test_same_name_user_skill_keeps_files_and_metadata(skills):
    make_user_skill(skills)
    before = (skills.dest / "SKILL.md").read_bytes()
    install(skills)
    assert (skills.dest / "SKILL.md").read_bytes() == before
    entry = read_entry(skills)
    assert entry["source"] == "custom"
    assert entry["enabled"] is False
    assert entry["channels"] == ["qq"]
    assert load_inventory("demo")["locations"][str(skills.dest)]["owned"] is (
        False
    )
    skills.api.manifest["version"] = "2.0.0"
    (skills.source / "my-search" / "added.txt").write_text("new factory file")
    install(skills)
    assert (skills.dest / "SKILL.md").read_bytes() == before
    assert sorted(path.name for path in skills.dest.iterdir()) == ["SKILL.md"]
    assert read_entry(skills)["source"] == "custom"
    assert read_entry(skills)["enabled"] is False
    assert read_entry(skills)["channels"] == ["qq"]


def test_owned_skill_migrates_without_resetting_user_settings(skills):
    install(skills)
    entry = read_entry(skills)
    assert entry["source"] == "plugin:demo"
    assert entry["enabled"] is True
    assert entry["channels"] == ["console"]
    assert load_inventory("demo")["locations"][str(skills.dest)]["owned"]
    set_user_state(skills, source="plugin:demo")
    install(skills)  # Same-version keep must not reset user preferences.
    skills.api.manifest["version"] = "2.0.0"
    factory = skills.source / "my-search" / "SKILL.md"
    factory.write_text(factory.read_text().replace("v1", "v2"))
    install(skills)
    assert "Factory v2" in (skills.dest / "SKILL.md").read_text()
    entry = read_entry(skills)
    assert entry["source"] == "plugin:demo"
    assert entry["enabled"] is False
    assert entry["channels"] == ["qq"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry_point,ownership",
    [
        ("live", "user"),
        ("disk", "user"),
        ("provider", "user"),
        ("live", "owned"),
        ("disk", "owned"),
        ("provider", "owned"),
        ("disk", "legacy"),
        ("disk", "missing"),
    ],
)
async def test_skill_cleanup_requires_inventory_ownership(
    skills,
    entry_point,
    ownership,
):
    if ownership in {"user", "missing"}:
        make_user_skill(skills)
    install(skills)
    # Simulate metadata damaged by the previous implementation.
    set_user_state(skills, source="plugin:demo")
    before = (skills.dest / "SKILL.md").read_bytes()
    if ownership == "legacy":
        data = load_inventory("demo")
        loc = data["locations"][str(skills.dest)]
        loc.pop("owned")
        loc["branch"] = "create"
        save_inventory("demo", data)
    elif ownership == "missing":
        delete_inventory("demo")
    if entry_point == "provider":
        skills.api.unregister_skill_provider()
    else:
        if entry_point == "live":
            skills.api.register_skill_provider(skills.source)
            skills.inst.activated = True
            skills.loader._loaded_plugins["demo"] = PluginRecord(
                manifest=skills.manifest,
                source_path=skills.root,
                instance=object(),
                enabled=True,
                status="active",
            )
        else:
            skills.loader.lifecycle.drop_instance("demo")
        report = await skills.loader.unload_plugin(
            "demo",
            mode=UnloadMode.UNINSTALL,
        )
        assert report.clean
        assert report.quiescent
    entries = json.loads(skills.manifest_path.read_text())["skills"]
    if ownership in {"owned", "legacy"}:
        assert not skills.dest.exists()
        assert "my-search" not in entries
    else:
        assert (skills.dest / "SKILL.md").read_bytes() == before
        assert entries["my-search"]["source"] == "plugin:demo"
        assert entries["my-search"]["enabled"] is False
        assert entries["my-search"]["channels"] == ["qq"]
