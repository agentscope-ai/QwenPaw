# -*- coding: utf-8 -*-
"""Staged installs by rename (skill pool, issue #8013 item 4).

Covers the rename into place and the copy fallback a refused one forces.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import store as skill_store
from qwenpaw.exceptions import SkillImportCancelled

_SKILL_MD = "---\nname: demo\ndescription: demo skill\n---\n# body\n"


def _write_tree(root: Path, files: int = 3) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    for index in range(files):
        (root / f"f{index}.txt").write_text(f"n{index}", encoding="utf-8")
    return root


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

    def test_falls_back_to_a_copy_when_the_rename_is_refused(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """A refused rename (cross-volume, or a locked file) copies instead."""
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = tmp_path / "workspace" / "skills" / "demo"
        monkeypatch.setattr(skill_store.os, "rename", _raise_locked_error)
        calls: list[tuple[Path, Path]] = []
        real_copy = skill_store.copy_skill_dir

        def _spy(source, destination):
            calls.append((Path(source), Path(destination)))
            real_copy(source, destination)

        monkeypatch.setattr(skill_store, "copy_skill_dir", _spy)
        skill_store.install_staged_skill_dir(staged, target)

        assert calls == [(staged, target)]
        assert (target / "SKILL.md").is_file()
        assert staged.exists()

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
            raise SkillImportCancelled()

        monkeypatch.setattr(skill_store, "ensure_not_cancelled", _cancelled)
        with pytest.raises(SkillImportCancelled):
            skill_store.install_staged_skill_dir(staged, target)

        assert marker.read_text(encoding="utf-8") == "original"
        assert staged.exists()

    def test_the_previous_tree_waits_under_a_hidden_name(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """Replacing must not delete the old tree inline: it is moved aside
        first, under a name no skill enumeration picks up."""
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = _write_tree(tmp_path / "workspace" / "skills" / "demo")
        (target / "stale.txt").write_text("old", encoding="utf-8")
        monkeypatch.setattr(
            skill_store,
            "_reclaim_retired_tree",
            lambda _path: None,
        )

        skill_store.install_staged_skill_dir(staged, target)

        retired = list(target.parent.glob(".demo.retired-*"))
        assert len(retired) == 1
        assert (retired[0] / "stale.txt").read_text(encoding="utf-8") == "old"
        assert skill_store.is_ignored_skill_entry(retired[0].name)

    def test_a_failed_install_puts_the_previous_tree_back(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = _write_tree(tmp_path / "workspace" / "skills" / "demo")
        marker = target / "keep.txt"
        marker.write_text("original", encoding="utf-8")

        def _boom(*_args, **_kwargs):
            raise OSError("install failed")

        monkeypatch.setattr(
            skill_store,
            "rename_or_copy_directory",
            _boom,
        )
        with pytest.raises(OSError, match="install failed"):
            skill_store.install_staged_skill_dir(staged, target)

        assert marker.read_text(encoding="utf-8") == "original"
        assert not list(target.parent.glob(".*.retired-*"))

    def test_keeps_the_old_tree_when_it_cannot_be_moved_back(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """If even the move back fails, the retired tree is the last copy and
        must not be reclaimed."""
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = _write_tree(tmp_path / "workspace" / "skills" / "demo")

        real_replace = skill_store.os.replace
        calls: list[tuple[Path, Path]] = []

        def _replace(source, destination):
            calls.append((Path(source), Path(destination)))
            if len(calls) == 2:  # the move back
                raise OSError("cannot move back")
            real_replace(source, destination)

        def _boom(*_args, **_kwargs):
            raise OSError("install failed")

        monkeypatch.setattr(skill_store.os, "replace", _replace)
        monkeypatch.setattr(
            skill_store,
            "rename_or_copy_directory",
            _boom,
        )
        with pytest.raises(OSError, match="install failed"):
            skill_store.install_staged_skill_dir(staged, target)

        retired = list(target.parent.glob(".demo.retired-*"))
        assert len(retired) == 1
        assert (retired[0] / "SKILL.md").is_file()

    def test_a_partial_target_does_not_block_the_move_back(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """A copy that dies half way leaves a partial target; putting the old
        tree back must remove it first instead of giving up."""
        staged = _write_tree(tmp_path / "stage" / "demo")
        target = _write_tree(tmp_path / "workspace" / "skills" / "demo")
        marker = target / "keep.txt"
        marker.write_text("original", encoding="utf-8")

        def _half_copy(_source, destination, **_kwargs):
            Path(destination).mkdir(parents=True, exist_ok=True)
            (Path(destination) / "partial.txt").write_text(
                "half",
                encoding="utf-8",
            )
            raise OSError("install failed")

        monkeypatch.setattr(
            skill_store,
            "rename_or_copy_directory",
            _half_copy,
        )
        with pytest.raises(OSError, match="install failed"):
            skill_store.install_staged_skill_dir(staged, target)

        assert marker.read_text(encoding="utf-8") == "original"
        assert not (target / "partial.txt").exists()
        assert not list(target.parent.glob(".*.retired-*"))


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


class TestRetiredTreeRetention:
    def test_another_install_keeps_a_tree_left_by_a_killed_run(
        self,
        tmp_path: Path,
    ):
        """A retired tree may be the only copy of an interrupted overwrite.

        Its name says how the directory was created, not that its contents are
        safe to drop: a process killed between moving the previous tree aside
        and renaming the new one leaves the old version here. Reclaiming it on
        the next, unrelated install turned that window into data loss.
        """
        skills_dir = tmp_path / "workspace" / "skills"
        skills_dir.mkdir(parents=True)
        retired = skills_dir / ".demo.retired-deadbeef"
        retired.mkdir()
        (retired / "SKILL.md").write_text(
            "previous version",
            encoding="utf-8",
        )

        staged = _write_tree(tmp_path / "stage" / "fresh")
        skill_store.install_staged_skill_dir(staged, skills_dir / "fresh")

        # The reclaim path removes the tree on a daemon thread; give it a
        # moment before deciding the tree survived.
        for _ in range(50):
            if not retired.is_dir():
                break
            time.sleep(0.01)

        assert retired.is_dir(), "an interrupted update must stay recoverable"
        assert (retired / "SKILL.md").read_text(
            encoding="utf-8",
        ) == "previous version"


# ---------------------------------------------------------------------------
# Cleanup timing (review: Leirunlin, 2026-11-20)
# ---------------------------------------------------------------------------


def test_a_failed_install_never_schedules_cleanup(tmp_path: Path, monkeypatch):
    """Reclaiming while the move back can still fail would delete the only
    recoverable copy, so the failure path schedules nothing."""
    staged = _write_tree(tmp_path / "stage" / "demo")
    target = _write_tree(tmp_path / "workspace" / "skills" / "demo")
    scheduled: list[Path] = []

    def _boom(*_args, **_kwargs):
        raise OSError("install failed")

    monkeypatch.setattr(skill_store, "rename_or_copy_directory", _boom)
    monkeypatch.setattr(
        skill_store,
        "_reclaim_retired_tree",
        lambda path: scheduled.append(path),
    )

    with pytest.raises(OSError, match="install failed"):
        skill_store.install_staged_skill_dir(staged, target)

    assert scheduled == []
    # The previous tree was moved back, so nothing was lost either.
    assert (target / "SKILL.md").is_file()


def test_cleanup_is_scheduled_only_after_the_new_tree_lands(
    tmp_path: Path,
    monkeypatch,
):
    """The old tree is reclaimed once the new one is already in place."""
    staged = _write_tree(tmp_path / "stage" / "demo")
    target = _write_tree(tmp_path / "workspace" / "skills" / "demo")
    scheduled: list[Path] = []
    monkeypatch.setattr(
        skill_store,
        "_reclaim_retired_tree",
        lambda path: scheduled.append(path),
    )

    skill_store.install_staged_skill_dir(staged, target)

    assert len(scheduled) == 1
    assert ".demo.retired-" in scheduled[0].name
    assert (target / "SKILL.md").is_file()


def test_a_cleanup_that_cannot_start_leaves_the_tree(
    tmp_path: Path,
    monkeypatch,
):
    """A thread that refuses to start must not fail the install around it."""
    tree = tmp_path / ".demo.retired-abc"
    tree.mkdir()

    class _RefusingThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(skill_store.threading, "Thread", _RefusingThread)

    skill_store._reclaim_retired_tree(tree)

    assert tree.is_dir()
