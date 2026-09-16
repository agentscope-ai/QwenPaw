# -*- coding: utf-8 -*-
"""Tests for the legacy skill migration and builtin QA agent bootstrap.

``test_migration.py`` pins the early-return legs of ``app/migration.py``
(exception wrappers, "pool manifest already exists", "config failed to
load"). This file covers what happens once those guards pass: the legacy
skill discovery/copy/reconcile pipeline, the two pure helpers that decide
whether the builtin QA workspace may be claimed, and the QA creation leg
that writes the profile into config.
"""
# pylint: disable=protected-access,too-many-arguments,too-many-locals
# pylint: disable=redefined-outer-name,unused-argument
# C1803 is disabled because `== []` is the assertion being made: `not saved`
# would also accept None, which is a different (and weaker) claim. Same
# convention as test_migration.py and 69 other upstream test files.
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.agents.skill_system import store as skill_store
from qwenpaw.app import migration
from qwenpaw.config.config import AgentProfileRef, Config
from qwenpaw.constant import BUILTIN_QA_AGENT_ID, LEGACY_QA_AGENT_ID

SKILL_BODY = "---\nname: {name}\n---\n\n# {name}\n\nBody: {body}\n"


def _write_skill(root: Path, name: str, body: str = "default") -> Path:
    """Create ``<root>/<name>/SKILL.md`` and assert it really landed.

    The assert is deliberate: a skill written to the wrong directory level
    makes the migration silently take its "nothing found" branch, which
    would keep these tests green while covering nothing.
    """
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        SKILL_BODY.format(name=name, body=body),
        encoding="utf-8",
    )
    assert skill_md.is_file()
    return skill_dir


def _config(profiles: dict | None = None, active: str = "default") -> Config:
    cfg = Config()
    cfg.agents.profiles = profiles if profiles is not None else {}
    cfg.agents.active_agent = active
    return cfg


def _ref(agent_id: str, workspace_dir: Path, **kwargs) -> AgentProfileRef:
    return AgentProfileRef(
        id=agent_id,
        workspace_dir=str(workspace_dir),
        **kwargs,
    )


def _owner_of(
    profiles: dict,
    workspace: Path,
    builtin: str = BUILTIN_QA_AGENT_ID,
):
    """Call the ownership helper in a form that needs no line folding."""
    return migration._other_agent_owns_workspace(profiles, workspace, builtin)


def _read_manifest(workspace_dir: Path) -> dict:
    path = workspace_dir / "skill.json"
    assert path.is_file(), f"no manifest at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _enabled_map(workspace_dir: Path) -> dict:
    return {
        name: entry["enabled"]
        for name, entry in _read_manifest(workspace_dir)["skills"].items()
    }


def _leaves(payload, prefix: str = "") -> dict:
    """Flatten a json payload into ``{dotted path: scalar}``."""
    flat = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            flat.update(_leaves(value, f"{prefix}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            flat.update(_leaves(value, f"{prefix}[{index}]"))
    else:
        flat[prefix] = payload
    return flat


def _changed_leaf_paths(before: dict, after: dict) -> set:
    left, right = _leaves(before), _leaves(after)
    return {
        path
        for path in set(left) | set(right)
        if left.get(path) != right.get(path)
    }


@pytest.fixture()
def migrated_env(tmp_path, monkeypatch):
    """Point every WORKING_DIR-derived path at ``tmp_path``.

    ``skill_store.get_pool_skill_manifest_path`` reads ``WORKING_DIR`` from
    inside the function body, so patching ``migration.WORKING_DIR`` alone
    leaves it pointing at the real pool: patch the getter instead.
    """
    wd = tmp_path / "wd"
    (wd / "workspaces").mkdir(parents=True)
    monkeypatch.setattr(migration, "WORKING_DIR", str(wd))
    monkeypatch.setattr(
        skill_store,
        "get_pool_skill_manifest_path",
        lambda: wd / "skill_pool" / "skill.json",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skill_pool_initialized",
        lambda: True,
    )
    return wd


@pytest.fixture()
def single_default_workspace(migrated_env, monkeypatch):
    """One ``default`` workspace whose profile points at it."""
    ws = migrated_env / "workspaces" / "default"
    ws.mkdir(parents=True)
    cfg = _config({"default": _ref("default", ws)})
    monkeypatch.setattr(migration, "load_config", lambda: cfg)
    return ws


# ---------------------------------------------------------------------------
# _do_migrate_legacy_skills: the copy pipeline
# ---------------------------------------------------------------------------


class TestLegacySkillsCopyPipeline:
    def test_customized_only_skill_is_copied_and_stays_disabled(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "customized_skills", "mine", "c1")

        assert migration._do_migrate_legacy_skills() is True

        target = single_default_workspace / "skills" / "mine"
        assert (target / "SKILL.md").is_file()
        assert _enabled_map(single_default_workspace) == {"mine": False}

    def test_active_only_skill_is_copied_and_enabled(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "active_skills", "live", "a1")

        assert migration._do_migrate_legacy_skills() is True

        assert (single_default_workspace / "skills" / "live").is_dir()
        assert _enabled_map(single_default_workspace) == {"live": True}

    def test_same_name_same_content_yields_one_enabled_copy(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "customized_skills", "both", "identical")
        _write_skill(migrated_env / "active_skills", "both", "identical")

        assert migration._do_migrate_legacy_skills() is True

        copied = sorted(
            p.name
            for p in (single_default_workspace / "skills").iterdir()
            if p.is_dir()
        )
        assert copied == ["both"]
        assert _enabled_map(single_default_workspace) == {"both": True}

    def test_same_name_different_content_keeps_both_versions(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "customized_skills", "clash", "custom")
        _write_skill(migrated_env / "active_skills", "clash", "active")

        assert migration._do_migrate_legacy_skills() is True

        skills = single_default_workspace / "skills"
        assert (skills / "clash-customize" / "SKILL.md").is_file()
        assert (skills / "clash-active" / "SKILL.md").is_file()
        assert not (skills / "clash").exists()
        # the suffixed active copy stays usable, the custom one does not
        assert _enabled_map(single_default_workspace) == {
            "clash-active": True,
            "clash-customize": False,
        }
        assert "custom" in (skills / "clash-customize" / "SKILL.md").read_text(
            encoding="utf-8",
        )
        assert "active" in (skills / "clash-active" / "SKILL.md").read_text(
            encoding="utf-8",
        )

    def test_os_artifacts_do_not_change_the_signature(
        self,
        migrated_env,
        single_default_workspace,
    ):
        source = _write_skill(migrated_env / "customized_skills", "art")
        for noise in ("__pycache__", "__MACOSX"):
            (source / noise).mkdir()
            (source / noise / "junk.pyc").write_bytes(b"junk")
        (source / ".DS_Store").write_bytes(b"ds")
        (source / "Thumbs.db").write_bytes(b"thumbs")
        (source / "desktop.ini").write_bytes(b"ini")

        assert migration._do_migrate_legacy_skills() is True

        copied = single_default_workspace / "skills" / "art"
        assert (copied / "SKILL.md").is_file()
        # the artifacts are filtered out of the copy, not just the digest
        assert not (copied / "__pycache__").exists()
        assert not (copied / ".DS_Store").exists()

    def test_second_run_copies_nothing_and_returns_false(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "active_skills", "once", "v1")

        assert migration._do_migrate_legacy_skills() is True
        first = _read_manifest(single_default_workspace)
        assert migration._do_migrate_legacy_skills() is False
        second = _read_manifest(single_default_workspace)

        # the second pass moves nothing but the manifest counter and the
        # refreshed timestamp: pinning the exact leaf set means a future
        # change to skill state cannot hide behind a stripped comparison
        assert _changed_leaf_paths(first, second) == {
            ".version",
            ".skills.once.updated_at",
        }
        assert second["version"] > first["version"]
        assert _enabled_map(single_default_workspace) == {"once": True}

    def test_existing_target_with_different_content_is_not_overwritten(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "active_skills", "sk", "from-legacy")
        existing = single_default_workspace / "skills" / "sk"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("KEEP-ME", encoding="utf-8")

        assert migration._do_migrate_legacy_skills() is False

        assert (existing / "SKILL.md").read_text(encoding="utf-8") == "KEEP-ME"

    def test_no_legacy_skill_dirs_creates_workspace_skeleton_only(
        self,
        migrated_env,
        single_default_workspace,
    ):
        assert migration._do_migrate_legacy_skills() is False

        assert (single_default_workspace / "skills").is_dir()
        assert _read_manifest(single_default_workspace)["skills"] == {}

    def test_legacy_root_is_used_when_default_workspace_is_empty(
        self,
        migrated_env,
        single_default_workspace,
    ):
        # legacy artefacts live at the WORKING_DIR root, not in a workspace
        _write_skill(migrated_env / "active_skills", "rootlevel", "rl")

        assert migration._do_migrate_legacy_skills() is True

        assert (
            single_default_workspace / "skills" / "rootlevel" / "SKILL.md"
        ).is_file()
        assert _enabled_map(single_default_workspace) == {"rootlevel": True}

    def test_legacy_root_is_ignored_when_workspace_already_has_skills(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "active_skills", "rootlevel", "rl")
        _write_skill(
            single_default_workspace / "skills",
            "already",
            "existing",
        )

        assert migration._do_migrate_legacy_skills() is False

        skills = single_default_workspace / "skills"
        assert not (skills / "rootlevel").exists()
        assert (skills / "already").is_dir()

    def test_legacy_root_is_ignored_when_the_default_workspace_has_one(
        self,
        migrated_env,
        single_default_workspace,
    ):
        # both roots hold legacy skills: the workspace wins, the
        # WORKING_DIR root is left alone so nothing is mixed together
        _write_skill(migrated_env / "active_skills", "atroot", "root-body")
        _write_skill(
            single_default_workspace / "customized_skills",
            "inworkspace",
            "ws-body",
        )

        assert migration._do_migrate_legacy_skills() is True

        skills = single_default_workspace / "skills"
        assert (skills / "inworkspace" / "SKILL.md").is_file()
        assert not (skills / "atroot").exists()
        # an in-workspace customized skill is copied but not enabled
        assert _enabled_map(single_default_workspace) == {
            "inworkspace": False,
        }

    def test_a_legacy_root_that_is_a_file_is_not_a_skill_root(
        self,
        migrated_env,
        single_default_workspace,
    ):
        (migrated_env / "customized_skills").write_text("i am a file")
        _write_skill(migrated_env / "active_skills", "live", "a")

        assert migration._do_migrate_legacy_skills() is True

        skills = single_default_workspace / "skills"
        assert (skills / "live").is_dir()
        assert not (skills / "customized_skills").exists()

    def test_directories_without_skill_md_are_not_discovered(
        self,
        migrated_env,
        single_default_workspace,
    ):
        root = migrated_env / "customized_skills"
        (root / "notaskill").mkdir(parents=True)
        (root / "notaskill" / "README.md").write_text("hi", encoding="utf-8")
        (root / "stray.txt").write_text("file", encoding="utf-8")

        assert migration._do_migrate_legacy_skills() is False

        assert _read_manifest(single_default_workspace)["skills"] == {}

    def test_profile_and_workspaces_dir_are_deduplicated(
        self,
        migrated_env,
        monkeypatch,
    ):
        ws = migrated_env / "workspaces" / "default"
        ws.mkdir(parents=True)
        # the profile and the on-disk scan both resolve to the same dir
        cfg = _config({"default": _ref("default", ws)})
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        _write_skill(migrated_env / "customized_skills", "dup", "d")

        assert migration._do_migrate_legacy_skills() is True

        # one copy, and reconcile ran once for that workspace
        assert (ws / "skills" / "dup").is_dir()
        assert list(_enabled_map(ws)) == ["dup"]

    def test_extra_workspace_directory_is_also_migrated(
        self,
        migrated_env,
        monkeypatch,
    ):
        ws = migrated_env / "workspaces" / "other"
        ws.mkdir(parents=True)
        _write_skill(ws / "customized_skills", "inws", "w")
        cfg = _config({"other": _ref("other", ws)})
        monkeypatch.setattr(migration, "load_config", lambda: cfg)

        assert migration._do_migrate_legacy_skills() is True

        assert (ws / "skills" / "inws").is_dir()
        assert _enabled_map(ws) == {"inws": False}

    def test_manifest_schema_version_is_written(
        self,
        migrated_env,
        single_default_workspace,
    ):
        _write_skill(migrated_env / "active_skills", "sch", "s")

        migration._do_migrate_legacy_skills()

        manifest = _read_manifest(single_default_workspace)
        assert manifest["schema_version"] == "workspace-skill-manifest.v1"
        entry = manifest["skills"]["sch"]
        assert entry["enabled"] is True
        assert entry["metadata"]["name"] == "sch"


# ---------------------------------------------------------------------------
# _other_agent_owns_workspace
# ---------------------------------------------------------------------------


class TestOtherAgentOwnsWorkspace:
    def test_empty_profiles_claim_nothing(self, tmp_path):
        target = tmp_path / "workspaces" / BUILTIN_QA_AGENT_ID
        assert _owner_of({}, target) is None

    def test_another_agent_on_the_same_path_is_reported(self, tmp_path):
        target = tmp_path / "workspaces" / BUILTIN_QA_AGENT_ID
        profiles = {"alice": _ref("alice", target)}
        assert _owner_of(profiles, target) == "alice"

    def test_the_builtin_slot_itself_is_skipped(self, tmp_path):
        target = tmp_path / "workspaces" / BUILTIN_QA_AGENT_ID
        profiles = {BUILTIN_QA_AGENT_ID: _ref(BUILTIN_QA_AGENT_ID, target)}
        assert _owner_of(profiles, target) is None

    def test_a_different_path_is_not_a_conflict(self, tmp_path):
        target = tmp_path / "workspaces" / BUILTIN_QA_AGENT_ID
        profiles = {"bob": _ref("bob", tmp_path / "somewhere-else")}
        assert _owner_of(profiles, target) is None

    def test_equivalent_path_with_dotdot_still_conflicts(self, tmp_path):
        target = tmp_path / "workspaces" / BUILTIN_QA_AGENT_ID
        roundabout = target.parent / "subdir" / ".." / BUILTIN_QA_AGENT_ID
        profiles = {"carol": _ref("carol", roundabout)}
        assert _owner_of(profiles, target) == "carol"

    def test_missing_directories_compare_by_path(self, tmp_path):
        target = tmp_path / "nope" / BUILTIN_QA_AGENT_ID
        profiles = {"dave": _ref("dave", target)}
        assert _owner_of(profiles, target) == "dave"

    def test_tilde_is_expanded_on_both_sides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        target = tmp_path / "ws"
        profiles = {"eve": _ref("eve", Path.home() / "ws")}
        assert _owner_of(profiles, target) == "eve"

    def test_the_excluded_id_can_be_overridden(self, tmp_path):
        target = tmp_path / "ws"
        profiles = {"frank": _ref("frank", target)}
        assert (
            migration._other_agent_owns_workspace(
                profiles,
                target,
                "frank",
            )
            is None
        )


# ---------------------------------------------------------------------------
# _fallback_active_agent_id
# ---------------------------------------------------------------------------


class TestFallbackActiveAgentId:
    def test_builtin_qa_wins_when_available(self, tmp_path):
        cfg = _config(
            {BUILTIN_QA_AGENT_ID: _ref(BUILTIN_QA_AGENT_ID, tmp_path)},
        )
        assert (
            migration._fallback_active_agent_id(cfg, "gone")
            == BUILTIN_QA_AGENT_ID
        )

    def test_default_is_used_when_qa_is_the_excluded_one(self, tmp_path):
        cfg = _config(
            {
                BUILTIN_QA_AGENT_ID: _ref(BUILTIN_QA_AGENT_ID, tmp_path),
                "default": _ref("default", tmp_path),
            },
        )
        assert (
            migration._fallback_active_agent_id(cfg, BUILTIN_QA_AGENT_ID)
            == "default"
        )

    def test_disabled_qa_falls_through_to_default(self, tmp_path):
        cfg = _config(
            {
                BUILTIN_QA_AGENT_ID: _ref(
                    BUILTIN_QA_AGENT_ID,
                    tmp_path,
                    enabled=False,
                ),
                "default": _ref("default", tmp_path),
            },
        )
        assert migration._fallback_active_agent_id(cfg, "gone") == "default"

    def test_no_preferred_profile_picks_any_enabled_one(self, tmp_path):
        cfg = _config({"zed": _ref("zed", tmp_path)})
        assert migration._fallback_active_agent_id(cfg, "gone") == "zed"

    def test_everything_disabled_still_prefers_default(self, tmp_path):
        cfg = _config({"default": _ref("default", tmp_path, enabled=False)})
        assert migration._fallback_active_agent_id(cfg, "gone") == "default"

    def test_all_disabled_without_default_picks_first_other(self, tmp_path):
        cfg = _config(
            {
                "a1": _ref("a1", tmp_path, enabled=False),
                "a2": _ref("a2", tmp_path, enabled=False),
            },
        )
        assert migration._fallback_active_agent_id(cfg, "gone") == "a1"

    def test_excluded_agent_is_never_returned(self, tmp_path):
        cfg = _config({"only": _ref("only", tmp_path)})
        assert migration._fallback_active_agent_id(cfg, "only") == "default"

    def test_empty_profiles_returns_default(self):
        assert migration._fallback_active_agent_id(_config({}), "gone") == (
            "default"
        )


# ---------------------------------------------------------------------------
# _apply_legacy_qa_disable_for_migration
# ---------------------------------------------------------------------------


class TestApplyLegacyQaDisable:
    def test_missing_legacy_profile_is_a_noop(self, tmp_path):
        cfg = _config({"default": _ref("default", tmp_path)}, active="default")
        migration._apply_legacy_qa_disable_for_migration(cfg)
        assert cfg.agents.active_agent == "default"
        assert LEGACY_QA_AGENT_ID not in cfg.agents.profiles

    def test_active_agent_moves_off_the_legacy_profile(self, tmp_path):
        cfg = _config(
            {
                LEGACY_QA_AGENT_ID: _ref(LEGACY_QA_AGENT_ID, tmp_path),
                "default": _ref("default", tmp_path),
            },
            active=LEGACY_QA_AGENT_ID,
        )

        migration._apply_legacy_qa_disable_for_migration(cfg)

        assert cfg.agents.active_agent == "default"
        assert cfg.agents.profiles[LEGACY_QA_AGENT_ID].enabled is False

    def test_already_disabled_legacy_profile_stays_disabled(self, tmp_path):
        legacy_ref = _ref(LEGACY_QA_AGENT_ID, tmp_path, enabled=False)
        cfg = _config({LEGACY_QA_AGENT_ID: legacy_ref}, active="default")

        migration._apply_legacy_qa_disable_for_migration(cfg)

        assert cfg.agents.profiles[LEGACY_QA_AGENT_ID].enabled is False
        assert cfg.agents.active_agent == "default"

    def test_inactive_legacy_profile_is_disabled_but_active_untouched(
        self,
        tmp_path,
    ):
        cfg = _config(
            {
                LEGACY_QA_AGENT_ID: _ref(LEGACY_QA_AGENT_ID, tmp_path),
                "default": _ref("default", tmp_path),
            },
            active="default",
        )

        migration._apply_legacy_qa_disable_for_migration(cfg)

        assert cfg.agents.active_agent == "default"
        assert cfg.agents.profiles[LEGACY_QA_AGENT_ID].enabled is False


# ---------------------------------------------------------------------------
# _do_ensure_qa_agent
# ---------------------------------------------------------------------------


@pytest.fixture()
def qa_env(tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    (wd / "workspaces").mkdir(parents=True)
    monkeypatch.setattr(migration, "WORKING_DIR", str(wd))
    saved_configs = []
    saved_agents = []
    initialized = []
    monkeypatch.setattr(
        migration,
        "save_config",
        saved_configs.append,
    )
    monkeypatch.setattr(
        migration,
        "save_agent_config",
        lambda agent_id, agent_config: saved_agents.append(agent_id),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.agents._initialize_agent_workspace",
        lambda ws, skill_names, md_template_id: initialized.append(
            (Path(ws), list(skill_names), md_template_id),
        ),
    )
    return wd, saved_configs, saved_agents, initialized


class TestDoEnsureQaAgent:
    def test_creates_the_builtin_slot_and_moves_active_agent_off_legacy(
        self,
        qa_env,
        monkeypatch,
    ):
        wd, saved_configs, saved_agents, initialized = qa_env
        cfg = _config(
            {LEGACY_QA_AGENT_ID: _ref(LEGACY_QA_AGENT_ID, wd / "legacy_ws")},
            active=LEGACY_QA_AGENT_ID,
        )
        monkeypatch.setattr(migration, "load_config", lambda: cfg)

        migration._do_ensure_qa_agent()

        canonical = wd / "workspaces" / BUILTIN_QA_AGENT_ID
        assert canonical.is_dir()
        # the two json files a workspace needs are seeded on creation
        assert (canonical / "chats.json").is_file()
        assert (canonical / "jobs.json").is_file()
        assert saved_agents == [BUILTIN_QA_AGENT_ID]
        assert len(saved_configs) == 1
        assert BUILTIN_QA_AGENT_ID in cfg.agents.profiles
        assert cfg.agents.active_agent == BUILTIN_QA_AGENT_ID
        assert cfg.agents.profiles[LEGACY_QA_AGENT_ID].enabled is False
        assert len(initialized) == 1
        workspace, skill_names, template_id = initialized[0]
        assert workspace == canonical
        assert template_id == "qa"
        assert skill_names, "builtin QA must be seeded with skills"

    def test_skips_creation_when_another_agent_owns_the_path(
        self,
        qa_env,
        monkeypatch,
    ):
        wd, saved_configs, saved_agents, initialized = qa_env
        canonical = wd / "workspaces" / BUILTIN_QA_AGENT_ID
        canonical.mkdir(parents=True)
        cfg = _config({"alice": _ref("alice", canonical)}, active="alice")
        monkeypatch.setattr(migration, "load_config", lambda: cfg)

        migration._do_ensure_qa_agent()

        # nothing was claimed: alice keeps her agent.json
        assert saved_configs == []
        assert saved_agents == []
        assert initialized == []
        assert BUILTIN_QA_AGENT_ID not in cfg.agents.profiles
        assert cfg.agents.active_agent == "alice"

    def test_existing_builtin_profile_is_a_noop(self, qa_env, monkeypatch):
        wd, saved_configs, saved_agents, initialized = qa_env
        existing = wd / "existing_qa"
        cfg = _config(
            {BUILTIN_QA_AGENT_ID: _ref(BUILTIN_QA_AGENT_ID, existing)},
            active=BUILTIN_QA_AGENT_ID,
        )
        monkeypatch.setattr(migration, "load_config", lambda: cfg)

        migration._do_ensure_qa_agent()

        assert saved_configs == []
        assert saved_agents == []
        assert initialized == []
        # the workspace json files are still ensured for an existing profile
        assert (existing / "chats.json").is_file()

    def test_existing_profile_with_a_custom_workspace_is_respected(
        self,
        qa_env,
        monkeypatch,
    ):
        wd, saved_configs, _saved_agents, _initialized = qa_env
        custom = wd / "user" / "my_qa"
        cfg = _config(
            {BUILTIN_QA_AGENT_ID: _ref(BUILTIN_QA_AGENT_ID, custom)},
            active=BUILTIN_QA_AGENT_ID,
        )
        monkeypatch.setattr(migration, "load_config", lambda: cfg)

        migration._do_ensure_qa_agent()

        assert saved_configs == []
        assert custom.is_dir()
        assert not (wd / "workspaces" / BUILTIN_QA_AGENT_ID).exists()

    def test_wrapper_swallows_failures(self, monkeypatch):
        def boom():
            raise RuntimeError("qa init failed")

        monkeypatch.setattr(migration, "_do_ensure_qa_agent", boom)
        migration.ensure_qa_agent_exists()  # must not raise


# ---------------------------------------------------------------------------
# _do_ensure_default_agent / _do_migrate_legacy_workspace failure legs
# ---------------------------------------------------------------------------


class TestDefaultAgentLegs:
    def test_blank_active_agent_is_filled_in(self, tmp_path, monkeypatch):
        wd = tmp_path / "wd"
        (wd / "workspaces").mkdir(parents=True)
        monkeypatch.setattr(migration, "WORKING_DIR", str(wd))
        cfg = _config({}, active="")
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        saved = []
        monkeypatch.setattr(
            migration,
            "save_config",
            saved.append,
        )
        monkeypatch.setattr(
            migration,
            "save_agent_config",
            lambda agent_id, agent_config: None,
        )

        migration._do_ensure_default_agent()

        assert cfg.agents.active_agent == "default"
        assert len(saved) == 1

    def test_non_blank_active_agent_is_left_alone(self, tmp_path, monkeypatch):
        wd = tmp_path / "wd"
        (wd / "workspaces").mkdir(parents=True)
        monkeypatch.setattr(migration, "WORKING_DIR", str(wd))
        cfg = _config({}, active="chosen")
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        monkeypatch.setattr(
            migration,
            "save_config",
            lambda c: None,
        )
        monkeypatch.setattr(
            migration,
            "save_agent_config",
            lambda agent_id, agent_config: None,
        )

        migration._do_ensure_default_agent()

        assert cfg.agents.active_agent == "chosen"

    def test_agent_config_write_failure_cleans_up_and_reraises(
        self,
        tmp_path,
        monkeypatch,
    ):
        wd = tmp_path / "wd"
        default_ws = wd / "workspaces" / "default"
        default_ws.mkdir(parents=True)
        # a directory where agent.json must land makes the atomic rename fail
        (default_ws / "agent.json").mkdir()
        monkeypatch.setattr(migration, "WORKING_DIR", str(wd))
        cfg = _config({})
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        saved = []
        monkeypatch.setattr(
            migration,
            "save_config",
            saved.append,
        )

        with pytest.raises(OSError):
            migration._do_migrate_legacy_workspace()

        # the partial temp file is removed and config is never persisted
        assert not (default_ws / "agent.json.tmp").exists()
        assert saved == []
        assert (default_ws / "agent.json").is_dir()
