# -*- coding: utf-8 -*-
"""Safe, byte-preserving filesystem operations for checkpoint restore."""

from __future__ import annotations

import os
import stat
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Protocol

from .models import CheckpointError
from .tree_entries import REGULAR_TREE_MODES, SYMLINK_TREE_MODE

_REPARSE_POINT_ATTRIBUTE = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400,
)
_STREAM_CHUNK_SIZE = 1024 * 1024


class _ReadableStream(Protocol):
    def read(self, size: int = -1) -> bytes:
        """Read up to *size* bytes from the stream."""


class SafeWorkspaceFS:
    """Confine checkpoint comparisons and mutations to one workspace."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir

    def workspace_path(self, rel: str) -> Path:
        """Return a lexical target after validating its real parent chain."""
        target = Path(os.path.abspath(self.workspace_dir / rel))
        if not target.is_relative_to(self.workspace_dir):
            raise CheckpointError(
                f"Refusing to write outside workspace: {rel}",
            )
        try:
            resolved_parent = target.parent.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise CheckpointError(
                f"Failed to resolve workspace path {rel}: {exc}",
            ) from exc
        if not resolved_parent.is_relative_to(self.workspace_dir):
            raise CheckpointError(
                f"Refusing to write outside workspace: {rel}",
            )
        current = self.workspace_dir
        for component in target.relative_to(self.workspace_dir).parts[:-1]:
            current /= component
            try:
                current_stat = os.lstat(current)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise CheckpointError(
                    f"Failed to inspect workspace path {rel}: {exc}",
                ) from exc
            if self._is_reparse_stat(current_stat):
                raise CheckpointError(
                    "Refusing to follow workspace symlink or reparse point "
                    f"for path: {rel}",
                )
            if not stat.S_ISDIR(current_stat.st_mode):
                raise CheckpointError(
                    f"Workspace parent is not a directory for path: {rel}",
                )
        return target

    @staticmethod
    def _is_reparse_stat(path_stat: os.stat_result) -> bool:
        attributes = getattr(path_stat, "st_file_attributes", 0)
        return stat.S_ISLNK(path_stat.st_mode) or bool(
            attributes & _REPARSE_POINT_ATTRIBUTE,
        )

    @staticmethod
    def _path_identity(path_stat: os.stat_result) -> tuple[int, int, int]:
        return (
            path_stat.st_dev,
            path_stat.st_ino,
            getattr(path_stat, "st_file_attributes", 0),
        )

    def _prepare_workspace_target(
        self,
        rel: str,
    ) -> tuple[Path, tuple[int, int, int]]:
        """Create and validate a target parent, returning its identity."""
        target = self.workspace_path(rel)
        current = self.workspace_dir
        for component in target.relative_to(self.workspace_dir).parts[:-1]:
            current /= component
            try:
                current.mkdir()
            except FileExistsError:
                pass
            target = self.workspace_path(rel)
        try:
            parent_stat = os.lstat(target.parent)
        except OSError as exc:
            raise CheckpointError(
                f"Failed to inspect workspace parent for {rel}: {exc}",
            ) from exc
        if self._is_reparse_stat(parent_stat) or not stat.S_ISDIR(
            parent_stat.st_mode,
        ):
            raise CheckpointError(
                f"Unsafe workspace parent for path: {rel}",
            )
        return target, self._path_identity(parent_stat)

    def _verify_workspace_parent(
        self,
        rel: str,
        expected_identity: tuple[int, int, int],
    ) -> Path:
        """Revalidate containment and parent identity before publication."""
        target = self.workspace_path(rel)
        try:
            parent_stat = os.lstat(target.parent)
        except OSError as exc:
            raise CheckpointError(
                f"Failed to revalidate workspace parent for {rel}: {exc}",
            ) from exc
        if (
            self._is_reparse_stat(parent_stat)
            or self._path_identity(parent_stat) != expected_identity
        ):
            raise CheckpointError(
                f"Workspace parent changed while restoring path: {rel}",
            )
        return target

    def _remove_tree_without_reparse(
        self,
        target: Path,
        expected_identity: tuple[int, int, int],
    ) -> None:
        """Remove a real directory tree without traversing reparse points."""
        target_stat = os.lstat(target)
        if (
            self._is_reparse_stat(target_stat)
            or self._path_identity(target_stat) != expected_identity
        ):
            raise CheckpointError(
                f"Directory changed while deleting path: {target}",
            )
        with os.scandir(target) as entries:
            for entry in entries:
                entry_path = Path(entry.path)
                entry_stat = entry.stat(follow_symlinks=False)
                if self._is_reparse_stat(entry_stat):
                    if stat.S_ISDIR(entry_stat.st_mode):
                        os.rmdir(entry_path)
                    else:
                        entry_path.unlink()
                elif stat.S_ISDIR(entry_stat.st_mode):
                    self._remove_tree_without_reparse(
                        entry_path,
                        self._path_identity(entry_stat),
                    )
                else:
                    entry_path.unlink()
        os.rmdir(target)

    def delete_workspace_path(self, rel: str) -> bool:
        """Delete a workspace entry without traversing reparse points."""
        target = self.workspace_path(rel)
        try:
            target_stat = os.lstat(target)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CheckpointError(
                f"Failed to inspect file {rel}: {exc}",
            ) from exc
        try:
            if self._is_reparse_stat(target_stat):
                if stat.S_ISDIR(target_stat.st_mode):
                    os.rmdir(target)
                else:
                    target.unlink()
                return True
            if stat.S_ISDIR(target_stat.st_mode):
                self._remove_tree_without_reparse(
                    target,
                    self._path_identity(target_stat),
                )
                return True
            target.unlink()
            return True
        except OSError as exc:
            raise CheckpointError(
                f"Failed to delete file {rel}: {exc}",
            ) from exc

    def same_workspace_content(self, rel: str, expected: bytes) -> bool:
        """Return whether a workspace file exactly matches *expected*."""
        target = self.workspace_path(rel)
        try:
            target_stat = os.lstat(target)
            if self._is_reparse_stat(target_stat) or not stat.S_ISREG(
                target_stat.st_mode,
            ):
                return False
            return self._same_regular_content(target, target_stat, expected)
        except OSError:
            return False

    @staticmethod
    def _same_regular_content(
        target: Path,
        target_stat: os.stat_result,
        expected: bytes,
    ) -> bool:
        if target_stat.st_size != len(expected):
            return False
        view = memoryview(expected)
        offset = 0
        with target.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                end = offset + len(chunk)
                if chunk != view[offset:end]:
                    return False
                offset = end
        return offset == len(expected)

    def same_tree_entry(self, rel: str, mode: str, content: bytes) -> bool:
        """Return whether a workspace entry matches Git mode and content."""
        target = self.workspace_path(rel)
        try:
            target_stat = os.lstat(target)
            if mode == SYMLINK_TREE_MODE:
                return stat.S_ISLNK(target_stat.st_mode) and (
                    os.fsencode(os.readlink(target)) == content
                )
            if self._is_reparse_stat(target_stat) or not stat.S_ISREG(
                target_stat.st_mode,
            ):
                return False
            if os.name != "nt":
                expected_executable = mode == "100755"
                actual_executable = bool(target_stat.st_mode & 0o111)
                if actual_executable != expected_executable:
                    return False
            return self._same_regular_content(target, target_stat, content)
        except OSError:
            return False

    def same_tree_entry_stream(
        self,
        rel: str,
        mode: str,
        stream: _ReadableStream,
        size: int,
    ) -> bool:
        """Compare one Git entry without materializing regular-file bytes."""
        target = self.workspace_path(rel)
        try:
            target_stat = os.lstat(target)
            if mode == SYMLINK_TREE_MODE:
                content = self._read_stream(stream)
                return stat.S_ISLNK(target_stat.st_mode) and (
                    os.fsencode(os.readlink(target)) == content
                )
            if self._is_reparse_stat(target_stat) or not stat.S_ISREG(
                target_stat.st_mode,
            ):
                return False
            if os.name != "nt":
                expected_executable = mode == "100755"
                actual_executable = bool(target_stat.st_mode & 0o111)
                if actual_executable != expected_executable:
                    return False
            if target_stat.st_size != size:
                return False
            return self._same_regular_stream(target, stream)
        except OSError:
            return False

    @staticmethod
    def _same_regular_stream(
        target: Path,
        stream: _ReadableStream,
    ) -> bool:
        with target.open("rb") as current:
            while expected := stream.read(_STREAM_CHUNK_SIZE):
                if current.read(len(expected)) != expected:
                    return False
            return current.read(1) == b""

    def restore_tree_entry(self, rel: str, mode: str, content: bytes) -> bool:
        """Restore one Git tree entry, returning whether it changed."""
        if self.same_tree_entry(rel, mode, content):
            return False
        target = self.workspace_path(rel)
        try:
            target_stat = os.lstat(target)
        except FileNotFoundError:
            target_stat = None
        if target_stat is not None and stat.S_ISDIR(target_stat.st_mode):
            self.delete_workspace_path(rel)
        if mode == SYMLINK_TREE_MODE:
            self._restore_symlink(rel, content)
        else:
            self._restore_regular_file(
                rel,
                content,
                mode=REGULAR_TREE_MODES[mode],
            )
        return True

    def restore_tree_entry_stream(
        self,
        rel: str,
        mode: str,
        stream: _ReadableStream,
    ) -> None:
        """Restore one known-different Git entry from a bounded stream."""
        target = self.workspace_path(rel)
        try:
            target_stat = os.lstat(target)
        except FileNotFoundError:
            target_stat = None
        if target_stat is not None and stat.S_ISDIR(target_stat.st_mode):
            self.delete_workspace_path(rel)
        if mode == SYMLINK_TREE_MODE:
            self._restore_symlink(rel, self._read_stream(stream))
        else:
            self._restore_regular_file_stream(
                rel,
                stream,
                mode=REGULAR_TREE_MODES[mode],
            )

    def restore_internal_paths(self, blobs: dict[str, bytes]) -> None:
        """Restore checkpoint-internal regular files with private mode."""
        for rel, content in blobs.items():
            self._restore_regular_file(rel, content, mode=0o600)

    def _restore_regular_file(
        self,
        rel: str,
        content: bytes,
        *,
        mode: int,
    ) -> None:
        with BytesIO(content) as stream:
            self._restore_regular_file_stream(rel, stream, mode=mode)

    def _restore_regular_file_stream(
        self,
        rel: str,
        stream: _ReadableStream,
        *,
        mode: int,
    ) -> None:
        temp_path: Path | None = None
        try:
            target, parent_identity = self._prepare_workspace_target(rel)
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.ckpt-",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                while chunk := stream.read(_STREAM_CHUNK_SIZE):
                    temp_file.write(chunk)
                temp_file.flush()
                if os.name != "nt":
                    os.fchmod(temp_file.fileno(), mode)
                os.fsync(temp_file.fileno())
            target = self._verify_workspace_parent(rel, parent_identity)
            os.replace(temp_path, target)
            temp_path = None
            self._verify_workspace_parent(rel, parent_identity)
        except CheckpointError:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise CheckpointError(
                f"Failed to restore file {rel}: {exc}",
            ) from exc

    @staticmethod
    def _read_stream(stream: _ReadableStream) -> bytes:
        chunks: list[bytes] = []
        while chunk := stream.read(_STREAM_CHUNK_SIZE):
            chunks.append(chunk)
        return b"".join(chunks)

    def _restore_symlink(self, rel: str, content: bytes) -> None:
        temp_path: Path | None = None
        try:
            target, parent_identity = self._prepare_workspace_target(rel)
            handle, temp_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.ckpt-",
                suffix=".tmp",
            )
            os.close(handle)
            temp_path = Path(temp_name)
            temp_path.unlink()
            os.symlink(os.fsdecode(content), temp_path)
            target = self._verify_workspace_parent(rel, parent_identity)
            os.replace(temp_path, target)
            temp_path = None
            self._verify_workspace_parent(rel, parent_identity)
        except CheckpointError:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise CheckpointError(
                f"Failed to restore symbolic link {rel}: {exc}",
            ) from exc


__all__ = ["SafeWorkspaceFS"]
