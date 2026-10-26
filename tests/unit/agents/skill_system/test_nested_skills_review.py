# -*- coding: utf-8 -*-
"""Regression tests for the PR #8178 review findings.

Each test reproduces one reviewer scenario against the nested (categorised)
skill layout:

1. rename overwrote ``cat/target`` despite ``overwrite=False``
2. reading ``a/foo`` but saving the shadowed ``foo``; ``rel_path`` dropped
3. ZIP import silently replaced an enabled skill identity
4. ZIP ``target_name`` / ``rename_map`` and rename-save separated the name
   from the path (category segment was rewritten)
5. delete followed a symlinked category outside the skills root

6a/6b (pool metadata rel_path and primary-pool detection) are covered by the
pool tests at the end.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import pool_service as skill_pool_service
from qwenpaw.agents.skill_system import registry as skill_registry
from qwenpaw.agents.skill_system.pool_service import SkillPoolService
from qwenpaw.agents.skill_system.registry import (
    reconcile_workspace_manifest,
    resolve_workspace_skill_dir,
)
from qwenpaw.agents.skill_system.store import (
    is_primary_pool_skill_dir,
    resolve_pool_skill_dir,
)
from qwenpaw.agents.skill_system.workspace_service import SkillService
from qwenpaw.exceptions import SkillsError


def _skill_md(name: str, body: str = "body") -> str:
    return (
        f"---\nname: {name}\ndescription: test skill {name}\n---\n\n{body}\n"
    )


def _mk_skill(root: Path, rel: str, name: str, body: str = "body") -> Path:
    directory = root / rel
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        _skill_md(name, body),
        encoding="utf-8",
    )
    return directory


def _zip(payload: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in payload.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _read_manifest(workspace_dir: Path) -> dict:
    return json.loads(
        (workspace_dir / "skill.json").read_text(encoding="utf-8"),
    )


def _write_manifest(workspace_dir: Path, skills: dict) -> None:
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "workspace-skill-manifest.v1",
                "version": 0,
                "skills": skills,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Claim 1 — rename must check the actual nested destination
# ---------------------------------------------------------------------------


def test_rename_conflict_checks_nested_target(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "cat/source", "source", body="SOURCE")
    _mk_skill(skills, "cat/target", "target", body="TARGET")
    reconcile_workspace_manifest(tmp_path)

    result = SkillService(tmp_path).save_skill(
        skill_name="source",
        content=_skill_md("source", "EDITED"),
        target_name="target",
        overwrite=False,
    )

    assert result["success"] is False
    assert result["reason"] == "conflict"
    # The existing nested target must not be silently replaced.
    assert "TARGET" in (skills / "cat/target" / "SKILL.md").read_text(
        encoding="utf-8",
    )
    assert (skills / "cat/source" / "SKILL.md").exists()


def test_rename_ignores_flat_dir_that_is_not_a_skill(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "cat/source", "source", body="SOURCE")
    (skills / "target").mkdir(parents=True)  # empty, not a skill
    reconcile_workspace_manifest(tmp_path)

    result = SkillService(tmp_path).save_skill(
        skill_name="source",
        content=_skill_md("source", "EDITED"),
        target_name="target",
        overwrite=False,
    )

    assert result["success"] is True
    assert result["mode"] == "rename"
    assert (skills / "cat/target" / "SKILL.md").exists()
    # The unrelated flat directory is left untouched.
    assert (skills / "target").is_dir()
    assert not (skills / "target" / "SKILL.md").exists()
    entry = _read_manifest(tmp_path)["skills"]["target"]
    assert entry["rel_path"] == "cat/target"


# ---------------------------------------------------------------------------
# Claim 2 — save must target the manifest copy and keep rel_path
# ---------------------------------------------------------------------------


def test_save_edits_manifest_copy_not_shadowed_flat_copy(
    tmp_path: Path,
) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "a/foo", "foo", body="A-COPY")
    _mk_skill(skills, "foo", "foo", body="FLAT")
    reconcile_workspace_manifest(tmp_path)
    assert _read_manifest(tmp_path)["skills"]["foo"]["rel_path"] == "a/foo"

    resolved = resolve_workspace_skill_dir(tmp_path, "foo")
    assert resolved is not None
    assert resolved.parent.name == "a"

    result = SkillService(tmp_path).save_skill(
        skill_name="foo",
        content=_skill_md("foo", "EDITED"),
    )

    assert result["success"] is True
    assert result["mode"] == "edit"
    assert "EDITED" in (skills / "a/foo" / "SKILL.md").read_text(
        encoding="utf-8",
    )
    assert "FLAT" in (skills / "foo" / "SKILL.md").read_text(
        encoding="utf-8",
    )
    # rel_path must survive the save so runtime resolution stays on a/foo.
    assert _read_manifest(tmp_path)["skills"]["foo"]["rel_path"] == "a/foo"
    assert resolve_workspace_skill_dir(tmp_path, "foo").parent.name == "a"


# ---------------------------------------------------------------------------
# Claim 3 — ZIP import must not replace an existing skill identity
# ---------------------------------------------------------------------------


def test_import_conflicts_with_enabled_identity_at_other_path(
    tmp_path: Path,
) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "z/foo", "foo", body="ENABLED")
    manifest = reconcile_workspace_manifest(tmp_path)
    manifest["skills"]["foo"]["enabled"] = True
    _write_manifest(tmp_path, manifest["skills"])

    data = _zip({"a/foo/SKILL.md": _skill_md("foo", "NEW")})
    result = SkillService(tmp_path).import_from_zip(data, enable=False)

    assert result["imported"] == []
    assert result["count"] == 0
    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["skill_name"] == "foo"
    assert conflict["selected"] == "a/foo"
    assert conflict["shadowed"] == "z/foo"
    assert not (skills / "a/foo").exists()

    entry = _read_manifest(tmp_path)["skills"]["foo"]
    assert entry["enabled"] is True
    assert entry["rel_path"] == "z/foo"


def test_import_writes_rel_path_when_identity_is_free(tmp_path: Path) -> None:
    data = _zip({"cat/foo/SKILL.md": _skill_md("foo", "NEW")})

    result = SkillService(tmp_path).import_from_zip(data)

    assert result["imported"] == ["foo"]
    assert (tmp_path / "skills" / "cat/foo" / "SKILL.md").exists()
    entry = _read_manifest(tmp_path)["skills"]["foo"]
    assert entry["rel_path"] == "cat/foo"


# ---------------------------------------------------------------------------
# Claim 4a — ZIP target_name / rename_map must move the destination leaf
# ---------------------------------------------------------------------------


def test_zip_target_name_moves_nested_destination_leaf(
    tmp_path: Path,
) -> None:
    data = _zip({"cat-x/foo/SKILL.md": _skill_md("foo")})

    result = SkillService(tmp_path).import_from_zip(data, target_name="bar")

    assert result["imported"] == ["bar"]
    assert (tmp_path / "skills/cat-x/bar/SKILL.md").exists()
    assert not (tmp_path / "skills/cat-x/foo").exists()
    assert not (tmp_path / "skills/bar").exists()
    entry = _read_manifest(tmp_path)["skills"]["bar"]
    assert entry["rel_path"] == "cat-x/bar"
    assert SkillService(tmp_path).enable_skill("bar")["success"] is True


def test_zip_rename_map_moves_nested_destination_leaf(tmp_path: Path) -> None:
    data = _zip({"cat-x/foo/SKILL.md": _skill_md("foo")})

    result = SkillService(tmp_path).import_from_zip(
        data,
        rename_map={"foo": "bar"},
    )

    assert result["imported"] == ["bar"]
    assert (tmp_path / "skills/cat-x/bar/SKILL.md").exists()
    assert not (tmp_path / "skills/cat-x/foo").exists()
    entry = _read_manifest(tmp_path)["skills"]["bar"]
    assert entry["rel_path"] == "cat-x/bar"


def test_zip_rename_map_accepts_source_specific_rel_path_key(
    tmp_path: Path,
) -> None:
    data = _zip(
        {
            "cat-x/foo/SKILL.md": _skill_md("foo"),
            "cat-y/foo/SKILL.md": _skill_md("foo"),
        },
    )

    result = SkillService(tmp_path).import_from_zip(
        data,
        rename_map={"cat-x/foo": "bar", "cat-y/foo": "baz"},
    )

    assert sorted(result["imported"]) == ["bar", "baz"]
    assert (tmp_path / "skills/cat-x/bar/SKILL.md").exists()
    assert (tmp_path / "skills/cat-y/baz/SKILL.md").exists()
    manifest = _read_manifest(tmp_path)["skills"]
    assert manifest["bar"]["rel_path"] == "cat-x/bar"
    assert manifest["baz"]["rel_path"] == "cat-y/baz"


# ---------------------------------------------------------------------------
# Claim 4b — rename-save must replace only the leaf segment
# ---------------------------------------------------------------------------


def test_rename_save_preserves_category_segment(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "foo-tools/foo", "foo", body="OLD")
    reconcile_workspace_manifest(tmp_path)

    result = SkillService(tmp_path).save_skill(
        skill_name="foo",
        content=_skill_md("bar", "NEW"),
        target_name="bar",
    )

    assert result["success"] is True
    assert result["mode"] == "rename"
    assert (skills / "foo-tools/bar/SKILL.md").exists()
    assert not (skills / "bar-tools/foo").exists()
    assert not (skills / "foo-tools/foo").exists()
    entry = _read_manifest(tmp_path)["skills"]["bar"]
    assert entry["rel_path"] == "foo-tools/bar"


# ---------------------------------------------------------------------------
# Claim 5 — delete must not escape the skills root through a symlink
# ---------------------------------------------------------------------------


def test_delete_refuses_symlinked_category_outside_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    _mk_skill(outside, "foo", "foo", body="OUTSIDE")

    workspace = tmp_path / "workspace"
    skills = workspace / "skills"
    skills.mkdir(parents=True)
    try:
        os.symlink(outside, skills / "cat", target_is_directory=True)
    except OSError:  # pragma: no cover - platform without symlink support
        pytest.skip("symlinks are not supported on this platform")

    reconcile_workspace_manifest(workspace)
    assert (
        _read_manifest(workspace)["skills"]["foo"]["rel_path"] == "cat/foo"
    )

    service = SkillService(workspace)
    with pytest.raises(SkillsError):
        service.delete_skill("foo")

    # The out-of-root directory and its manifest entry survive.
    assert (outside / "foo" / "SKILL.md").exists()
    assert "foo" in _read_manifest(workspace)["skills"]


def test_save_refuses_symlinked_category_outside_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    _mk_skill(outside, "foo", "foo", body="OUTSIDE")

    workspace = tmp_path / "workspace"
    skills = workspace / "skills"
    skills.mkdir(parents=True)
    try:
        os.symlink(outside, skills / "cat", target_is_directory=True)
    except OSError:  # pragma: no cover - platform without symlink support
        pytest.skip("symlinks are not supported on this platform")

    reconcile_workspace_manifest(workspace)
    service = SkillService(workspace)

    with pytest.raises(SkillsError):
        service.save_skill(
            skill_name="foo",
            content=_skill_md("foo", "EDITED"),
        )

    # Same boundary policy as delete: write must not reach outside the root.
    assert "OUTSIDE" in (outside / "foo" / "SKILL.md").read_text(
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Claim 6a/6b — pool metadata and primary-pool detection for nested skills
# ---------------------------------------------------------------------------


@pytest.fixture()
def pool_env(tmp_path, monkeypatch):
    """Isolated pool rooted in tmp_path; builtin import and scans stubbed."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        skill_registry,
        "import_builtin_skills",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        skill_pool_service,
        "scan_skill_dir_or_raise",
        lambda *args, **kwargs: None,
    )
    service = SkillPoolService()
    return service, tmp_path / "skill_pool", tmp_path / "workspaces" / "ws"


def test_pool_import_records_nested_rel_path_and_metadata(
    pool_env,
) -> None:
    service, pool_dir, _workspace = pool_env
    data = _zip({"cat/foo/SKILL.md": _skill_md("foo")})

    result = service.import_from_zip(data)

    assert result["imported"] == ["foo"]
    assert (pool_dir / "cat/foo" / "SKILL.md").exists()
    manifest = json.loads(
        (pool_dir / "skill.json").read_text(encoding="utf-8"),
    )
    entry = manifest["skills"]["foo"]
    assert entry["rel_path"] == "cat/foo"
    assert entry["external"] is False
    assert entry["description"] == "test skill foo"


def test_primary_pool_detection_accepts_nested_dirs(
    pool_env,
    tmp_path,
) -> None:
    _service, pool_dir, _workspace = pool_env
    nested = _mk_skill(pool_dir, "cat/foo", "foo")
    external = _mk_skill(tmp_path / "extra-root", "foo", "foo")

    assert is_primary_pool_skill_dir(nested) is True
    assert is_primary_pool_skill_dir(external) is False


def test_pool_rename_keeps_workspace_category_segment(
    pool_env,
    monkeypatch,
) -> None:
    service, pool_dir, workspace = pool_env
    # The pool has already been renamed: new name lives in the same category.
    _mk_skill(pool_dir, "foo-tools/bar", "bar")
    skill_registry.reconcile_pool_manifest()

    workspace_skills = workspace / "skills"
    _mk_skill(workspace_skills, "foo-tools/foo", "foo", body="OLD")
    _write_manifest(
        workspace,
        {
            "foo": {
                "enabled": False,
                "source": "customized",
                "rel_path": "foo-tools/foo",
            },
        },
    )
    monkeypatch.setattr(
        skill_pool_service,
        "list_workspaces",
        lambda: [
            {
                "agent_id": "agent_x",
                "agent_name": "Agent X",
                "workspace_dir": str(workspace),
            },
        ],
    )

    result = service.rename_in_workspaces("foo", "bar")

    assert result["renamed"] == ["agent_x"]
    assert (workspace_skills / "foo-tools/bar/SKILL.md").exists()
    assert not (workspace_skills / "foo-tools/foo").exists()
    assert not (workspace_skills / "bar-tools").exists()
    entry = _read_manifest(workspace)["skills"]["bar"]
    assert entry["rel_path"] == "foo-tools/bar"


def test_pool_resolution_prefers_manifest_rel_path(pool_env) -> None:
    service, pool_dir, _workspace = pool_env
    # Two same-leaf copies; the manifest picks b/dup, not the first on disk.
    _mk_skill(pool_dir, "a/dup", "dup", body="A")
    _mk_skill(pool_dir, "b/dup", "dup", body="B")
    skill_registry.reconcile_pool_manifest()
    manifest = json.loads(
        (pool_dir / "skill.json").read_text(encoding="utf-8"),
    )
    manifest["skills"]["dup"]["rel_path"] = "b/dup"
    (pool_dir / "skill.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    assert resolve_pool_skill_dir("dup") == pool_dir / "b/dup"
