# -*- coding: utf-8 -*-
"""Unit tests for skill_system.store gap paths.

Covers skill-name normalization and path-safety guards, the bounded
SKILL.md frontmatter reader with encoding fallback, JSON manifest I/O
helpers, pool automation read/write/copy round trips, requirements and
emoji extraction, conflict-name suggestion, zip extraction and import,
and the skill-content validation/render helpers.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import io
import json
import zipfile

import pytest

from qwenpaw.agents.skill_system.store import (
    PoolSkillAutomation,
    _create_files_from_tree,
    _directory_tree,
    _extract_emoji_from_metadata,
    _extract_requirements,
    _read_json_unlocked,
    _safe_child_path,
    classify_pool_skill_source,
    compute_skill_md_hash,
    copy_pool_skill_automation,
    extract_version,
    get_skill_mtime,
    get_workspace_skills_dir,
    import_skill_dir,
    normalize_pool_manifest_payload,
    normalize_skill_dir_name,
    read_pool_skill_automation,
    read_skill_frontmatter_from_dir,
    render_skill_md,
    safe_skill_dir,
    suggest_conflict_name,
    validate_skill_content,
    workspace_skill_name_conflict,
    write_json_atomic,
    write_pool_skill_automation,
)
from qwenpaw.exceptions import SkillsError


SKILL_MD = """---
name: demo
description: A demo skill
---

Body text.
"""


# ---------------------------------------------------------------------------
# normalize_skill_dir_name / safe_skill_dir / _safe_child_path
# ---------------------------------------------------------------------------


class TestNameAndPathSafety:
    @pytest.mark.parametrize("bad", ["", "   ", ".", ".."])
    def test_rejects_empty_or_dot_names(self, bad):
        with pytest.raises(SkillsError):
            normalize_skill_dir_name(bad)

    def test_rejects_control_characters(self):
        with pytest.raises(SkillsError):
            normalize_skill_dir_name("bad\x01name")

    def test_rejects_path_separators(self):
        with pytest.raises(SkillsError):
            normalize_skill_dir_name("a/b")
        with pytest.raises(SkillsError):
            normalize_skill_dir_name("a\\b")

    def test_strips_whitespace(self):
        assert normalize_skill_dir_name("  skill  ") == "skill"

    def test_safe_skill_dir_resolves_inside_base(self, tmp_path):
        result = safe_skill_dir(tmp_path, "demo")
        assert result == (tmp_path / "demo").resolve()

    def test_safe_skill_dir_rejects_bad_name(self, tmp_path):
        with pytest.raises(SkillsError):
            safe_skill_dir(tmp_path, "..")

    def test_safe_child_path_ok(self, tmp_path):
        result = _safe_child_path(tmp_path, "sub/file.txt")
        assert result == (tmp_path / "sub" / "file.txt").resolve()

    def test_safe_child_path_rejects_empty(self, tmp_path):
        with pytest.raises(SkillsError):
            _safe_child_path(tmp_path, "")

    def test_safe_child_path_rejects_absolute(self, tmp_path):
        with pytest.raises(SkillsError):
            _safe_child_path(tmp_path, "/etc/passwd")

    def test_safe_child_path_rejects_traversal(self, tmp_path):
        with pytest.raises(SkillsError):
            _safe_child_path(tmp_path, "../../escape")

    def test_safe_child_path_normalizes_backslashes(self, tmp_path):
        result = _safe_child_path(tmp_path, "a\\b.txt")
        assert result == (tmp_path / "a" / "b.txt").resolve()


# ---------------------------------------------------------------------------
# get_workspace_skills_dir (legacy rename)
# ---------------------------------------------------------------------------


class TestWorkspaceSkillsDir:
    def test_prefers_existing_skills_dir(self, tmp_path):
        (tmp_path / "skills").mkdir()
        (tmp_path / "skill").mkdir()
        assert get_workspace_skills_dir(tmp_path) == tmp_path / "skills"

    def test_renames_legacy_skill_dir(self, tmp_path):
        (tmp_path / "skill").mkdir()
        result = get_workspace_skills_dir(tmp_path)
        assert result == tmp_path / "skills"
        assert (tmp_path / "skills").exists()
        assert not (tmp_path / "skill").exists()

    def test_returns_preferred_when_neither_exists(self, tmp_path):
        assert get_workspace_skills_dir(tmp_path) == tmp_path / "skills"


# ---------------------------------------------------------------------------
# read_skill_frontmatter_from_dir (bounded reader + fallbacks)
# ---------------------------------------------------------------------------


class TestReadSkillFrontmatter:
    def test_reads_yaml_header(self, tmp_path):
        skill = tmp_path / "demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        post = read_skill_frontmatter_from_dir(skill)
        assert post["name"] == "demo"
        assert post["description"] == "A demo skill"

    def test_missing_file_returns_fallback(self, tmp_path):
        skill = tmp_path / "demo"
        skill.mkdir()
        post = read_skill_frontmatter_from_dir(skill, "demo")
        assert post == {"name": "demo", "description": ""}

    def test_no_frontmatter_returns_fallback(self, tmp_path):
        skill = tmp_path / "demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "plain markdown, no header",
            encoding="utf-8",
        )
        post = read_skill_frontmatter_from_dir(skill)
        assert post == {"name": "demo", "description": ""}

    def test_utf8_bom_header_is_accepted(self, tmp_path):
        skill = tmp_path / "demo"
        skill.mkdir()
        content = "\ufeff" + SKILL_MD
        (skill / "SKILL.md").write_bytes(content.encode("utf-8-sig"))
        post = read_skill_frontmatter_from_dir(skill)
        assert post["name"] == "demo"

    def test_gbk_encoded_header_falls_back_through_encodings(self, tmp_path):
        skill = tmp_path / "demo"
        skill.mkdir()
        gbk_content = "---\nname: 中文技能\ndescription: 描述\n---\n正文"
        (skill / "SKILL.md").write_bytes(gbk_content.encode("gbk"))
        post = read_skill_frontmatter_from_dir(skill)
        # Some encoding in the fallback chain must decode the header.
        assert post.get("name")


# ---------------------------------------------------------------------------
# mtime / hash helpers
# ---------------------------------------------------------------------------


class TestMtimeAndHash:
    def test_mtime_empty_on_missing_dir(self, tmp_path):
        assert get_skill_mtime(tmp_path / "ghost") == ""

    def test_mtime_iso_zulu_on_existing_dir(self, tmp_path):
        skill = tmp_path / "demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        result = get_skill_mtime(skill)
        assert result.endswith("Z")

    def test_hash_sha256_of_content(self, tmp_path):
        skill = tmp_path / "demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        digest = compute_skill_md_hash(skill)
        assert len(digest) == 64

    def test_hash_empty_when_missing(self, tmp_path):
        assert compute_skill_md_hash(tmp_path / "ghost") == ""


# ---------------------------------------------------------------------------
# extract_version / emoji / requirements extraction
# ---------------------------------------------------------------------------


class TestMetadataExtraction:
    def test_version_from_top_level(self):
        assert extract_version({"version": "1.2"}) == "1.2"

    def test_version_from_metadata(self):
        post = {"metadata": {"version": "2.0"}}
        assert extract_version(post) == "2.0"

    def test_version_from_builtin_key(self):
        post = {"metadata": {"builtin_skill_version": "3.1"}}
        assert extract_version(post) == "3.1"

    def test_version_empty_when_absent(self):
        assert extract_version({}) == ""

    def test_emoji_from_qwenpaw_metadata(self):
        metadata = {"qwenpaw": {"emoji": "🚀"}}
        assert _extract_emoji_from_metadata(metadata) == "🚀"

    def test_emoji_empty_for_non_dict(self):
        assert _extract_emoji_from_metadata("not-a-dict") == ""
        assert _extract_emoji_from_metadata({"qwenpaw": "x"}) == ""

    def test_requirements_from_namespace(self):
        post = {
            "metadata": {
                "qwenpaw": {"requires": {"bins": ["git"], "env": ["KEY"]}},
            },
        }
        req = _extract_requirements(post)
        assert req.require_bins == ["git"]
        assert req.require_envs == ["KEY"]

    def test_requirements_list_form(self):
        post = {"requires": ["ffmpeg", "pandoc"]}
        req = _extract_requirements(post)
        assert req.require_bins == ["ffmpeg", "pandoc"]
        assert req.require_envs == []

    def test_requirements_garbage_falls_back_empty(self):
        post = {"requires": 12345}
        req = _extract_requirements(post)
        assert req.require_bins == []
        assert req.require_envs == []


# ---------------------------------------------------------------------------
# pool automation read / write / copy
# ---------------------------------------------------------------------------


class TestPoolAutomation:
    def test_read_non_dict_returns_defaults(self):
        automation = read_pool_skill_automation(None)
        assert automation.auto_update is False
        assert automation.auto_sync is False

    def test_read_legacy_flat_fields(self):
        entry = {
            "auto_update": True,
            "auto_update_targets": ["ws1", "ws1", "ws2"],
            "auto_update_synced_hash": "abc",
        }
        automation = read_pool_skill_automation(entry)
        # Legacy flat auto_update maps to auto_sync, dedup keeps order.
        assert automation.auto_sync is True
        assert automation.auto_sync_targets == ("ws1", "ws2")
        assert automation.auto_sync_synced_hash == "abc"

    def test_read_canonical_builtin_entry(self):
        entry = {
            "source": "builtin",
            "automation": {
                "auto_update": {"enabled": True},
                "auto_sync": {
                    "enabled": True,
                    "targets": ["ws"],
                    "synced_hash": "h1",
                },
            },
        }
        automation = read_pool_skill_automation(entry)
        assert automation.auto_update is True
        assert automation.auto_sync is True
        assert automation.auto_sync_targets == ("ws",)
        assert automation.auto_sync_synced_hash == "h1"

    def test_read_canonical_custom_entry_ignores_auto_update(self):
        entry = {
            "source": "customized",
            "automation": {"auto_update": {"enabled": True}},
        }
        automation = read_pool_skill_automation(entry)
        assert automation.auto_update is False

    def test_read_malformed_automation_returns_defaults(self):
        entry = {"automation": "garbage"}
        automation = read_pool_skill_automation(entry)
        assert automation == PoolSkillAutomation()

    def test_write_sets_canonical_and_strips_legacy(self):
        entry = {
            "auto_update": True,
            "auto_update_targets": ["ws"],
            "auto_update_synced_hash": "old",
        }
        settings = PoolSkillAutomation(
            auto_sync=True,
            auto_sync_targets=("ws2",),
            auto_sync_synced_hash="new",
        )
        changed = write_pool_skill_automation(entry, settings)
        assert changed is True
        assert "auto_update" not in entry
        assert entry["automation"]["auto_sync"]["enabled"] is True
        assert entry["automation"]["auto_sync"]["targets"] == ["ws2"]
        assert entry["automation"]["auto_sync"]["synced_hash"] == "new"

    def test_write_builtin_keeps_auto_update_flag(self):
        entry = {"source": "builtin"}
        settings = PoolSkillAutomation(auto_update=True)
        write_pool_skill_automation(entry, settings)
        assert entry["automation"]["auto_update"]["enabled"] is True

    def test_write_unchanged_returns_false(self):
        entry = {
            "automation": {
                "auto_sync": {"enabled": False},
            },
        }
        settings = PoolSkillAutomation(auto_sync=False)
        changed = write_pool_skill_automation(entry, settings)
        assert changed is False

    def test_copy_transfers_settings(self):
        source = {
            "automation": {
                "auto_sync": {"enabled": True, "synced_hash": "hh"},
            },
        }
        target: dict = {}
        copy_pool_skill_automation(source, target)
        assert target["automation"]["auto_sync"]["enabled"] is True
        assert target["automation"]["auto_sync"]["synced_hash"] == "hh"


# ---------------------------------------------------------------------------
# normalize_pool_manifest_payload / classify_pool_skill_source
# ---------------------------------------------------------------------------


class TestPoolManifestNormalize:
    def test_rejects_unknown_schema(self):
        payload = {"schema_version": "other", "skills": {}}
        assert normalize_pool_manifest_payload(payload) is False

    def test_adds_missing_schema(self):
        payload = {"skills": {}}
        assert normalize_pool_manifest_payload(payload) is True
        assert payload["schema_version"] == "skill-pool-manifest.v1"

    def test_non_dict_skills_keeps_schema_change_only(self):
        payload = {"skills": []}
        result = normalize_pool_manifest_payload(payload)
        assert result is True

    def test_legacy_entry_gets_canonicalized(self):
        payload = {
            "skills": {
                "demo": {
                    "auto_update": True,
                    "auto_update_targets": ["ws"],
                },
            },
        }
        changed = normalize_pool_manifest_payload(payload)
        assert changed is True
        entry = payload["skills"]["demo"]
        assert "auto_update" not in entry
        assert entry["automation"]["auto_sync"]["enabled"] is True

    def test_classify_preserves_existing_builtin(self, tmp_path):
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        existing = {"source": "builtin"}
        source, changed = classify_pool_skill_source(
            "demo",
            skill_dir,
            existing,
            ["demo"],
        )
        assert (source, changed) == ("builtin", False)

    def test_classify_non_builtin_is_customized(self, tmp_path):
        skill_dir = tmp_path / "mine"
        skill_dir.mkdir()
        source, _ = classify_pool_skill_source(
            "mine",
            skill_dir,
            {},
            ["demo"],
        )
        assert source == "customized"

    def test_classify_builtin_with_version_is_builtin(self, tmp_path):
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\nmetadata:\n"
            "  builtin_skill_version: 1.0\n---\nbody",
            encoding="utf-8",
        )
        source, _ = classify_pool_skill_source(
            "demo",
            skill_dir,
            {},
            ["demo"],
        )
        assert source == "builtin"

    def test_classify_builtin_without_version_is_customized(self, tmp_path):
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        source, _ = classify_pool_skill_source(
            "demo",
            skill_dir,
            {},
            ["demo"],
        )
        assert source == "customized"


# ---------------------------------------------------------------------------
# JSON I/O helpers
# ---------------------------------------------------------------------------


class TestJsonIo:
    def test_read_missing_returns_default_copy(self, tmp_path):
        default = {"a": 1}
        result = _read_json_unlocked(tmp_path / "nope.json", default)
        assert result == default
        assert result is not default

    def test_read_malformed_returns_default(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{broken", encoding="utf-8")
        result = _read_json_unlocked(path, {"fallback": True})
        assert result == {"fallback": True}

    def test_read_valid_json(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text(json.dumps({"x": 2}), encoding="utf-8")
        assert _read_json_unlocked(path, {}) == {"x": 2}

    def test_write_json_atomic_bumps_version(self, tmp_path):
        path = tmp_path / "nested" / "manifest.json"
        write_json_atomic(path, {"skills": {}})
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["version"] > 0
        assert payload["skills"] == {}


# ---------------------------------------------------------------------------
# conflict naming
# ---------------------------------------------------------------------------


class TestConflictNaming:
    def test_suggest_strips_old_timestamp_suffix(self):
        suggestion = suggest_conflict_name("demo-20240101010101")
        assert suggestion.startswith("demo-")
        assert "20240101010101" not in suggestion

    def test_suggest_avoids_taken_names(self):
        suggestion = suggest_conflict_name("demo", {"demo"})
        assert suggestion != "demo"
        assert suggestion.startswith("demo-")

    def test_workspace_no_conflict_when_absent(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        assert workspace_skill_name_conflict(tmp_path, "new-skill") is None

    def test_workspace_conflict_returns_rename(self, tmp_path):
        skills = tmp_path / "skills"
        (skills / "dup").mkdir(parents=True)
        result = workspace_skill_name_conflict(tmp_path, "dup")
        assert result is not None
        name, suggestion = result
        assert name == "dup"
        assert suggestion.startswith("dup-")


# ---------------------------------------------------------------------------
# directory tree / create files from tree
# ---------------------------------------------------------------------------


class TestDirectoryTreeRoundTrip:
    def test_tree_missing_dir_is_empty(self, tmp_path):
        assert _directory_tree(tmp_path / "ghost") == {}

    def test_tree_describes_files_and_dirs(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.md").write_text("y", encoding="utf-8")
        tree = _directory_tree(tmp_path)
        assert tree == {"a.txt": None, "sub": {"b.md": None}}

    def test_create_files_from_tree_round_trip(self, tmp_path):
        tree = {"a.txt": "hello", "sub": {"b.md": None}}
        _create_files_from_tree(tmp_path, tree)
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
        assert (tmp_path / "sub" / "b.md").read_text(encoding="utf-8") == ""

    def test_create_files_rejects_invalid_value(self, tmp_path):
        with pytest.raises(SkillsError):
            _create_files_from_tree(tmp_path, {"bad": 123})

    def test_create_files_rejects_traversal_name(self, tmp_path):
        with pytest.raises(SkillsError):
            _create_files_from_tree(tmp_path, {"../escape.txt": "x"})


# ---------------------------------------------------------------------------
# validate / render / import
# ---------------------------------------------------------------------------


class TestValidateRenderImport:
    def test_validate_ok(self):
        name, description = validate_skill_content(SKILL_MD)
        assert name == "demo"
        assert description == "A demo skill"

    def test_validate_requires_name_and_description(self):
        with pytest.raises(SkillsError):
            validate_skill_content("---\nname: demo\n---\nbody")

    def test_validate_rejects_non_dict_metadata(self):
        content = "---\nname: demo\ndescription: d\nmetadata: 5\n---\n"
        with pytest.raises(SkillsError):
            validate_skill_content(content)

    def test_render_includes_frontmatter(self):
        rendered = render_skill_md(
            proposed_name="new",
            description="desc",
            body="body text",
        )
        assert rendered.startswith("---")
        assert "name: new" in rendered
        assert "body text" in rendered

    def test_import_copies_valid_skill(self, tmp_path):
        src = tmp_path / "src" / "demo"
        src.mkdir(parents=True)
        (src / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        target_root = tmp_path / "target"
        target_root.mkdir()

        ok = import_skill_dir(src, target_root, "demo")

        assert ok is True
        assert (target_root / "demo" / "SKILL.md").exists()

    def test_import_rejects_skill_without_frontmatter(self, tmp_path):
        src = tmp_path / "src" / "demo"
        src.mkdir(parents=True)
        (src / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
        target_root = tmp_path / "target"
        target_root.mkdir()

        assert import_skill_dir(src, target_root, "demo") is False

    def test_import_refuses_existing_target(self, tmp_path):
        src = tmp_path / "src" / "demo"
        src.mkdir(parents=True)
        (src / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        target_root = tmp_path / "target"
        (target_root / "demo").mkdir(parents=True)

        assert import_skill_dir(src, target_root, "demo") is False


# ---------------------------------------------------------------------------
# zip extraction
# ---------------------------------------------------------------------------


def _build_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class TestExtractZipSkills:
    def test_single_skill_at_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from qwenpaw.agents.skill_system import store

        data = _build_zip({"SKILL.md": SKILL_MD})
        extracted_dir, found = store.extract_zip_skills(data)
        try:
            assert len(found) == 1
            assert found[0][1] == "demo"
        finally:
            import shutil

            shutil.rmtree(extracted_dir, ignore_errors=True)

    def test_multi_skill_dirs(self, tmp_path):
        from qwenpaw.agents.skill_system import store

        data = _build_zip(
            {
                "one/SKILL.md": SKILL_MD,
                "two/SKILL.md": SKILL_MD.replace("demo", "other"),
            },
        )
        extracted_dir, found = store.extract_zip_skills(data)
        try:
            names = {name for _, name in found}
            assert len(found) == 2
            assert {"demo", "other"} == names
        finally:
            import shutil

            shutil.rmtree(extracted_dir, ignore_errors=True)

    def test_non_zip_raises(self):
        from qwenpaw.agents.skill_system import store

        with pytest.raises(SkillsError):
            store.extract_zip_skills(b"not a zip file")

    def test_zip_without_skills_raises(self, tmp_path):
        from qwenpaw.agents.skill_system import store

        data = _build_zip({"readme.txt": "nothing here"})
        with pytest.raises(SkillsError):
            store.extract_zip_skills(data)
