# -*- coding: utf-8 -*-
"""Workspace router filesystem helpers: stats, archive, upload targets.

These are the parts of ``app/routers/workspace.py`` that work purely on
paths and bytes, so they are exercised against real temporary trees
rather than mocks: directory accounting, in-memory archiving, the
atomic upload-target reservation table (overwrite / skip / rename /
reject), the zip safety gate, and the bound-project membership check
that authorizes Files API roots.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import workspace as workspace_router
from qwenpaw.services.project_directory import (
    ResolvedProjectDir,
    ResolvedProjectDirs,
)

_RESOLVE_DIRS = "qwenpaw.app.routers.workspace.get_project_dirs_for_request"
_DIR_KEY = "qwenpaw.services.project_directory.dir_key"


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _upload(filename: str, payload: bytes) -> Any:
    """A UploadFile stand-in: only ``filename`` and ``file`` are read."""
    return SimpleNamespace(filename=filename, file=io.BytesIO(payload))


# ---------------------------------------------------------------------------
# _dir_stats
# ---------------------------------------------------------------------------


class TestDirStats:
    def test_counts_files_and_sums_bytes_recursively(self, tmp_path):
        (tmp_path / "a.txt").write_text("12345", encoding="utf-8")
        nested = tmp_path / "sub" / "deep"
        nested.mkdir(parents=True)
        (nested / "b.txt").write_text("67", encoding="utf-8")
        assert workspace_router._dir_stats(tmp_path) == (2, 7)

    def test_empty_directory_is_zero(self, tmp_path):
        assert workspace_router._dir_stats(tmp_path) == (0, 0)

    def test_missing_directory_is_zero_not_an_error(self, tmp_path):
        assert workspace_router._dir_stats(tmp_path / "ghost") == (0, 0)

    def test_directories_are_not_counted_as_files(self, tmp_path):
        (tmp_path / "sub").mkdir()
        assert workspace_router._dir_stats(tmp_path) == (0, 0)


# ---------------------------------------------------------------------------
# _zip_directory
# ---------------------------------------------------------------------------


class TestZipDirectory:
    def test_files_and_empty_dirs_are_both_included(self, tmp_path):
        (tmp_path / "a.txt").write_text("A", encoding="utf-8")
        (tmp_path / "empty").mkdir()
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "b.txt").write_text("BB", encoding="utf-8")

        buffer = workspace_router._zip_directory(tmp_path)
        with zipfile.ZipFile(buffer) as zf:
            names = set(zf.namelist())
            assert names == {"a.txt", "empty/", "sub/", "sub/b.txt"}
            assert zf.read("a.txt") == b"A"
            assert zf.read("sub/b.txt") == b"BB"

    def test_buffer_is_rewound_to_the_start(self, tmp_path):
        (tmp_path / "a.txt").write_text("A", encoding="utf-8")
        buffer = workspace_router._zip_directory(tmp_path)
        assert buffer.tell() == 0
        assert buffer.read(4) == b"PK\x03\x04"

    def test_empty_root_yields_an_empty_archive(self, tmp_path):
        buffer = workspace_router._zip_directory(tmp_path)
        with zipfile.ZipFile(buffer) as zf:
            assert zf.namelist() == []

    def test_hidden_files_are_included(self, tmp_path):
        """_zip_directory archives everything; skipping is the lister's job."""
        (tmp_path / ".env").write_text("SECRET", encoding="utf-8")
        buffer = workspace_router._zip_directory(tmp_path)
        with zipfile.ZipFile(buffer) as zf:
            assert zf.namelist() == [".env"]


# ---------------------------------------------------------------------------
# _reserve_path / _reserve_upload_targets / _cleanup_upload_reservations
# ---------------------------------------------------------------------------


class TestReservePath:
    def test_reserves_a_new_file_without_truncating(self, tmp_path):
        target = tmp_path / "a.txt"
        assert workspace_router._reserve_path(target) is True
        assert target.exists()
        assert target.stat().st_size == 0
        if os.name != "nt":
            # Windows ignores the mode bits passed to os.open.
            assert oct(target.stat().st_mode & 0o777) == "0o600"

    def test_existing_file_is_not_reserved(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("keep me", encoding="utf-8")
        assert workspace_router._reserve_path(target) is False
        # the placeholder attempt must not have touched the content
        assert target.read_text(encoding="utf-8") == "keep me"


class TestReserveUploadTargets:
    def test_overwrite_reuses_the_existing_target(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("old", encoding="utf-8")
        upload = _upload("a.txt", b"new")
        allocated, reservations = workspace_router._reserve_upload_targets(
            [(upload, "a.txt", target)],
            "overwrite",
        )
        assert allocated == [(upload, "a.txt", target, target)]
        assert reservations == set()
        assert target.read_text(encoding="utf-8") == "old"

    def test_new_files_are_reserved(self, tmp_path):
        target = tmp_path / "a.txt"
        upload = _upload("a.txt", b"x")
        allocated, reservations = workspace_router._reserve_upload_targets(
            [(upload, "a.txt", target)],
            None,
        )
        assert allocated == [(upload, "a.txt", target, target)]
        assert reservations == {target}

    def test_skip_marks_the_target_unwritable(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("old", encoding="utf-8")
        upload = _upload("a.txt", b"new")
        allocated, reservations = workspace_router._reserve_upload_targets(
            [(upload, "a.txt", target)],
            "skip",
        )
        assert allocated == [(upload, "a.txt", None, target)]
        assert reservations == set()
        assert target.read_text(encoding="utf-8") == "old"

    def test_rename_picks_the_first_free_index(self, tmp_path):
        taken = tmp_path / "a.txt"
        taken.write_text("old", encoding="utf-8")
        (tmp_path / "a (1).txt").write_text("also taken", encoding="utf-8")
        upload = _upload("a.txt", b"new")
        allocated, reservations = workspace_router._reserve_upload_targets(
            [(upload, "a.txt", taken)],
            "rename",
        )
        chosen = tmp_path / "a (2).txt"
        assert allocated == [(upload, "a.txt", chosen, taken)]
        assert reservations == {chosen}
        assert chosen.exists()
        assert taken.read_text(encoding="utf-8") == "old"

    def test_unknown_conflict_mode_rejects(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("old", encoding="utf-8")
        upload = _upload("a.txt", b"new")
        with pytest.raises(FileExistsError, match="a.txt"):
            workspace_router._reserve_upload_targets(
                [(upload, "a.txt", target)],
                "explode",
            )

    def test_exhausted_rename_space_raises(self, tmp_path):
        """Every one of the 9999 candidate names is taken."""
        target = tmp_path / "a.txt"
        upload = _upload("a.txt", b"new")
        attempts: list[Path] = []

        def _always_taken(candidate: Path) -> bool:
            attempts.append(candidate)
            return False

        with patch.object(
            workspace_router,
            "_reserve_path",
            side_effect=_always_taken,
        ):
            with pytest.raises(
                OSError,
                match="Unable to allocate a conflict-free filename",
            ):
                workspace_router._reserve_upload_targets(
                    [(upload, "a.txt", target)],
                    "rename",
                )
        # the original name is probed first, then 1..9999
        assert attempts[0] == target
        assert attempts[1] == tmp_path / "a (1).txt"
        assert len(attempts) == 1 + 9999

    def test_failure_releases_every_earlier_reservation(self, tmp_path):
        """A later conflict must not leave the earlier placeholders behind."""
        first = tmp_path / "first.txt"
        second = tmp_path / "second.txt"
        second.write_text("old", encoding="utf-8")
        uploads = [
            (_upload("first.txt", b"1"), "first.txt", first),
            (_upload("second.txt", b"2"), "second.txt", second),
        ]
        with pytest.raises(FileExistsError, match="second.txt"):
            workspace_router._reserve_upload_targets(uploads, None)
        assert not first.exists()
        # the pre-existing file is untouched by the rollback
        assert second.read_text(encoding="utf-8") == "old"


class TestCleanupUploadReservations:
    def test_removes_leftover_placeholders(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        workspace_router._reserve_path(a)
        workspace_router._reserve_path(b)
        workspace_router._cleanup_upload_reservations({a, b})
        assert not a.exists()
        assert not b.exists()

    def test_already_gone_reservation_is_not_an_error(self, tmp_path):
        workspace_router._cleanup_upload_reservations({tmp_path / "ghost.txt"})

    def test_empty_set_is_a_no_op(self):
        workspace_router._cleanup_upload_reservations(set())


# ---------------------------------------------------------------------------
# _write_reserved_upload
# ---------------------------------------------------------------------------


class _FailingUpload:
    """An upload whose stream breaks part-way through."""

    def __init__(self, payload: bytes, fail_after: int) -> None:
        self.filename = "a.txt"
        self._buffer = io.BytesIO(payload)
        self._fail_after = fail_after
        self.file = self

    def seek(self, pos: int) -> None:
        self._buffer.seek(pos)

    def read(self, size: int) -> bytes:
        if self._fail_after <= 0:
            raise OSError("stream broke")
        chunk = self._buffer.read(min(size, self._fail_after))
        self._fail_after -= len(chunk)
        return chunk


class TestWriteReservedUpload:
    def test_writes_the_payload_and_reports_its_size(self, tmp_path):
        target = tmp_path / "a.txt"
        workspace_router._reserve_path(target)
        size = workspace_router._write_reserved_upload(
            _upload("a.txt", b"hello"),
            target,
        )
        assert size == 5
        assert target.read_bytes() == b"hello"
        assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]

    def test_rereads_from_the_start_of_the_stream(self, tmp_path):
        target = tmp_path / "a.txt"
        workspace_router._reserve_path(target)
        upload = _upload("a.txt", b"hello")
        upload.file.read(2)
        assert workspace_router._write_reserved_upload(upload, target) == 5

    def test_stream_failure_removes_the_temporary_file(self, tmp_path):
        target = tmp_path / "a.txt"
        workspace_router._reserve_path(target)
        with pytest.raises(OSError, match="stream broke"):
            workspace_router._write_reserved_upload(
                _FailingUpload(b"hello world", 5),
                target,
            )
        # the reservation placeholder survives, the partial temp file does not
        assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]
        assert target.stat().st_size == 0


# ---------------------------------------------------------------------------
# _prepare_upload_targets
# ---------------------------------------------------------------------------


class TestPrepareUploadTargets:
    def test_targets_and_conflicts_are_reported(self, tmp_path):
        (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
        files = [
            _upload("existing.txt", b"1"),
            _upload("fresh.txt", b"2"),
        ]
        targets, conflicts = workspace_router._prepare_upload_targets(
            tmp_path,
            files,
        )
        assert [name for _, name, _ in targets] == [
            "existing.txt",
            "fresh.txt",
        ]
        assert [t for _, _, t in targets] == [
            tmp_path / "existing.txt",
            tmp_path / "fresh.txt",
        ]
        assert conflicts == ["existing.txt"]

    def test_duplicate_names_in_one_batch_conflict(self, tmp_path):
        files = [_upload("a.txt", b"1"), _upload("a.txt", b"2")]
        targets, conflicts = workspace_router._prepare_upload_targets(
            tmp_path,
            files,
        )
        assert len(targets) == 2
        assert conflicts == ["a.txt"]

    @pytest.mark.parametrize("name", ["sub/a.txt", "..\\a.txt", "a\\b.txt"])
    def test_path_in_the_filename_is_rejected(self, tmp_path, name):
        with pytest.raises(HTTPException) as exc_info:
            workspace_router._prepare_upload_targets(
                tmp_path,
                [_upload(name, b"x")],
            )
        assert exc_info.value.status_code == 400
        assert "must not contain a path" in exc_info.value.detail

    def test_invalid_workspace_path_is_a_400(self, tmp_path):
        with patch.object(
            workspace_router,
            "resolve_workspace_path",
            side_effect=workspace_router.InvalidWorkspacePath("too deep"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                workspace_router._prepare_upload_targets(
                    tmp_path,
                    [_upload("a.txt", b"x")],
                )
        assert exc_info.value.status_code == 400
        assert "too deep" in exc_info.value.detail

    def test_empty_filename_is_a_400(self, tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            workspace_router._prepare_upload_targets(
                tmp_path,
                [_upload("", b"x")],
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _validate_zip_data / _validate_and_extract_zip
# ---------------------------------------------------------------------------


class TestValidateZipData:
    def test_valid_zip_passes(self, tmp_path):
        workspace_router._validate_zip_data(
            _zip_bytes({"a.txt": "A", "sub/b.txt": "B"}),
            tmp_path,
        )

    def test_non_zip_bytes_is_a_400(self, tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            workspace_router._validate_zip_data(b"not a zip", tmp_path)
        assert exc_info.value.status_code == 400
        assert "not a valid zip archive" in exc_info.value.detail

    def test_traversal_entry_is_a_400(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        data = _zip_bytes({"../escape.txt": "evil"})
        with pytest.raises(HTTPException) as exc_info:
            workspace_router._validate_zip_data(data, workspace)
        assert exc_info.value.status_code == 400
        assert "unsafe path" in exc_info.value.detail
        assert "../escape.txt" in exc_info.value.detail

    def test_sibling_directory_entry_is_a_400(self, tmp_path):
        # "../ws-evil/x" resolves outside ".../ws" but still textually
        # extends the workspace path, so a prefix check without the
        # separator lets it through.
        workspace = (tmp_path / "ws").resolve()
        workspace.mkdir()
        data = _zip_bytes({"../ws-evil/pwned.txt": "evil"})
        with pytest.raises(HTTPException) as exc_info:
            workspace_router._validate_zip_data(data, workspace)
        assert exc_info.value.status_code == 400
        assert "unsafe path" in exc_info.value.detail

    def test_absolute_entry_is_a_400(self, tmp_path):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("/etc/passwd", "evil")
        with pytest.raises(HTTPException) as exc_info:
            workspace_router._validate_zip_data(buffer.getvalue(), tmp_path)
        assert exc_info.value.status_code == 400
        assert "unsafe path" in exc_info.value.detail

    def test_validate_and_extract_writes_the_files(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace_router._validate_and_extract_zip(
            _zip_bytes({"a.txt": "A"}),
            workspace,
        )
        assert (workspace / "a.txt").read_text(encoding="utf-8") == "A"

    def test_validate_and_extract_rejects_before_writing(self, tmp_path):
        workspace = tmp_path / "ws"
        with pytest.raises(HTTPException):
            workspace_router._validate_and_extract_zip(
                _zip_bytes({"../escape.txt": "evil"}),
                workspace,
            )
        assert not workspace.exists()


# ---------------------------------------------------------------------------
# _resolve_extra_project_root / _resolve_files_root
# ---------------------------------------------------------------------------


def _resolved(dirs: tuple) -> ResolvedProjectDirs:
    return ResolvedProjectDirs(
        dirs=dirs,
        source="config",
        workspace_dir=Path("/nonexistent/ws"),
    )


class TestResolveExtraProjectRoot:
    async def test_bound_directory_is_returned(self, tmp_path):
        bound = tmp_path / "repo"
        bound.mkdir()
        entry = ResolvedProjectDir(path=bound, key="KEY")
        with patch(
            _RESOLVE_DIRS,
            new=AsyncMock(return_value=_resolved((entry,))),
        ), patch(_DIR_KEY, return_value="KEY"):
            result = await workspace_router._resolve_extra_project_root(
                MagicMock(),
                SimpleNamespace(agent_id="a"),
                f"  {bound}  ",
            )
        assert result == bound

    async def test_unbound_directory_is_403_not_a_silent_fallback(
        self,
        tmp_path,
    ):
        bound = tmp_path / "repo"
        entry = ResolvedProjectDir(path=bound, key="KEY")
        with patch(
            _RESOLVE_DIRS,
            new=AsyncMock(return_value=_resolved((entry,))),
        ), patch(_DIR_KEY, return_value="OTHER"):
            with pytest.raises(HTTPException) as exc_info:
                await workspace_router._resolve_extra_project_root(
                    MagicMock(),
                    SimpleNamespace(agent_id="a"),
                    str(tmp_path / "elsewhere"),
                )
        assert exc_info.value.status_code == 403
        assert "Not a bound project directory" in exc_info.value.detail

    async def test_entry_without_a_key_never_matches(self, tmp_path):
        """An entry built without a key must not match the empty key."""
        entry = ResolvedProjectDir(path=tmp_path / "repo", key="")
        with patch(
            _RESOLVE_DIRS,
            new=AsyncMock(return_value=_resolved((entry,))),
        ), patch(_DIR_KEY, return_value=""):
            with pytest.raises(HTTPException) as exc_info:
                await workspace_router._resolve_extra_project_root(
                    MagicMock(),
                    SimpleNamespace(agent_id="a"),
                    str(tmp_path / "repo"),
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.parametrize("raw", ["", "   "])
    async def test_blank_path_is_a_400(self, raw):
        resolved_mock = AsyncMock()
        with patch(_RESOLVE_DIRS, new=resolved_mock), patch(_DIR_KEY):
            with pytest.raises(HTTPException) as exc_info:
                await workspace_router._resolve_extra_project_root(
                    MagicMock(),
                    SimpleNamespace(agent_id="a"),
                    raw,
                )
        assert exc_info.value.status_code == 400
        assert "root path is empty" in exc_info.value.detail
        resolved_mock.assert_not_awaited()

    async def test_membership_is_decided_by_key_not_by_path_text(
        self,
        tmp_path,
    ):
        """A symlinked spelling of a bound dir still resolves to the entry."""
        real = tmp_path / "repo"
        real.mkdir()
        link = tmp_path / "alias"
        link.symlink_to(real)
        entry = ResolvedProjectDir(path=real, key="REAL")
        with patch(
            _RESOLVE_DIRS,
            new=AsyncMock(return_value=_resolved((entry,))),
        ), patch(
            _DIR_KEY,
            side_effect=lambda raw: "REAL"
            if Path(raw).name == "alias"
            else "OTHER",
        ):
            result = await workspace_router._resolve_extra_project_root(
                MagicMock(),
                SimpleNamespace(agent_id="a"),
                str(link),
            )
        assert result == real


class TestResolveFilesRoot:
    async def test_workspace_selector_returns_the_workspace_dir(self):
        workspace = SimpleNamespace(workspace_dir=Path("/ws"))
        result = await workspace_router._resolve_files_root(
            MagicMock(),
            workspace,
            "workspace",
        )
        assert result == Path("/ws")

    async def test_project_selector_uses_the_primary_dir(self):
        with patch(
            "qwenpaw.app.routers.workspace.get_project_dir_for_request",
            new=AsyncMock(return_value=Path("/proj")),
        ):
            result = await workspace_router._resolve_files_root(
                MagicMock(),
                SimpleNamespace(workspace_dir=Path("/ws")),
                "project",
            )
        assert result == Path("/proj")

    async def test_prefixed_selector_delegates_to_the_membership_check(self):
        with patch(
            "qwenpaw.app.routers.workspace._resolve_extra_project_root",
            new=AsyncMock(return_value=Path("/bound")),
        ) as resolver:
            result = await workspace_router._resolve_files_root(
                MagicMock(),
                SimpleNamespace(workspace_dir=Path("/ws")),
                "project:/bound",
            )
        assert result == Path("/bound")
        assert resolver.await_args.args[2] == "/bound"

    @pytest.mark.parametrize("root", ["", "projects", "PROJECT"])
    async def test_unknown_selector_is_a_400(self, root):
        with pytest.raises(HTTPException) as exc_info:
            await workspace_router._resolve_files_root(
                MagicMock(),
                SimpleNamespace(workspace_dir=Path("/ws")),
                root,
            )
        assert exc_info.value.status_code == 400
        assert "root must be" in exc_info.value.detail
