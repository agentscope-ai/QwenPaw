# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
# pylint: disable=use-implicit-booleaness-not-comparison
"""Unit tests for the packaged-builtin sync layer of the skill registry.

Covers packaged builtin discovery, the pool sync status, the builtin
update notice (added / missing / updated / removed plus its
fingerprint), the staged single-builtin update with its rollback, the
opt-in batch auto-update, and the import request validation.

Every packaged builtin is faked through ``get_builtin_skills_dir`` so
no shipped skill file is read or written, and ``WORKING_DIR`` is
pointed at ``tmp_path`` so the real skill pool is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import registry as reg
from qwenpaw.agents.skill_system.pool_service import refresh_pool_automation
from qwenpaw.exceptions import SkillsError
from qwenpaw.utils.file_snapshot_cache import get_file_snapshot_cache


def _packaged_variant(
    root: Path,
    name: str,
    language: str,
    version: str,
    *,
    body: str = "",
) -> Path:
    """Create one fake packaged builtin and return its directory."""
    skill_dir = root / f"{name}-{language}"
    skill_dir.mkdir(parents=True, exist_ok=True)
    text = body or f"body {name} {language} {version}"
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {name} {language}\n"
        "metadata:\n"
        f'  builtin_skill_version: "{version}"\n'
        "---\n"
        f"{text}\n",
        encoding="utf-8",
    )
    return skill_dir


def _manifest_path() -> Path:
    return reg.get_skill_pool_dir() / "skill.json"


def _read_manifest() -> dict:
    return json.loads(_manifest_path().read_text(encoding="utf-8"))


def _write_manifest(payload: dict) -> None:
    """Write the pool manifest and drop any cached snapshot of it."""
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    get_file_snapshot_cache().invalidate(path)


def _opt_in_auto_update(entry: dict) -> dict:
    entry["automation"] = {
        "auto_update": {"enabled": True},
        "auto_sync": {"enabled": False},
    }
    return entry


@pytest.fixture(autouse=True)
def packaged_root(tmp_path, monkeypatch):
    """Isolate WORKING_DIR, the packaged builtins and the caches."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    root = tmp_path / "packaged"
    root.mkdir()
    monkeypatch.setattr(reg, "get_builtin_skills_dir", lambda: root)
    reg._builtin_cache.clear()
    yield root
    reg._builtin_cache.clear()


# ---------------------------------------------------------------------------
# packaged builtin discovery
# ---------------------------------------------------------------------------


class TestPackagedBuiltinDiscovery:
    def test_entries_without_skill_md_or_language_suffix_are_skipped(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        # OS/cache artifacts and directories are ignored by name rule.
        (packaged_root / ".DS_Store").mkdir()
        (packaged_root / "__pycache__").mkdir()
        # Language-suffixed directory without a SKILL.md.
        (packaged_root / "gamma-en").mkdir()
        # SKILL.md present but the directory name carries no language.
        plain = packaged_root / "delta"
        plain.mkdir()
        (plain / "SKILL.md").write_text("body", encoding="utf-8")

        assert sorted(reg._get_packaged_builtin_registry()) == ["alpha"]

    def test_missing_packaged_root_yields_empty_registry(self, monkeypatch):
        monkeypatch.setattr(
            reg,
            "get_builtin_skills_dir",
            lambda: Path("/nonexistent/packaged"),
        )
        assert reg._get_packaged_builtin_registry() == {}
        assert reg.get_packaged_builtin_versions() == {}

    def test_refresh_forces_a_rescan(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        assert sorted(reg._get_packaged_builtin_registry()) == ["alpha"]

        _packaged_variant(packaged_root, "beta", "en", "1.0")
        assert sorted(reg._get_packaged_builtin_registry()) == ["alpha"]

        reg.refresh_packaged_builtin_registry()
        assert sorted(reg._get_packaged_builtin_registry()) == [
            "alpha",
            "beta",
        ]

    def test_packaged_versions_use_the_preferred_language(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        _packaged_variant(packaged_root, "alpha", "zh", "2.0")
        _packaged_variant(packaged_root, "beta", "en", "1.5")
        assert reg.get_packaged_builtin_versions() == {
            "alpha": "2.0",
            "beta": "1.5",
        }

    def test_resolve_builtin_skill_dir_honours_explicit_language(
        self,
        packaged_root,
    ):
        zh_dir = _packaged_variant(packaged_root, "alpha", "zh", "1.0")
        en_dir = _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.set_builtin_skill_language_preference("en")

        assert reg.resolve_builtin_skill_dir(
            "alpha",
            preferred_language="zh",
        ) == str(zh_dir)
        assert reg.resolve_builtin_skill_dir("alpha") == str(en_dir)
        # The language suffix of an alias name is not honoured here; it is
        # resolved by the import-request normalisation instead.
        assert reg.resolve_builtin_skill_dir("alpha-zh") == str(en_dir)
        assert reg.resolve_builtin_skill_dir("nope") is None

    def test_import_candidates_report_pool_state(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _packaged_variant(packaged_root, "alpha", "zh", "1.0")
        before = reg.list_builtin_import_candidates()
        assert [
            (item["name"], item["status"], item["available_languages"])
            for item in before
        ] == [("alpha", "missing", ["en", "zh"])]

        reg.import_builtin_skills()
        after = reg.list_builtin_import_candidates()
        assert [
            (
                item["name"],
                item["status"],
                item["current_language"],
                item["current_version_text"],
            )
            for item in after
        ] == [("alpha", "current", "en", "1.0")]

    def test_empty_registry_short_circuits_candidates(self, monkeypatch):
        monkeypatch.setattr(
            reg,
            "get_builtin_skills_dir",
            lambda: Path("/nonexistent/packaged"),
        )
        assert reg.list_builtin_import_candidates() == []


# ---------------------------------------------------------------------------
# pool builtin sync status
# ---------------------------------------------------------------------------


class TestPoolBuiltinSyncStatus:
    def test_empty_packaged_registry_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            reg,
            "get_builtin_skills_dir",
            lambda: Path("/nonexistent/packaged"),
        )
        assert reg.get_pool_builtin_sync_status() == {}

    def test_synced_then_outdated_after_a_version_bump(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _packaged_variant(packaged_root, "beta", "en", "1.0")
        reg.import_builtin_skills()
        assert reg.get_pool_builtin_sync_status() == {
            "alpha": {
                "sync_status": "synced",
                "latest_version_text": "",
                "available_languages": ["en"],
            },
            "beta": {
                "sync_status": "synced",
                "latest_version_text": "",
                "available_languages": ["en"],
            },
        }

        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()
        assert reg.get_pool_builtin_sync_status() == {
            "alpha": {
                "sync_status": "outdated",
                "latest_version_text": "2.0",
                "available_languages": ["en"],
            },
            "beta": {
                "sync_status": "synced",
                "latest_version_text": "",
                "available_languages": ["en"],
            },
        }

    def test_customized_pool_entries_are_not_reported(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        assert (
            reg.get_pool_builtin_sync_status(
                pool_skills={"alpha": {"source": "customized"}},
            )
            == {}
        )

    def test_builtin_missing_from_the_package_is_removed(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()
        manifest = _read_manifest()
        manifest["skills"]["gamma"] = {
            "name": "gamma",
            "source": "builtin",
            "version_text": "3.0",
        }
        _write_manifest(manifest)

        status = reg.get_pool_builtin_sync_status()
        assert status["gamma"] == {
            f"sync_status": f"removed",
            "latest_version_text": "",
            "available_languages": [],
        }
        assert status["alpha"]["sync_status"] == "synced"

    @pytest.mark.parametrize(
        (f"current", f"packaged"),
        [(f"1.0", f"2.0"), (f"2.0", f"1.0")],
    )
    @pytest.mark.parametrize(f"source_name_only", [False, True])
    def test_removed_language_preserves_the_installed_copy(
        self,
        packaged_root,
        current,
        packaged,
        source_name_only,
    ):
        removed_dir = _packaged_variant(
            packaged_root,
            f"alpha",
            f"zh",
            current,
        )
        _packaged_variant(packaged_root, f"alpha", f"en", packaged)
        reg.import_builtin_skills(
            [{f"skill_name": f"alpha", f"language": f"zh"}],
        )
        manifest = _read_manifest()
        if source_name_only:
            del manifest[f"skills"][f"alpha"][f"builtin_language"]
            _write_manifest(manifest)
        pool_md = reg.get_skill_pool_dir() / f"alpha" / f"SKILL.md"
        installed_content = pool_md.read_bytes()
        (removed_dir / f"SKILL.md").unlink()
        removed_dir.rmdir()
        reg.refresh_packaged_builtin_registry()

        reg.ensure_skill_pool_initialized()

        assert _read_manifest() == manifest
        assert reg.get_pool_builtin_sync_status()[f"alpha"] == {
            f"sync_status": f"removed",
            f"latest_version_text": f"",
            f"available_languages": [f"en"],
        }
        candidate = reg.list_builtin_import_candidates()[0]
        assert candidate[f"current_language"] == f"zh"
        assert candidate[f"status"] == f"removed"
        assert candidate[f"languages"][f"en"][f"status"] == f"removed"
        notice = reg.get_pool_builtin_update_notice()
        assert notice[f"added"] == []
        assert notice[f"updated"] == []
        assert [item[f"name"] for item in notice[f"removed"]] == [f"alpha"]
        assert notice[f"actionable_skill_names"] == []
        assert notice[f"total_changes"] == 1

        result = reg.import_builtin_skills(
            [{f"skill_name": f"alpha", f"language": f"en"}],
        )

        assert result[f"conflicts"][0][f"status"] == f"language_switch"
        assert pool_md.read_bytes() == installed_content

    @pytest.mark.parametrize(
        (f"current", f"packaged", f"expected"),
        [
            (f"1.0", f"2.0", f"outdated"),
            (f"1.10", f"1.9", f"synced"),
            (f"2.0", f"1.0", f"synced"),
            (f"1.0", f"1.0.0", f"synced"),
            (f"v1.0", f"1.0", f"synced"),
            (f"1.0rc1", f"1.0", f"outdated"),
            (f"1.0", f"1.0rc1", f"synced"),
            (f"custom", f"1.0", f"conflict"),
            (f"", f"1.0", f"conflict"),
            (f"custom", f"custom", f"synced"),
        ],
    )
    def test_version_status_agrees_with_import_candidates(
        self,
        packaged_root,
        current,
        packaged,
        expected,
    ):
        _packaged_variant(packaged_root, f"alpha", f"en", packaged)
        _write_manifest(
            {
                f"builtin_skill_names": [f"alpha"],
                f"skills": {
                    f"alpha": {
                        f"name": f"alpha",
                        f"source": f"builtin",
                        f"builtin_language": f"en",
                        f"version_text": current,
                    },
                },
            },
        )

        sync = reg.get_pool_builtin_sync_status()[f"alpha"]
        candidate = reg.list_builtin_import_candidates()[0]

        assert sync[f"sync_status"] == expected
        assert candidate[f"status"] == (
            f"current" if expected == f"synced" else expected
        )
        assert sync[f"latest_version_text"] == (
            packaged if expected == f"outdated" else f""
        )
        notice = reg.get_pool_builtin_update_notice()
        assert bool(notice[f"updated"]) == (expected != f"synced")


# ---------------------------------------------------------------------------
# builtin update notice
# ---------------------------------------------------------------------------


class TestPoolBuiltinUpdateNotice:
    def test_added_until_reviewed_then_quiet(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _packaged_variant(packaged_root, "beta", "en", "1.0")

        notice = reg.get_pool_builtin_update_notice()
        assert notice["has_updates"] is True
        assert notice["total_changes"] == 2
        assert notice["actionable_skill_names"] == ["alpha", "beta"]
        assert [item["name"] for item in notice["added"]] == [
            "alpha",
            "beta",
        ]
        assert len(notice["fingerprint"]) == 64
        assert notice["fingerprint"] == (
            reg.get_pool_builtin_update_notice()["fingerprint"]
        )

        reg.import_builtin_skills()
        quiet = reg.get_pool_builtin_update_notice()
        assert quiet["has_updates"] is False
        assert quiet["total_changes"] == 0
        assert quiet["actionable_skill_names"] == []
        assert quiet["fingerprint"] == ""

    def test_missing_when_the_pool_copy_is_dropped(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()
        manifest = _read_manifest()
        del manifest["skills"]["alpha"]
        _write_manifest(manifest)

        notice = reg.get_pool_builtin_update_notice()
        assert notice["total_changes"] == 1
        assert [
            (item["name"], item["status"]) for item in notice["missing"]
        ] == [("alpha", "missing")]
        assert notice["actionable_skill_names"] == ["alpha"]

    def test_updated_after_a_version_bump(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()

        notice = reg.get_pool_builtin_update_notice()
        assert notice["total_changes"] == 1
        assert [
            (
                item["name"],
                item["status"],
                item["version_text"],
                item["current_version_text"],
            )
            for item in notice["updated"]
        ] == [("alpha", "outdated", "2.0", "1.0")]

    def test_removed_names_are_not_actionable(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()
        manifest = _read_manifest()
        manifest["builtin_skill_names"] = ["alpha", "gamma"]
        manifest["skills"]["gamma"] = {
            "name": "gamma",
            "source": "builtin",
            "version_text": "3.0",
            "description": "gone",
        }
        _write_manifest(manifest)

        notice = reg.get_pool_builtin_update_notice()
        assert [
            (
                item["name"],
                item["current_version_text"],
                item["current_source"],
            )
            for item in notice["removed"]
        ] == [("gamma", "3.0", "builtin")]
        # ``removed`` is informational only: nothing can be imported for a
        # builtin the package no longer ships.
        assert notice["actionable_skill_names"] == []
        assert notice["total_changes"] == 1

    def test_removed_name_without_a_pool_copy_is_skipped(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()
        manifest = _read_manifest()
        manifest["builtin_skill_names"] = ["alpha", "ghost"]
        _write_manifest(manifest)

        notice = reg.get_pool_builtin_update_notice()
        assert notice["removed"] == []
        assert notice["total_changes"] == 0

    def test_fingerprint_tracks_the_payload(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()
        first = reg.get_pool_builtin_update_notice()["fingerprint"]
        assert first == ""

        manifest = _read_manifest()
        manifest["skills"]["alpha"]["version_text"] = "0.0.1"
        _write_manifest(manifest)
        second = reg.get_pool_builtin_update_notice()["fingerprint"]
        assert second != first
        assert len(second) == 64


# ---------------------------------------------------------------------------
# update_single_builtin
# ---------------------------------------------------------------------------


class TestUpdateSingleBuiltin:
    def test_replaces_the_pool_copy_and_keeps_bookkeeping(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _packaged_variant(packaged_root, "alpha", "zh", "2.0", body="中文")
        reg.import_builtin_skills(
            [{"skill_name": "alpha", "language": "en"}],
        )
        manifest = _read_manifest()
        manifest["skills"]["alpha"]["config"] = {"k": "v"}
        manifest["skills"]["alpha"]["tags"] = ["t1"]
        _opt_in_auto_update(manifest["skills"]["alpha"])
        _write_manifest(manifest)

        entry = reg.update_single_builtin("alpha", language="zh")
        assert entry["builtin_language"] == "zh"
        assert entry["builtin_source_name"] == "alpha-zh"
        assert entry["version_text"] == "2.0"
        assert entry["config"] == {"k": "v"}
        assert entry["tags"] == ["t1"]
        assert entry["automation"]["auto_update"] == {"enabled": True}

        pool_dir = reg.get_skill_pool_dir()
        assert (pool_dir / "alpha" / "SKILL.md").read_text(
            encoding="utf-8",
        ).strip().splitlines()[-1] == "中文"
        # The staged transaction directory must not survive the update.
        assert sorted(path.name for path in pool_dir.iterdir()) == [
            ".skill.json.lock",
            "alpha",
            "skill.json",
        ]

    def test_unknown_builtin_raises(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        with pytest.raises(SkillsError, match="not a builtin skill"):
            reg.update_single_builtin("ghost")

    def test_customized_pool_entry_raises(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _write_manifest(
            {
                "schema_version": "skill-pool-manifest.v1",
                "version": 1,
                "skills": {
                    "alpha": {
                        "name": "alpha",
                        "source": "customized",
                        "version_text": "9.9",
                    },
                },
                "builtin_skill_names": ["alpha"],
            },
        )
        with pytest.raises(SkillsError, match="not a builtin pool skill"):
            reg.update_single_builtin("alpha")

    def test_language_the_package_lacks_raises(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "zh", "1.0")
        _write_manifest(
            {
                "schema_version": "skill-pool-manifest.v1",
                "version": 1,
                "skills": {
                    "alpha": {
                        "name": "alpha",
                        "source": "builtin",
                        "version_text": "1.0",
                        "builtin_language": "zh",
                    },
                },
                "builtin_skill_names": ["alpha"],
            },
        )
        with pytest.raises(SkillsError, match="does not support language"):
            reg.update_single_builtin("alpha", language="en")

    def test_unparsable_language_falls_back_to_the_preference(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.import_builtin_skills()
        reg.set_builtin_skill_language_preference("en")
        entry = reg.update_single_builtin("alpha", language="fr")
        assert entry["builtin_language"] == "en"

    def test_alias_name_is_canonicalised(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "zh", "2.0")
        _write_manifest(
            {
                "schema_version": "skill-pool-manifest.v1",
                "version": 1,
                "skills": {
                    "alpha": {
                        "name": "alpha",
                        "source": "builtin",
                        "version_text": "1.0",
                        "builtin_language": "zh",
                    },
                },
                "builtin_skill_names": ["alpha"],
            },
        )
        entry = reg.update_single_builtin("alpha-zh")
        assert entry["name"] == "alpha"
        assert entry["builtin_source_name"] == "alpha-zh"

    def test_manifest_failure_restores_the_previous_pool_copy(
        self,
        packaged_root,
        monkeypatch,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0", body="old")
        reg.import_builtin_skills()
        pool_dir = reg.get_skill_pool_dir()
        skill_md = pool_dir / "alpha" / "SKILL.md"
        before = skill_md.read_text(encoding="utf-8")

        _packaged_variant(packaged_root, "alpha", "en", "2.0", body="new")
        reg.refresh_packaged_builtin_registry()

        def _fail_after_staging(mutator):
            payload = _read_manifest()
            # Runs the real staging swap, then loses the manifest write.
            mutator(payload)
            raise RuntimeError("manifest write failed")

        original = reg.mutate_pool_manifest
        monkeypatch.setattr(reg, "mutate_pool_manifest", _fail_after_staging)
        try:
            with pytest.raises(RuntimeError, match="manifest write failed"):
                reg.update_single_builtin("alpha")
        finally:
            # ``monkeypatch.undo()`` is deliberately not used: it would also
            # revert the fixture's WORKING_DIR patch and expose the real one.
            monkeypatch.setattr(reg, "mutate_pool_manifest", original)

        assert skill_md.read_text(encoding="utf-8") == before
        assert sorted(path.name for path in pool_dir.iterdir()) == [
            ".skill.json.lock",
            "alpha",
            "skill.json",
        ]

    def test_entry_reclassified_mid_update_raises(
        self,
        packaged_root,
        monkeypatch,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()

        def _racy(mutator):
            return mutator(
                {
                    "schema_version": "skill-pool-manifest.v1",
                    "version": 1,
                    "skills": {
                        "alpha": {
                            "name": "alpha",
                            "source": "customized",
                        },
                    },
                    "builtin_skill_names": [],
                },
            )

        monkeypatch.setattr(reg, "mutate_pool_manifest", _racy)
        with pytest.raises(SkillsError, match="not a builtin pool skill"):
            reg.update_single_builtin("alpha")


# ---------------------------------------------------------------------------
# auto_update_builtin_skills
# ---------------------------------------------------------------------------


class TestAutoUpdateBuiltinSkills:
    def _imported_pool(self, packaged_root, version="1.0"):
        _packaged_variant(packaged_root, "alpha", "en", version)
        reg.import_builtin_skills()
        return _read_manifest()

    def test_nothing_is_checked_without_an_opt_in(self, packaged_root):
        self._imported_pool(packaged_root)
        assert reg.auto_update_builtin_skills() == {
            "updated": [],
            "failed": [],
            "checked": 0,
        }
        assert reg.auto_update_builtin_skills("alpha") == {
            "updated": [],
            "failed": [],
            "checked": 0,
        }

    def test_opted_in_entry_is_updated_once(self, packaged_root):
        manifest = self._imported_pool(packaged_root)
        _opt_in_auto_update(manifest["skills"]["alpha"])
        _write_manifest(manifest)

        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()

        assert reg.auto_update_builtin_skills() == {
            "updated": [
                {
                    "skill": "alpha",
                    "language": "en",
                    "from_version": "1.0",
                    "to_version": "2.0",
                },
            ],
            "failed": [],
            "checked": 1,
        }
        assert reg.auto_update_builtin_skills() == {
            "updated": [],
            "failed": [],
            "checked": 1,
        }
        assert _read_manifest()["skills"]["alpha"]["version_text"] == "2.0"

    @pytest.mark.parametrize("packaged_version", ["1.0", "2.0.0", "legacy"])
    def test_refresh_keeps_pool_copy_without_a_newer_version(
        self,
        packaged_root,
        packaged_version,
    ):
        manifest = self._imported_pool(packaged_root, version="2.0")
        _opt_in_auto_update(manifest["skills"]["alpha"])
        _write_manifest(manifest)
        pool_md = reg.get_skill_pool_dir() / "alpha" / "SKILL.md"
        original = pool_md.read_bytes()
        _packaged_variant(
            packaged_root,
            "alpha",
            "en",
            packaged_version,
            body="replacement",
        )

        result = refresh_pool_automation()

        assert result["checked"]["auto_update"] == 1
        assert result["pool_updated"] == []
        assert result["pool_failed"] == []
        assert pool_md.read_bytes() == original
        assert _read_manifest()["skills"]["alpha"]["version_text"] == "2.0"

    def test_auto_update_rechecks_version_at_write(
        self,
        packaged_root,
        monkeypatch,
    ):
        manifest = self._imported_pool(packaged_root)
        _opt_in_auto_update(manifest["skills"]["alpha"])
        _write_manifest(manifest)
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()
        pool_md = reg.get_skill_pool_dir() / "alpha" / "SKILL.md"
        newer_content = pool_md.read_bytes().replace(b"1.0", b"3.0")
        mutate = reg.mutate_pool_manifest

        def _after_newer_install(mutator):
            pool_md.write_bytes(newer_content)
            manifest["skills"]["alpha"]["version_text"] = "3.0"
            _write_manifest(manifest)
            return mutate(mutator)

        monkeypatch.setattr(reg, "mutate_pool_manifest", _after_newer_install)

        assert reg.auto_update_builtin_skills() == {
            "updated": [],
            "failed": [],
            "checked": 1,
        }
        assert pool_md.read_bytes() == newer_content
        assert _read_manifest()["skills"]["alpha"]["version_text"] == "3.0"

    def test_name_filter_limits_the_batch(self, packaged_root):
        manifest = self._imported_pool(packaged_root)
        _opt_in_auto_update(manifest["skills"]["alpha"])
        _write_manifest(manifest)
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()

        assert reg.auto_update_builtin_skills("other") == {
            "updated": [],
            "failed": [],
            "checked": 0,
        }
        assert len(reg.auto_update_builtin_skills("alpha")["updated"]) == 1

    def test_configured_language_the_package_lacks_is_reported(
        self,
        packaged_root,
    ):
        manifest = self._imported_pool(packaged_root)
        entry = manifest["skills"]["alpha"]
        entry["builtin_language"] = "fr"
        _opt_in_auto_update(entry)
        _write_manifest(manifest)

        result = reg.auto_update_builtin_skills()
        assert result["failed"] == [
            {
                "skill": "alpha",
                "language": "fr",
                "from_version": "1.0",
                "to_version": "",
                "reason": "language_unavailable",
            },
        ]
        assert result["checked"] == 1
        assert result["updated"] == []

    def test_one_failure_does_not_abort_the_batch(
        self,
        packaged_root,
        monkeypatch,
    ):
        manifest = self._imported_pool(packaged_root)
        _opt_in_auto_update(manifest["skills"]["alpha"])
        _write_manifest(manifest)
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()

        def _boom(*_args, **_kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(reg, "update_single_builtin", _boom)
        result = reg.auto_update_builtin_skills()
        assert result["failed"][0]["reason"] == "update_failed"
        assert result["failed"][0]["detail"] == "disk full"
        assert result["failed"][0]["to_version"] == "2.0"
        assert result["updated"] == []
        # The pool copy is untouched, so the batch stays retryable.
        assert _read_manifest()["skills"]["alpha"]["version_text"] == "1.0"

    def test_non_builtin_entries_are_never_auto_updated(
        self,
        packaged_root,
    ):
        manifest = self._imported_pool(packaged_root)
        manifest["skills"]["alpha"]["source"] = "customized"
        _opt_in_auto_update(manifest["skills"]["alpha"])
        _write_manifest(manifest)
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()

        assert reg.auto_update_builtin_skills()["checked"] == 0

    def test_legacy_flat_auto_update_is_not_an_opt_in(self, packaged_root):
        manifest = self._imported_pool(packaged_root)
        manifest["skills"]["alpha"] = {
            "name": "alpha",
            "source": "builtin",
            "version_text": "1.0",
            # Released flat spelling: it maps onto auto-sync, not onto the
            # builtin auto-update opt-in.
            "auto_update": True,
        }
        _write_manifest(manifest)
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.refresh_packaged_builtin_registry()

        assert reg.auto_update_builtin_skills()["checked"] == 0
        assert _read_manifest()["skills"]["alpha"]["version_text"] == "1.0"

    def test_builtin_without_packaged_variants_is_skipped(
        self,
        packaged_root,
    ):
        manifest = self._imported_pool(packaged_root)
        _opt_in_auto_update(manifest["skills"]["alpha"])
        manifest["skills"]["zeta"] = {
            "name": "zeta",
            "source": "builtin",
            "version_text": "1.0",
        }
        _opt_in_auto_update(manifest["skills"]["zeta"])
        _write_manifest(manifest)

        assert reg.auto_update_builtin_skills() == {
            "updated": [],
            "failed": [],
            "checked": 1,
        }


# ---------------------------------------------------------------------------
# import_builtin_skills
# ---------------------------------------------------------------------------


class TestImportBuiltinSkills:
    def test_default_request_imports_every_packaged_builtin(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _packaged_variant(packaged_root, "zhonly", "zh", "3.0")
        result = reg.import_builtin_skills()
        assert result["imported"] == ["alpha", "zhonly"]
        assert result["conflicts"] == []
        assert _read_manifest()["builtin_skill_names"] == [
            "alpha",
            "zhonly",
        ]
        # The zh-only builtin is imported in its own language.
        assert _read_manifest()["skills"]["zhonly"]["builtin_language"] == "zh"

    def test_unknown_skill_raises(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        with pytest.raises(SkillsError, match="Unknown builtin skill"):
            reg.import_builtin_skills(
                [{"skill_name": "ghost", "language": "en"}],
            )

    def test_language_the_package_lacks_raises(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        with pytest.raises(SkillsError, match="Unsupported builtin language"):
            reg.import_builtin_skills(
                [{"skill_name": "alpha", "language": "zh"}],
            )
        # The alias spelling is rejected for the very same reason.
        with pytest.raises(SkillsError, match="Unsupported builtin language"):
            reg.import_builtin_skills([{"skill_name": "alpha-zh"}])

    def test_unparsable_language_falls_back_to_the_preference(
        self,
        packaged_root,
    ):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.set_builtin_skill_language_preference("en")
        result = reg.import_builtin_skills(
            [{"skill_name": "alpha", "language": "fr"}],
        )
        assert result["imported"] == ["alpha"]
        assert _read_manifest()["skills"]["alpha"]["builtin_language"] == "en"

    def test_empty_skill_name_is_reported_as_unknown(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        with pytest.raises(SkillsError, match="Unknown builtin skill"):
            reg.import_builtin_skills([{"language": "en"}])

    def test_source_name_spelling_is_accepted(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        assert reg.import_builtin_skills(
            [{"source_name": "alpha-en"}],
        )[
            "imported"
        ] == ["alpha"]
        assert reg.import_builtin_skills(
            [{"source_name": "alpha-en"}],
        )[
            "unchanged"
        ] == ["alpha"]

    def test_reimport_of_the_same_variant_is_unchanged(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        reg.import_builtin_skills()
        assert reg.import_builtin_skills(
            [{"skill_name": "alpha", "language": "en"}],
        ) == {
            "imported": [],
            "updated": [],
            "unchanged": ["alpha"],
            "conflicts": [],
        }

    def test_same_language_downgrade_needs_confirmation(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.import_builtin_skills()
        pool_md = reg.get_skill_pool_dir() / "alpha" / "SKILL.md"
        original = pool_md.read_bytes()
        source = _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _packaged_variant(packaged_root, "beta", "en", "1.0")
        reg.refresh_packaged_builtin_registry()
        selection = [
            {"skill_name": "beta", "language": "en"},
            {"skill_name": "alpha", "language": "en"},
        ]
        original_manifest = _read_manifest()

        assert reg.list_builtin_import_candidates()[0]["status"] == "current"
        blocked = reg.import_builtin_skills(selection)

        assert blocked["imported"] == []
        assert blocked["updated"] == []
        (conflict,) = blocked["conflicts"]
        assert conflict["status"] == "conflict"
        assert conflict["current_version_text"] == "2.0"
        assert conflict["source_version_text"] == "1.0"
        assert pool_md.read_bytes() == original
        assert _read_manifest() == original_manifest
        assert not (reg.get_skill_pool_dir() / "beta").exists()

        forced = reg.import_builtin_skills(selection, overwrite_conflicts=True)

        assert forced["imported"] == ["beta"]
        assert forced["updated"] == ["alpha"]
        assert pool_md.read_bytes() == (source / "SKILL.md").read_bytes()
        assert _read_manifest()["skills"]["alpha"]["version_text"] == "1.0"

    def test_equivalent_version_is_unchanged(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "2.0")
        reg.import_builtin_skills()
        pool_md = reg.get_skill_pool_dir() / "alpha" / "SKILL.md"
        original = pool_md.read_bytes()
        original_manifest = _read_manifest()
        _packaged_variant(packaged_root, "alpha", "en", "2.0.0")
        reg.refresh_packaged_builtin_registry()

        result = reg.import_builtin_skills(
            [{"skill_name": "alpha", "language": "en"}],
        )

        assert result == {
            "imported": [],
            "updated": [],
            "unchanged": ["alpha"],
            "conflicts": [],
        }
        assert pool_md.read_bytes() == original
        assert _read_manifest() == original_manifest

    def test_language_switch_needs_confirmation(self, packaged_root):
        _packaged_variant(packaged_root, "alpha", "en", "1.0")
        _packaged_variant(packaged_root, "alpha", "zh", "1.0")
        reg.import_builtin_skills(
            [{"skill_name": "alpha", "language": "en"}],
        )
        result = reg.import_builtin_skills(
            [{"skill_name": "alpha", "language": "zh"}],
        )
        assert result["imported"] == []
        assert result["updated"] == []
        assert [
            (item["skill_name"], item["status"], item["current_language"])
            for item in result["conflicts"]
        ] == [("alpha", "language_switch", "en")]
        assert _read_manifest()["skills"]["alpha"]["builtin_language"] == "en"

    def test_customized_conflict_can_be_overwritten(self, packaged_root):
        _packaged_variant(packaged_root, "beta", "en", "1.0")
        reg.import_builtin_skills()
        manifest = _read_manifest()
        manifest["skills"]["beta"] = {
            "name": "beta",
            "source": "customized",
            "version_text": "0.1",
            "description": "mine",
        }
        _write_manifest(manifest)

        blocked = reg.import_builtin_skills(
            [{"skill_name": "beta", "language": "en"}],
        )
        assert [item["status"] for item in blocked["conflicts"]] == [
            "conflict",
        ]
        assert blocked["updated"] == []
        assert _read_manifest()["skills"]["beta"]["source"] == "customized"

        forced = reg.import_builtin_skills(
            [{"skill_name": "beta", "language": "en"}],
            overwrite_conflicts=True,
        )
        assert forced["updated"] == ["beta"]
        assert _read_manifest()["skills"]["beta"]["source"] == "builtin"
