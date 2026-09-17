# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for the runtime resolution layer of the skill registry.

Covers the prerequisite check that never starts a process
(``check_skill_dependencies``), the broadcast workspace listing with its
two failure fallbacks (``list_workspaces``), the strict preload
selection, the metadata-only workspace fingerprint, and the bounded
LRU that caches those fingerprints.

Nothing here reads or writes the real skill pool: every path comes
from ``tmp_path``, and the driver cards are created in a throwaway
workspace. The inventory cache is a module global, so the fixture
that touches it restores the previous contents explicitly instead of
relying on ``monkeypatch.undo()``, which would also revert unrelated
patches installed by other fixtures.
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import registry as reg
from qwenpaw.agents.skill_system.models import SkillRequirements
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.storage import card_path, dump_card

# A name that cannot exist in any PATH the tests build. Note that
# shell_execution_path(None) prepends the running interpreter's
# directory, so short guesses such as "sh" are not safe negatives.
ABSENT_BINARY = "qwenpaw_absent_binary_for_tests_0917"


def _write_card(
    workspace: Path,
    name: str,
    *,
    card_name: str | None = None,
    protocol: str = "mcp",
    enabled: bool = True,
) -> Path:
    """Create one driver card and return its canonical path."""
    card = DriverCard(
        name=card_name or name,
        protocol=protocol,
        endpoint={"url": "http://127.0.0.1:9"},
        enabled=enabled,
    )
    path = card_path(workspace / "drivers", name, "mcp")
    dump_card(card, path)
    return path


def _write_manifest(workspace: Path, skills: dict) -> Path:
    """Write a workspace skill manifest and return its path."""
    path = reg.get_workspace_skill_manifest_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"skills": skills}),
        encoding="utf-8",
    )
    return path


class TestCheckSkillDependencies:
    """The check reports unmet prerequisites and starts nothing."""

    def test_unmet_env_and_missing_binary_are_both_reported(self):
        req = SkillRequirements(
            require_envs=["FOO_BAR"],
            require_bins=[ABSENT_BINARY],
        )

        result = reg.check_skill_dependencies(req, {"PATH": "/usr/bin"}, None)

        assert result == [
            "Environment variable not set: FOO_BAR",
            f"CLI binary not found on PATH: {ABSENT_BINARY}",
        ]

    def test_empty_env_value_counts_as_unset(self):
        req = SkillRequirements(require_envs=["FOO_BAR"])

        result = reg.check_skill_dependencies(req, {"FOO_BAR": ""}, None)

        assert result == ["Environment variable not set: FOO_BAR"]

    def test_present_env_value_is_satisfied(self):
        req = SkillRequirements(require_envs=["FOO_BAR"])

        assert reg.check_skill_dependencies(req, {"FOO_BAR": "v"}, None) == []

    def test_binary_found_on_the_given_path_is_satisfied(self, tmp_path):
        binary_dir = tmp_path / "bins"
        binary_dir.mkdir()
        found = binary_dir / "qwenpaw_probe_tool"
        found.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        found.chmod(0o755)
        req = SkillRequirements(require_bins=["qwenpaw_probe_tool"])

        result = reg.check_skill_dependencies(
            req,
            {"PATH": str(binary_dir)},
            None,
        )

        assert result == []

    def test_no_requirements_reports_nothing(self):
        assert (
            reg.check_skill_dependencies(SkillRequirements(), {}, None) == []
        )

    def test_mcp_is_not_checked_without_a_workspace(self):
        req = SkillRequirements(require_mcps=["srv"])

        assert reg.check_skill_dependencies(req, {}, None) == []

    def test_absent_drivers_directory_means_not_configured(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        req = SkillRequirements(require_mcps=["srv"])

        result = reg.check_skill_dependencies(req, {}, workspace)

        assert result == ["MCP server not configured: srv"]

    def test_enabled_mcp_card_is_satisfied(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _write_card(workspace, "srv")
        req = SkillRequirements(require_mcps=["srv"])

        assert reg.check_skill_dependencies(req, {}, workspace) == []

    def test_disabled_mcp_card_is_reported_separately(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _write_card(workspace, "srv", enabled=False)
        req = SkillRequirements(require_mcps=["srv"])

        result = reg.check_skill_dependencies(req, {}, workspace)

        assert result == ["MCP server is disabled: srv"]

    def test_card_named_something_else_is_invalid(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        path = _write_card(workspace, "srv")
        path.unlink()
        path.write_text(
            "name: other\n"
            "protocol: mcp\n"
            "endpoint:\n"
            "  url: http://127.0.0.1:9\n",
            encoding="utf-8",
        )
        req = SkillRequirements(require_mcps=["srv"])

        result = reg.check_skill_dependencies(req, {}, workspace)

        assert result == ["MCP server configuration is invalid: srv"]

    def test_non_mcp_protocol_card_is_invalid(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        path = _write_card(workspace, "srv")
        path.unlink()
        path.write_text(
            "name: srv\n"
            "protocol: http\n"
            "endpoint:\n"
            "  url: http://127.0.0.1:9\n",
            encoding="utf-8",
        )
        req = SkillRequirements(require_mcps=["srv"])

        result = reg.check_skill_dependencies(req, {}, workspace)

        assert result == ["MCP server configuration is invalid: srv"]

    def test_malformed_card_yaml_is_invalid(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        path = _write_card(workspace, "srv")
        path.unlink()
        path.write_text("[not: a mapping\n", encoding="utf-8")
        req = SkillRequirements(require_mcps=["srv"])

        result = reg.check_skill_dependencies(req, {}, workspace)

        assert result == ["MCP server configuration is invalid: srv"]

    def test_unreadable_card_is_invalid_not_crash(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        path = _write_card(workspace, "srv")
        path.unlink()
        # A lone surrogate cannot be decoded as UTF-8, which is the
        # UnicodeError leg of the card guard.
        path.write_bytes(
            b"name: srv\nprotocol: mcp\nendpoint:\n" b"  url: \xed\xa0\x80\n",
        )
        req = SkillRequirements(require_mcps=["srv"])

        result = reg.check_skill_dependencies(req, {}, workspace)

        assert result == ["MCP server configuration is invalid: srv"]


class TestListWorkspaces:
    """Broadcast targets come from the config, never from a scan."""

    @pytest.fixture
    def fake_config(self, monkeypatch, tmp_path):
        """Install a config with two agents, ordered b-then-a."""

        def _install(profile_dirs):
            profiles = {
                agent_id: type("P", (), {"workspace_dir": wd})()
                for agent_id, wd in profile_dirs.items()
            }
            config = type(
                "C",
                (),
                {"agents": type("A", (), {"profiles": profiles})()},
            )()
            monkeypatch.setattr(
                "qwenpaw.config.utils.load_config",
                lambda *a, **k: config,
            )
            return config

        return _install

    def test_ids_are_sorted_and_workspace_dir_is_absolute(
        self,
        monkeypatch,
        fake_config,
        tmp_path,
    ):
        fake_config(
            {
                "agent_b": str(tmp_path / "ws_b"),
                "agent_a": str(
                    tmp_path / "ws_a",
                ),
            },
        )
        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda agent_id: type("A", (), {"name": f"Display {agent_id}"})(),
        )

        result = reg.list_workspaces()

        assert [item["agent_id"] for item in result] == ["agent_a", "agent_b"]
        assert result[0]["agent_name"] == "Display agent_a"
        assert result[0]["workspace_dir"] == str(tmp_path / "ws_a")

    def test_failing_agent_config_falls_back_to_the_agent_id(
        self,
        monkeypatch,
        fake_config,
        tmp_path,
    ):
        fake_config({"agent_b": str(tmp_path / "ws_b")})

        def boom(agent_id):
            raise RuntimeError("agent config unreadable")

        monkeypatch.setattr("qwenpaw.config.config.load_agent_config", boom)

        result = reg.list_workspaces()

        assert result == [
            {
                "agent_id": "agent_b",
                "agent_name": "agent_b",
                "workspace_dir": str(tmp_path / "ws_b"),
            },
        ]

    @pytest.mark.parametrize("blank_name", ["", None])
    def test_blank_display_name_falls_back_to_the_agent_id(
        self,
        monkeypatch,
        fake_config,
        tmp_path,
        blank_name,
    ):
        fake_config({"agent_a": str(tmp_path / "ws_a")})
        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda agent_id: type("A", (), {"name": blank_name})(),
        )

        result = reg.list_workspaces()

        assert result[0]["agent_name"] == "agent_a"

    def test_unreadable_config_yields_an_empty_list_not_an_error(
        self,
        monkeypatch,
    ):
        def boom(*args, **kwargs):
            raise RuntimeError("config unreadable")

        monkeypatch.setattr("qwenpaw.config.utils.load_config", boom)

        assert reg.list_workspaces() == []

    def test_config_without_profiles_yields_an_empty_list(
        self,
        monkeypatch,
        fake_config,
    ):
        fake_config({})
        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda agent_id: type("A", (), {"name": agent_id})(),
        )

        assert reg.list_workspaces() == []

    def test_unlisted_workspace_on_disk_is_never_broadcast(
        self,
        monkeypatch,
        fake_config,
        tmp_path,
    ):
        """A directory scan would resurrect deleted agents."""
        fake_config({"agent_a": str(tmp_path / "ws_a")})
        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda agent_id: type("A", (), {"name": agent_id})(),
        )
        (tmp_path / "workspaces" / "ghost").mkdir(parents=True)

        result = reg.list_workspaces()

        assert [item["agent_id"] for item in result] == ["agent_a"]


class TestSelectPreloadSkills:
    """Only a literal ``preload: true`` opts a skill into preloading."""

    def test_only_strict_true_preload_is_selected(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _write_manifest(
            workspace,
            {
                "a": {"enabled": True, "preload": True},
                "b": {"enabled": True, "preload": "yes"},
                "c": {"enabled": True},
                "d": {"enabled": True, "preload": False},
            },
        )

        result = reg.select_preload_skills(workspace, ["a", "b", "c", "d"])

        assert result == ["a"]

    def test_result_follows_the_input_order(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _write_manifest(
            workspace,
            {"a": {"preload": True}, "b": {"preload": True}},
        )

        assert reg.select_preload_skills(workspace, ["b", "a"]) == ["b", "a"]

    def test_unknown_and_empty_inputs_select_nothing(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _write_manifest(workspace, {"a": {"preload": True}})

        assert reg.select_preload_skills(workspace, ["zzz"]) == []
        assert reg.select_preload_skills(workspace, []) == []

    def test_missing_manifest_selects_nothing(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()

        assert reg.select_preload_skills(workspace, ["a"]) == []


def _make_skill_dir(root: Path, name: str, *, body: str | None = None):
    """Create one workspace skill directory with a SKILL.md."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    text = body or f"---\nname: {name}\n---\nhello\n"
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return skill_dir


class TestWorkspaceSkillInventory:
    """The fingerprint is metadata only and tolerates broken entries."""

    def test_only_skill_dirs_holding_skill_md_are_fingerprinted(
        self,
        tmp_path,
    ):
        workspace = tmp_path / "ws"
        skills = reg.get_workspace_skills_dir(workspace)
        _make_skill_dir(skills, "alpha")
        (skills / "beta").mkdir(parents=True)  # no SKILL.md

        inventory = reg._workspace_skill_inventory(workspace)

        assert [name for name, _, _ in inventory.skills] == ["alpha"]
        assert inventory.manifest is None

    def test_manifest_signature_is_present_once_written(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _make_skill_dir(reg.get_workspace_skills_dir(workspace), "alpha")
        assert reg._workspace_skill_inventory(workspace).manifest is None

        _write_manifest(workspace, {"alpha": {"enabled": True}})

        assert reg._workspace_skill_inventory(workspace).manifest is not None

    def test_ignored_entries_and_plain_files_are_skipped(self, tmp_path):
        workspace = tmp_path / "ws"
        skills = reg.get_workspace_skills_dir(workspace)
        _make_skill_dir(skills, "alpha")
        _make_skill_dir(skills, "__pycache__")
        _make_skill_dir(skills, ".hidden")
        (skills / "plain.txt").write_text("i-am-a-file", encoding="utf-8")

        inventory = reg._workspace_skill_inventory(workspace)

        assert [name for name, _, _ in inventory.skills] == ["alpha"]

    def test_dangling_symlink_is_skipped_not_fatal(self, tmp_path):
        workspace = tmp_path / "ws"
        skills = reg.get_workspace_skills_dir(workspace)
        _make_skill_dir(skills, "alpha")
        try:
            os.symlink(str(tmp_path / "nowhere"), str(skills / "broken"))
        except (OSError, NotImplementedError, AttributeError) as exc:
            pytest.skip(f"this platform cannot create a symlink: {exc}")

        inventory = reg._workspace_skill_inventory(workspace)

        assert [name for name, _, _ in inventory.skills] == ["alpha"]

    def test_missing_skill_root_yields_an_empty_inventory(self, tmp_path):
        inventory = reg._workspace_skill_inventory(tmp_path / "nope")

        assert inventory.skills == ()
        assert inventory.manifest is None

    def test_repeated_reads_are_value_equal(self, tmp_path):
        workspace = tmp_path / "ws"
        _make_skill_dir(reg.get_workspace_skills_dir(workspace), "alpha")

        first = reg._workspace_skill_inventory(workspace)
        second = reg._workspace_skill_inventory(workspace)

        assert first == second

    def test_touching_skill_md_changes_the_fingerprint(self, tmp_path):
        workspace = tmp_path / "ws"
        skill_dir = _make_skill_dir(
            reg.get_workspace_skills_dir(workspace),
            "alpha",
        )
        first = reg._workspace_skill_inventory(workspace)

        (skill_dir / "SKILL.md").write_text(
            "---\nname: alpha\n---\nchanged\n",
            encoding="utf-8",
        )
        second = reg._workspace_skill_inventory(workspace)

        assert first != second


class TestWorkspaceInventoryCache:
    """The fingerprint cache is a bounded LRU."""

    @pytest.fixture
    def clean_cache(self):
        """Swap in an empty cache and restore the previous entries."""
        saved = OrderedDict(reg._WORKSPACE_INVENTORIES)
        reg._WORKSPACE_INVENTORIES.clear()
        try:
            yield reg._WORKSPACE_INVENTORIES
        finally:
            reg._WORKSPACE_INVENTORIES.clear()
            reg._WORKSPACE_INVENTORIES.update(saved)

    def test_entries_beyond_the_cap_evict_the_oldest(self, clean_cache):
        cap = reg._MAX_WORKSPACE_INVENTORIES
        inventory = reg._WorkspaceInventory(None, ())

        for index in range(cap + 3):
            reg._remember_workspace_inventory(f"k{index:04d}", inventory)

        assert len(clean_cache) == cap
        for index in range(3):
            assert reg._cached_workspace_inventory(f"k{index:04d}") is None
        assert reg._cached_workspace_inventory(f"k{cap + 2:04d}") is not None

    def test_a_cached_hit_moves_the_entry_out_of_eviction_order(
        self,
        clean_cache,
    ):
        cap = reg._MAX_WORKSPACE_INVENTORIES
        inventory = reg._WorkspaceInventory(None, ())
        for index in range(cap):
            reg._remember_workspace_inventory(f"k{index:04d}", inventory)

        assert reg._cached_workspace_inventory("k0000") is not None
        reg._remember_workspace_inventory("overflow", inventory)

        assert "k0000" in clean_cache
        assert "k0001" not in clean_cache

    def test_remembering_the_same_key_does_not_grow_the_cache(
        self,
        clean_cache,
    ):
        inventory = reg._WorkspaceInventory(None, ())

        reg._remember_workspace_inventory("dup", inventory)
        reg._remember_workspace_inventory("dup", inventory)

        assert len(clean_cache) == 1

    def test_remembering_a_key_replaces_its_value(self, clean_cache):
        empty = reg._WorkspaceInventory(None, ())
        populated = reg._WorkspaceInventory(None, (("alpha", 1, 2),))

        reg._remember_workspace_inventory("ws", empty)
        reg._remember_workspace_inventory("ws", populated)

        assert reg._cached_workspace_inventory("ws") is populated
