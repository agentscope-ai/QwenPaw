# -*- coding: utf-8 -*-
"""Behavioral tests for the transactional patch primitive."""

from __future__ import annotations

import asyncio
import pytest

from qwenpaw.patching import PatchError, apply_patch_document, parse_patch
from qwenpaw.patching.executor import _commit
from qwenpaw.patching.models import PatchPlan, PlannedMutation


@pytest.mark.asyncio
async def test_multi_file_multi_hunk_add_delete_move_preserves_format(tmp_path):
    original = b"\xef\xbb\xbffirst\r\none\r\nmiddle\r\ntwo\r\nlast\r\n"
    (tmp_path / "source.txt").write_bytes(original)
    (tmp_path / "delete.txt").write_text("obsolete\n", encoding="utf-8")
    patch = parse_patch(
        """*** Begin Patch
*** Update File: source.txt
*** Move to: moved.txt
@@ first
 first
-one
+ONE
 middle
@@ two
 middle
-two
+TWO
 last
*** Add File: nested/new.txt
+hello
+world
*** Delete File: delete.txt
*** End Patch""",
    )

    result = await apply_patch_document(tmp_path, patch)

    assert result.hunks_applied == 2
    assert not (tmp_path / "source.txt").exists()
    assert not (tmp_path / "delete.txt").exists()
    assert (tmp_path / "moved.txt").read_bytes() == (
        b"\xef\xbb\xbffirst\r\nONE\r\nmiddle\r\nTWO\r\nlast\r\n"
    )
    assert (tmp_path / "nested/new.txt").read_bytes() == b"hello\nworld\n"


@pytest.mark.asyncio
async def test_conflict_leaves_every_file_byte_for_byte_unchanged(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"alpha\n")
    second.write_bytes(b"beta\n")
    patch = parse_patch(
        """*** Begin Patch
*** Update File: first.txt
@@
-alpha
+changed
*** Update File: second.txt
@@
-not-beta
+changed
*** End Patch""",
    )

    with pytest.raises(PatchError) as caught:
        await apply_patch_document(tmp_path, patch)

    assert caught.value.code == "patch_conflict"
    assert caught.value.conflicts[0].code == "context_mismatch"
    assert first.read_bytes() == b"alpha\n"
    assert second.read_bytes() == b"beta\n"


def test_rejects_ambiguous_context_and_unsafe_paths(tmp_path):
    (tmp_path / "duplicate.txt").write_text("same\nsame\n", encoding="utf-8")
    ambiguous = parse_patch(
        """*** Begin Patch
*** Update File: duplicate.txt
@@
-same
+changed
*** End Patch""",
    )
    unsafe = parse_patch(
        """*** Begin Patch
*** Add File: ../escape.txt
+no
*** End Patch""",
    )

    with pytest.raises(PatchError) as caught:
        asyncio.run(apply_patch_document(tmp_path, ambiguous))
    assert caught.value.conflicts[0].code == "ambiguous_context"
    with pytest.raises(PatchError) as unsafe_error:
        asyncio.run(apply_patch_document(tmp_path, unsafe))
    assert unsafe_error.value.code == "unsafe_path"


def test_parser_reports_missing_end_marker():
    with pytest.raises(PatchError) as caught:
        parse_patch("*** Begin Patch\n*** Add File: x.txt\n+x")
    assert caught.value.code == "missing_end"


def test_commit_failure_rolls_back_files_and_created_directories(
    tmp_path,
    monkeypatch,
):
    first = tmp_path / "a.txt"
    second = tmp_path / "nested" / "b.txt"
    first.write_bytes(b"old-a")
    plan = PatchPlan(
        mutations=(
            PlannedMutation(first, b"new-a"),
            PlannedMutation(second, b"new-b"),
        ),
        files=("a.txt", "nested/b.txt"),
        hunks_applied=2,
    )
    from qwenpaw.patching import executor

    real_replace = executor.os.replace

    def fail_second_stage(source, destination):
        if str(source).endswith("patch-stage") and destination == second:
            raise OSError("injected commit failure")
        return real_replace(source, destination)

    monkeypatch.setattr(executor.os, "replace", fail_second_stage)

    with pytest.raises(PatchError) as caught:
        _commit(plan)

    assert caught.value.code == "commit_error"
    assert caught.value.rolled_back is True
    assert first.read_bytes() == b"old-a"
    assert not second.exists()
    assert not second.parent.exists()
    assert not list(tmp_path.rglob("*.patch-stage"))
    assert not list(tmp_path.rglob("*.patch-backup"))
