# -*- coding: utf-8 -*-
"""Unit tests for backup restore staging and merge helpers.

Covers the restore staging functions (_stage_skill_pool, _stage_agents),
target probing (_restore_directory_targets), the profile merge
(_merge_profiles_into), target deduplication (_dedupe_restore_targets),
and the global config staging (_stage_global_config), which had no
direct test coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from qwenpaw.backup._ops import restore
from qwenpaw.backup._utils.constants import (
    PREFIX_CONFIG,
    PREFIX_SKILL_POOL,
    PREFIX_WORKSPACES,
)
from qwenpaw.backup.models import BackupMeta, RestoreBackupRequest


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def backup_zip(tmp_path) -> Path:
    """Create a backup zip with config, skill pool, and two agents."""
    zp = tmp_path / "backup.zip"
    meta = BackupMeta(name="test backup", version="1")
    with zipfile.ZipFile(zp, "w") as zf:
        # meta.json lives at the zip root (read_meta_from_zip contract).
        zf.writestr("meta.json", meta.model_dump_json())
        zf.writestr(
            PREFIX_CONFIG,
            json.dumps(
                {
                    "user_timezone": "Asia/Shanghai",
                    "agents": {
                        "profiles": {
                            "default": {"name": "from-backup"},
                            "other": {"name": "from-backup-other"},
                        },
                    },
                },
            ),
        )
        zf.writestr(f"{PREFIX_SKILL_POOL}skill_a/SKILL.md", "# skill a")
        zf.writestr(f"{PREFIX_WORKSPACES}default/README.md", "agent readme")
        zf.writestr(f"{PREFIX_WORKSPACES}other/README.md", "other readme")
    return zp


def _open_zip(zp: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(zp, "r")


# ---------------------------------------------------------------------------
# _zip_has_prefix
# ---------------------------------------------------------------------------


class TestZipHasPrefix:
    def test_present_prefix(self, backup_zip):
        with _open_zip(backup_zip) as zf:
            assert restore._zip_has_prefix(zf, PREFIX_CONFIG) is True
            assert restore._zip_has_prefix(zf, PREFIX_SKILL_POOL) is True
            assert restore._zip_has_prefix(zf, PREFIX_WORKSPACES) is True

    def test_absent_prefix(self, backup_zip):
        with _open_zip(backup_zip) as zf:
            assert restore._zip_has_prefix(zf, "data/nonexistent/") is False

    def test_directory_only_entries_not_counted(self, tmp_path):
        zp = tmp_path / "dirs.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("data/secrets/", "")
        with _open_zip(zp) as zf:
            assert restore._zip_has_prefix(zf, "data/secrets/") is False


# ---------------------------------------------------------------------------
# _dedupe_restore_targets
# ---------------------------------------------------------------------------


class TestDedupeRestoreTargets:
    def test_deduplicates_same_paths(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        result = restore._dedupe_restore_targets([a, a, b, b])
        assert result == [a, b]

    def test_empty_list(self):
        assert restore._dedupe_restore_targets([]) == []

    def test_nonexistent_paths_dedup_by_absolute(self, tmp_path):
        # Paths that don't exist still resolve to absolute paths for dedup.
        p = tmp_path / "missing"
        result = restore._dedupe_restore_targets([p, p])
        assert result == [p]


# ---------------------------------------------------------------------------
# _merge_profiles_into
# ---------------------------------------------------------------------------


class TestMergeProfilesInto:
    def test_backup_wins_top_level_keys(self):
        backup = {
            "user_timezone": "Asia/Shanghai",
            "agents": {"profiles": {}},
        }
        current = {"user_timezone": "UTC", "agents": {"profiles": {}}}
        merged = restore._merge_profiles_into(backup, current, set())
        assert merged["user_timezone"] == "Asia/Shanghai"

    def test_empty_restore_aids_keeps_current_profiles(self):
        """No agents being restored: profiles stay exactly as local."""
        backup = {
            "agents": {
                "profiles": {"default": {"name": "from-backup"}},
            },
        }
        current = {
            "agents": {
                "profiles": {"default": {"name": "local"}},
            },
        }
        merged = restore._merge_profiles_into(backup, current, set())
        assert merged["agents"]["profiles"]["default"]["name"] == "local"

    def test_restore_aids_overwrite_from_backup(self):
        backup = {
            "agents": {
                "profiles": {
                    "default": {"name": "from-backup"},
                    "ghost": {"name": "should-not-appear"},
                },
            },
        }
        current = {
            "agents": {
                "profiles": {
                    "default": {"name": "local"},
                    "untouched": {"name": "keep-me"},
                },
            },
        }
        merged = restore._merge_profiles_into(
            backup,
            current,
            {"default"},
        )
        profiles = merged["agents"]["profiles"]
        assert profiles["default"]["name"] == "from-backup"
        # Agents not in restore_aids keep local state.
        assert profiles["untouched"]["name"] == "keep-me"
        # Agents in backup but not restored don't appear.
        assert "ghost" not in profiles

    def test_backup_agent_not_in_current_is_inserted(self):
        backup = {
            "agents": {
                "profiles": {"new_agent": {"name": "new"}},
            },
        }
        current = {"agents": {"profiles": {}}}
        merged = restore._merge_profiles_into(
            backup,
            current,
            {"new_agent"},
        )
        assert merged["agents"]["profiles"]["new_agent"]["name"] == "new"

    def test_does_not_mutate_input_dicts(self):
        backup = {"agents": {"profiles": {"a": {"name": "b"}}}}
        current = {"agents": {"profiles": {"a": {"name": "c"}}}}
        restore._merge_profiles_into(backup, current, {"a"})
        assert current["agents"]["profiles"]["a"]["name"] == "c"

    def test_missing_agents_section_defaults_to_empty(self):
        """Backup without an agents section keeps local profiles intact."""
        backup = {"user_timezone": "UTC"}
        current = {"agents": {"profiles": {"x": {"name": "y"}}}}
        merged = restore._merge_profiles_into(backup, current, {"x"})
        assert merged["agents"]["profiles"]["x"]["name"] == "y"
        assert merged["user_timezone"] == "UTC"


# ---------------------------------------------------------------------------
# _stage_skill_pool
# ---------------------------------------------------------------------------


class TestStageSkillPool:
    def test_stages_pool_and_appends(self, backup_zip, tmp_path, monkeypatch):
        pool_dir = tmp_path / "pool"
        pool_dir.mkdir()
        staged: list[Path] = []
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.store.get_skill_pool_dir",
            lambda: pool_dir,
        )
        with _open_zip(backup_zip) as zf:
            restore._stage_skill_pool(zf, staged)
        assert staged == [pool_dir]
        # Phase-1 extraction lands in the sibling .restore_tmp staging dir.
        assert (
            pool_dir.with_name("pool.restore_tmp") / "skill_a" / "SKILL.md"
        ).exists()

    def test_missing_pool_entries_skips(self, tmp_path, monkeypatch):
        """A backup without pool entries must not wipe the existing pool."""
        zp = tmp_path / "no_pool.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("data/meta.json", "{}")
        pool_dir = tmp_path / "pool"
        pool_dir.mkdir()
        (pool_dir / "existing.txt").write_text("keep me")
        staged: list[Path] = []
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.store.get_skill_pool_dir",
            lambda: pool_dir,
        )
        with _open_zip(zp) as zf:
            restore._stage_skill_pool(zf, staged)
        assert staged == []
        assert (pool_dir / "existing.txt").exists()


# ---------------------------------------------------------------------------
# _stage_agents
# ---------------------------------------------------------------------------


class TestStageAgents:
    def test_stages_requested_agent(self, backup_zip, tmp_path):
        dst = tmp_path / "ws_default"
        dst.mkdir()
        staged: list[Path] = []
        dst_map: dict[str, Path] = {}
        new_aids: list[str] = []
        planned = {"default": (dst, False), "other": (tmp_path / "ws_o", True)}
        with _open_zip(backup_zip) as zf:
            restore._stage_agents(
                zf,
                ["default"],
                {"default", "other"},
                planned,
                staged,
                dst_map,
                new_aids,
            )
        assert staged == [dst]
        assert dst_map == {"default": dst}
        assert new_aids == []  # not new
        assert (dst.with_name("ws_default.restore_tmp") / "README.md").exists()

    def test_new_agent_tracked(self, backup_zip, tmp_path):
        dst = tmp_path / "ws_other"
        staged: list[Path] = []
        dst_map: dict[str, Path] = {}
        new_aids: list[str] = []
        planned = {"other": (dst, True)}
        with _open_zip(backup_zip) as zf:
            restore._stage_agents(
                zf,
                ["other"],
                {"other"},
                planned,
                staged,
                dst_map,
                new_aids,
            )
        assert new_aids == ["other"]
        assert dst_map == {"other": dst}

    def test_unknown_agent_skipped(self, backup_zip, tmp_path):
        staged: list[Path] = []
        dst_map: dict[str, Path] = {}
        new_aids: list[str] = []
        with _open_zip(backup_zip) as zf:
            restore._stage_agents(
                zf,
                ["ghost"],
                {"default"},
                {},
                staged,
                dst_map,
                new_aids,
            )
        assert staged == []
        assert dst_map == {}

    def test_agent_without_files_skipped(self, backup_zip, tmp_path):
        """An agent present in meta but with no workspace files is skipped
        to avoid wiping an existing workspace."""
        dst = tmp_path / "ws_empty"
        dst.mkdir()
        (dst / "existing.txt").write_text("keep")
        staged: list[Path] = []
        dst_map: dict[str, Path] = {}
        new_aids: list[str] = []
        planned = {"empty_agent": (dst, False)}
        with _open_zip(backup_zip) as zf:
            restore._stage_agents(
                zf,
                ["empty_agent"],
                {"empty_agent"},
                planned,
                staged,
                dst_map,
                new_aids,
            )
        assert staged == []
        assert (dst / "existing.txt").exists()


# ---------------------------------------------------------------------------
# _restore_directory_targets
# ---------------------------------------------------------------------------


class TestRestoreDirectoryTargets:
    def test_targets_for_full_restore(self, backup_zip, tmp_path, monkeypatch):
        pool_dir = tmp_path / "pool"
        pool_dir.mkdir()
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        monkeypatch.setattr(restore, "SECRET_DIR", secret_dir)
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.store.get_skill_pool_dir",
            lambda: pool_dir,
        )
        req = RestoreBackupRequest(
            include_secrets=False,
            include_skill_pool=True,
            include_agents=True,
            agent_ids=["default"],
        )
        ws_dst = tmp_path / "ws_default"
        ws_dst.mkdir()
        planned = {"default": (ws_dst, False)}
        with _open_zip(backup_zip) as zf:
            targets = restore._restore_directory_targets(
                zf,
                req,
                ["default"],
                {"default"},
                planned,
            )
        assert pool_dir in targets
        assert ws_dst in targets
        assert secret_dir not in targets

    def test_dedupe_targets(self, tmp_path):
        a = tmp_path / "a"
        result = restore._dedupe_restore_targets([a, a, a])
        assert result == [a]


# ---------------------------------------------------------------------------
# _stage_global_config
# ---------------------------------------------------------------------------


class TestStageGlobalConfig:
    def test_skip_when_not_requested(self, backup_zip, tmp_path):
        req = RestoreBackupRequest(include_global_config=False)
        meta = BackupMeta(name="t", version="1")
        result = restore._stage_global_config(
            zf=_open_zip(backup_zip),
            req=req,
            meta=meta,
            restore_aids=set(),
        )
        assert result is None

    def test_full_mode_copies_verbatim(
        self,
        backup_zip,
        tmp_path,
        monkeypatch,
    ):
        working = tmp_path / "working"
        working.mkdir()
        monkeypatch.setattr(restore, "WORKING_DIR", working)
        req = RestoreBackupRequest(
            include_global_config=True,
            mode="full",
            preserve_local_protected_config=False,
        )
        meta = BackupMeta(name="t", version="1", accepted_via_trust=False)
        with _open_zip(backup_zip) as zf:
            staged = restore._stage_global_config(
                zf,
                req,
                meta,
                restore_aids=set(),
            )
        assert staged is not None
        assert staged.exists()
        staged_data = json.loads(staged.read_text(encoding="utf-8"))
        assert staged_data["user_timezone"] == "Asia/Shanghai"
        # Full mode: backup profiles kept verbatim.
        assert staged_data["agents"]["profiles"]["default"]["name"] == (
            "from-backup"
        )

    def test_custom_mode_merges_local_profiles(
        self,
        backup_zip,
        tmp_path,
        monkeypatch,
    ):
        working = tmp_path / "working"
        working.mkdir()
        # Existing config on disk with a local-only agent.
        existing = working / "config.json"
        existing.write_text(
            json.dumps(
                {
                    "user_timezone": "UTC",
                    "agents": {
                        "profiles": {
                            "default": {"name": "local"},
                            "local_only": {"name": "keep"},
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(restore, "WORKING_DIR", working)
        req = RestoreBackupRequest(
            include_global_config=True,
            mode="custom",
            agent_ids=["default"],
        )
        meta = BackupMeta(name="t", version="1", accepted_via_trust=False)
        with _open_zip(backup_zip) as zf:
            staged = restore._stage_global_config(
                zf,
                req,
                meta,
                restore_aids={"default"},
            )
        staged_data = json.loads(staged.read_text(encoding="utf-8"))
        # Top-level key from backup.
        assert staged_data["user_timezone"] == "Asia/Shanghai"
        profiles = staged_data["agents"]["profiles"]
        # Restored agent overwritten from backup.
        assert profiles["default"]["name"] == "from-backup"
        # Local-only agent preserved.
        assert profiles["local_only"]["name"] == "keep"
        # Backup-only agent not restored not injected.
        assert "other" not in profiles

    def test_missing_config_in_zip_skipped(self, tmp_path, monkeypatch):
        zp = tmp_path / "no_config.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("data/meta.json", "{}")
        req = RestoreBackupRequest(include_global_config=True, mode="full")
        meta = BackupMeta(name="t", version="1")
        with _open_zip(zp) as zf:
            result = restore._stage_global_config(zf, req, meta, set())
        assert result is None


# ---------------------------------------------------------------------------
# _validate_version / _read_meta_or_missing
# ---------------------------------------------------------------------------


class TestValidateVersion:
    def test_supported_version_passes(self):
        meta = BackupMeta(name="t", version="1")
        restore._validate_version(meta)  # no exception

    def test_unsupported_version_raises(self):
        meta = BackupMeta(name="t", version="99")
        with pytest.raises(ValueError, match="Unsupported backup version"):
            restore._validate_version(meta)


class TestReadMetaOrMissing:
    def test_missing_meta_raises(self, tmp_path):
        zp = tmp_path / "empty.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("data/other.json", "{}")
        with _open_zip(zp) as zf:
            with pytest.raises(FileNotFoundError, match="Backup not found"):
                restore._read_meta_or_missing(zf, "some-backup-id")

    def test_valid_meta_parsed(self, backup_zip):
        with _open_zip(backup_zip) as zf:
            meta = restore._read_meta_or_missing(zf, "x")
        assert meta.name == "test backup"
        assert meta.version == "1"
