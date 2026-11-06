# -*- coding: utf-8 -*-
"""Same-volume staging installs (skill pool, issue #8013 item 4).

Upstream #8013 asks for the staging round-trip to stop costing a second full
copy when the stage and the workspace sit on one volume. These tests pin both
halves of that: the volume probe, and the install that renames the staged tree
into place with a plain copy as the fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import store as skill_store

_SKILL_MD = "---\nname: demo\ndescription: demo skill\n---\n# body\n"


def _write_tree(root: Path, files: int = 3) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    for index in range(files):
        (root / f"f{index}.txt").write_text(f"n{index}", encoding="utf-8")
    return root


class TestSameVolume:
    def test_siblings_report_one_volume(self, tmp_path: Path):
        left = _write_tree(tmp_path / "left")
        assert skill_store.same_volume(left, tmp_path / "right") is True

    def test_missing_path_is_probed_through_its_ancestor(self, tmp_path: Path):
        missing = tmp_path / "not" / "created" / "yet"
        assert skill_store.same_volume(tmp_path, missing) is True


class TestInstallStagedSkillDir:
    def test_renames_the_staged_tree_into_place(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = tmp_path / "workspace" / "skills" / "demo"

        def _no_copy(*_args, **_kwargs):
            raise AssertionError("same-volume install must not copy")

        monkeypatch.setattr(skill_store, "copy_skill_dir", _no_copy)
        skill_store.install_staged_skill_dir(staged, target)

        assert (target / "SKILL.md").read_text(encoding="utf-8") == _SKILL_MD
        assert sorted(p.name for p in target.iterdir()) == [
            "SKILL.md",
            "f0.txt",
            "f1.txt",
            "f2.txt",
        ]
        assert not staged.exists()

    def test_replaces_what_was_already_there(self, tmp_path: Path):
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = _write_tree(tmp_path / "workspace" / "skills" / "demo")
        (target / "stale.txt").write_text("old", encoding="utf-8")

        skill_store.install_staged_skill_dir(staged, target)

        assert not (target / "stale.txt").exists()
        assert (target / "SKILL.md").is_file()

    def test_falls_back_to_a_copy_when_the_rename_fails(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = tmp_path / "workspace" / "skills" / "demo"
        monkeypatch.setattr(
            skill_store.os,
            "rename",
            _raise_locked_error,
        )
        skill_store.install_staged_skill_dir(staged, target)

        assert (target / "SKILL.md").is_file()
        assert staged.exists()

    def test_cross_volume_install_still_copies(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = tmp_path / "workspace" / "skills" / "demo"
        monkeypatch.setattr(
            skill_store,
            "same_volume",
            lambda *_args, **_kwargs: False,
        )
        calls: list[tuple[Path, Path]] = []
        real_copy = skill_store.copy_skill_dir

        def _spy(source, destination):
            calls.append((Path(source), Path(destination)))
            real_copy(source, destination)

        monkeypatch.setattr(skill_store, "copy_skill_dir", _spy)
        skill_store.install_staged_skill_dir(staged, target)

        assert calls == [(staged, target)]
        assert (target / "SKILL.md").is_file()

    def test_a_cancelled_install_touches_nothing(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = _write_tree(tmp_path / "workspace" / "skills" / "demo")
        marker = target / "keep.txt"
        marker.write_text("original", encoding="utf-8")

        def _cancelled() -> None:
            raise _Cancelled()

        monkeypatch.setattr(skill_store, "ensure_not_cancelled", _cancelled)
        with pytest.raises(_Cancelled):
            skill_store.install_staged_skill_dir(staged, target)

        assert marker.read_text(encoding="utf-8") == "original"
        assert staged.exists()


class _Cancelled(Exception):
    """Stand-in for SkillImportCancelled, which the store never imports."""


def _raise_locked_error(*_args, **_kwargs):
    raise OSError("locked")


class TestDownloadUsesTheStagedInstall:
    def test_download_installs_the_stage_instead_of_copying_it(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """One copy (pool -> stage), then the install: no second copy."""
        from qwenpaw.agents.skill_system import pool_service as pool_module
        from qwenpaw.agents.skill_system import registry as registry_module
        from qwenpaw.agents.skill_system.pool_service import SkillPoolService

        monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
        monkeypatch.setattr(
            registry_module,
            "import_builtin_skills",
            lambda *args, **kwargs: {},
        )
        monkeypatch.setattr(
            pool_module,
            "scan_skill_dir_or_raise",
            lambda *args, **kwargs: None,
        )

        pool_dir = tmp_path / "skill_pool"
        _write_tree(pool_dir / "demo")
        (pool_dir / "skill.json").write_text(
            '{"schema_version": "skill-pool-manifest.v1", "version": 0,'
            ' "skills": {"demo": {"source": "customized"}},'
            ' "builtin_skill_names": []}',
            encoding="utf-8",
        )
        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        (workspace_dir / "skill.json").write_text(
            '{"schema_version": "workspace-skill-manifest.v1",'
            ' "version": 0, "skills": {}}',
            encoding="utf-8",
        )

        installed: list[Path] = []
        real_install = pool_module.install_staged_skill_dir

        def _spy_install(staged, target):
            installed.append(Path(target))
            real_install(staged, target)

        copies: list[Path] = []
        real_copy = pool_module.copy_skill_dir

        def _spy_copy(source, target):
            copies.append(Path(target))
            real_copy(source, target)

        monkeypatch.setattr(
            pool_module,
            "install_staged_skill_dir",
            _spy_install,
        )
        monkeypatch.setattr(pool_module, "copy_skill_dir", _spy_copy)

        result = SkillPoolService().download_to_workspace(
            "demo",
            workspace_dir,
        )

        assert result["success"] is True
        target = workspace_dir / "skills" / "demo"
        assert installed == [target]
        assert len(copies) == 1, "the install must not copy the tree again"
        assert (target / "SKILL.md").is_file()
