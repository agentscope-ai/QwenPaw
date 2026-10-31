# -*- coding: utf-8 -*-
"""Cancellation of ``copy_skill_dir``: between whole files, never mid-file.

A pool download is a copy of a skill directory into a workspace, so the copy
is the only place a long-running download can notice a cancellation. The
guarantees these tests pin are the ones the endpoint promises the client:
whole files only, nothing destroyed before the last check, and no behaviour
change at all when no checker is armed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.agents.skill_system.store import (
    copy_skill_dir,
    with_cancel_checker,
)
from qwenpaw.exceptions import SkillImportCancelled

_PAYLOAD = "payload-" * 512


def _make_source(root: Path, names: tuple[str, ...]) -> Path:
    source = root / "source"
    source.mkdir(parents=True)
    for index, name in enumerate(names):
        (source / name).write_text(
            f"{name}\n{_PAYLOAD}{index}\n",
            encoding="utf-8",
        )
    return source


def _file_names(directory: Path) -> set[str]:
    return {entry.name for entry in directory.iterdir() if entry.is_file()}


def test_cancellation_stops_the_copy_between_two_whole_files(tmp_path):
    names = ("a.txt", "b.txt", "c.txt", "d.txt")
    source = _make_source(tmp_path, names)
    target = tmp_path / "target"

    calls = {"count": 0}

    def checker() -> bool:
        calls["count"] += 1
        # First call is the one before the target is touched; cancel after
        # exactly one file has been copied.
        return calls["count"] > 2

    with with_cancel_checker(checker):
        with pytest.raises(SkillImportCancelled):
            copy_skill_dir(source, target)

    copied = _file_names(target)
    assert copied, "the copy should have started before it noticed"
    assert copied < set(names), "the cancellation must stop the copy early"
    for name in copied:
        assert (target / name).read_bytes() == (
            source / name
        ).read_bytes(), "a file that landed must be complete, never truncated"
    assert _file_names(source) == set(names), "the source is read-only for us"


def test_an_already_cancelled_copy_leaves_the_existing_target_untouched(
    tmp_path,
):
    """The last check runs before the target is replaced, not after."""
    source = _make_source(tmp_path, ("a.txt",))
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("previous skill\n", encoding="utf-8")

    with with_cancel_checker(lambda: True):
        with pytest.raises(SkillImportCancelled):
            copy_skill_dir(source, target)

    assert (
        target / "keep.txt"
    ).is_file(), (
        "cancelling before the first byte must not delete what was there"
    )
    assert not (target / "a.txt").exists()


def test_an_unarmed_copy_is_unchanged(tmp_path):
    names = ("a.txt", "b.txt", "c.txt")
    source = _make_source(tmp_path, names)
    target = tmp_path / "target"

    copy_skill_dir(source, target)

    assert _file_names(target) == set(names)
    for name in names:
        assert (target / name).read_bytes() == (source / name).read_bytes()
