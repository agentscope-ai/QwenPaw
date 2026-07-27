# -*- coding: utf-8 -*-
"""Git and filesystem persistence for workspace checkpoints."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..utils.io_utils import read_json, write_json_atomic, write_text_atomic
from .policy import (
    DEFAULT_CONFIG,
    EXCLUDE_PATTERNS,
    GIT_REQUIRED_MESSAGE,
    SNAPSHOT_EXCLUDE_PATHSPECS,
    ensure_git_available,
)
from .models import CheckpointError

_GIT_TIMEOUT_SECONDS = 120
_INDEX_CONTENT_POLICY = "byte-preserving"
_BYTE_PRESERVING_ATTRIBUTES = (
    "* -text -eol -filter -ident -working-tree-encoding\n"
)
_REGULAR_TREE_MODES = {"100644": 0o644, "100755": 0o755}
_SYMLINK_TREE_MODE = "120000"
_RESTORABLE_TREE_MODES = frozenset(
    {*_REGULAR_TREE_MODES, _SYMLINK_TREE_MODE},
)
_REPARSE_POINT_ATTRIBUTE = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400,
)


@dataclass(frozen=True)
class _TreeEntry:
    """One restorable Git tree entry with its filesystem semantics."""

    mode: str
    content: bytes


class CheckpointRepository:
    """Own shadow Git persistence without checkpoint business semantics."""

    def __init__(self, workspace_dir: str | Path):
        ensure_git_available()
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.state_dir = self.workspace_dir / "checkpoints"
        self.git_dir = self.state_dir / "shadow.git"
        self.index_file = self.state_dir / "index"
        self.index_policy_file = self.state_dir / "index.policy"
        self.git_global_config = self.state_dir / "gitconfig"
        self.git_attributes_file = self.state_dir / "gitattributes"
        self.config_file = self.state_dir / "config.toml"
        self.heads_file = self.state_dir / "heads.json"
        self._git_process_env = self._build_git_env()
        self._heads: dict[str, str] | None = None
        self._pending_index_policy: str | None = None
        self.ensure_repo()

    def _build_git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_DIR": str(self.git_dir),
                "GIT_WORK_TREE": str(self.workspace_dir),
                "GIT_INDEX_FILE": str(self.index_file),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": str(self.git_global_config),
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "QwenPaw",
                "GIT_AUTHOR_EMAIL": "checkpoints@qwenpaw.local",
                "GIT_COMMITTER_NAME": "QwenPaw",
                "GIT_COMMITTER_EMAIL": "checkpoints@qwenpaw.local",
            },
        )
        return env

    def _git_command(self, *args: str) -> list[str]:
        """Build a Git command isolated from content-changing user config."""
        return [
            "git",
            "-c",
            "core.quotePath=false",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.safecrlf=false",
            "-c",
            f"core.attributesFile={self.git_attributes_file}",
            *args,
        ]

    def _git_env(self) -> dict[str, str]:
        """Return the immutable process environment shared by Git calls."""
        return self._git_process_env

    def _git_init_env(self) -> dict[str, str]:
        """Return isolated config without binding init to an existing repo."""
        env = self._git_env().copy()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(name, None)
        return env

    def run_git(self, *args: str, input_text: str | None = None) -> str:
        try:
            proc = subprocess.run(
                self._git_command(*args),
                cwd=str(self.workspace_dir),
                env=self._git_env(),
                input=(
                    input_text.encode("utf-8")
                    if input_text is not None
                    else None
                ),
                capture_output=True,
                check=False,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise CheckpointError(GIT_REQUIRED_MESSAGE) from exc
        except subprocess.TimeoutExpired as exc:
            raise CheckpointError(
                "git "
                f"{' '.join(args)} timed out after "
                f"{_GIT_TIMEOUT_SECONDS} seconds",
            ) from exc
        if proc.returncode != 0:
            detail = (
                (proc.stderr or proc.stdout or b"")
                .decode(
                    "utf-8",
                    errors="replace",
                )
                .strip()
            )
            raise CheckpointError(f"git {' '.join(args)} failed: {detail}")
        return proc.stdout.decode("utf-8", errors="replace").strip()

    def ensure_repo(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.git_global_config.write_text("", encoding="utf-8")
        self.git_attributes_file.write_text(
            _BYTE_PRESERVING_ATTRIBUTES,
            encoding="utf-8",
        )
        if not self.git_dir.exists():
            try:
                subprocess.run(
                    ["git", "init", "--bare", str(self.git_dir)],
                    env=self._git_init_env(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                    timeout=_GIT_TIMEOUT_SECONDS,
                )
            except FileNotFoundError as exc:
                raise CheckpointError(GIT_REQUIRED_MESSAGE) from exc
            except subprocess.TimeoutExpired as exc:
                raise CheckpointError(
                    "git init timed out after "
                    f"{_GIT_TIMEOUT_SECONDS} seconds",
                ) from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip()
                raise CheckpointError(
                    f"git init failed: {detail}",
                ) from exc
        info_dir = self.git_dir / "info"
        info_dir.mkdir(parents=True, exist_ok=True)
        (info_dir / "attributes").write_text(
            _BYTE_PRESERVING_ATTRIBUTES,
            encoding="utf-8",
        )
        exclude_path = info_dir / "exclude"
        existing = (
            exclude_path.read_text(encoding="utf-8").splitlines()
            if exclude_path.exists()
            else []
        )
        existing_set = set(existing)
        missing = [p for p in EXCLUDE_PATTERNS if p not in existing_set]
        if missing:
            merged = existing + missing
            exclude_path.write_text(
                "\n".join(merged) + "\n",
                encoding="utf-8",
            )
        if not self.config_file.exists():
            self.config_file.write_text(DEFAULT_CONFIG, encoding="utf-8")

    def _load_heads(self) -> dict[str, str]:
        if not self.heads_file.exists():
            return {}
        try:
            data = read_json(self.heads_file)
        except (OSError, UnicodeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            key: value
            for key, value in data.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def get_session_head(self, key: str) -> str | None:
        if self._heads is None:
            self._heads = self._load_heads()
        return self._heads.get(key)

    def set_session_head(self, key: str, commit: str) -> None:
        if self._heads is None:
            self._heads = self._load_heads()
        updated = dict(self._heads)
        updated[key] = commit
        self._atomic_write_json(self.heads_file, updated)
        self._heads = updated

    def remove_session_heads(self, keys: set[str]) -> None:
        """Remove deleted sessions from the persisted HEAD index."""
        if not keys:
            return
        if self._heads is None:
            self._heads = self._load_heads()
        updated = {
            key: commit
            for key, commit in self._heads.items()
            if key not in keys
        }
        if len(updated) == len(self._heads):
            return
        self._atomic_write_json(self.heads_file, updated)
        self._heads = updated

    def _index_policy_matches(self, pathspecs: tuple[str, ...]) -> bool:
        """Return whether the persistent index uses the current boundary."""
        digest = hashlib.sha256(
            "\0".join((_INDEX_CONTENT_POLICY, *pathspecs)).encode("utf-8"),
        ).hexdigest()
        try:
            current = self.index_policy_file.read_text(
                encoding="ascii",
            ).strip()
        except (OSError, UnicodeError):
            current = ""
        if current == digest and self.index_file.exists():
            return True
        self._pending_index_policy = digest
        return False

    def _commit_index_policy(self) -> None:
        digest = getattr(self, "_pending_index_policy", None)
        if not digest:
            return
        try:
            write_text_atomic(
                self.index_policy_file,
                digest + "\n",
                encoding="ascii",
            )
        except OSError as exc:
            raise CheckpointError(
                f"Failed to persist checkpoint index policy: {exc}",
            ) from exc
        self._pending_index_policy = None

    def write_workspace_tree(self) -> str:
        """Stage the snapshot boundary and return its Git tree object."""
        pathspecs = tuple(SNAPSHOT_EXCLUDE_PATHSPECS)
        if not self._index_policy_matches(pathspecs):
            self.run_git("read-tree", "--empty")
        self.run_git("add", "-f", "-A", "--", ".", *pathspecs)
        tree = self.run_git("write-tree")
        self._commit_index_policy()
        return tree

    def reset(self) -> None:
        """Delete and recreate all checkpoint-owned persistence."""
        if self.state_dir.exists():
            # Keep Python 3.11 compatibility; shutil.rmtree(onexc=...) is
            # unavailable there.
            # pylint: disable-next=deprecated-argument
            shutil.rmtree(self.state_dir, onerror=self._reset_onerror)
        self._heads = None
        self.ensure_repo()

    @staticmethod
    def _reset_onerror(func, path, exc_info) -> None:
        del exc_info
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def _atomic_write_json(self, path: Path, payload: dict) -> None:
        try:
            write_json_atomic(path, payload, indent=2, sort_keys=True)
        except OSError as exc:
            raise CheckpointError(
                f"Failed to write checkpoint state {path.name}: {exc}",
            ) from exc

    def ref_exists(self, ref: str) -> bool:
        try:
            proc = subprocess.run(
                self._git_command("show-ref", "--verify", "--quiet", ref),
                cwd=str(self.workspace_dir),
                env=self._git_env(),
                capture_output=True,
                check=False,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise CheckpointError(
                "git show-ref timed out after "
                f"{_GIT_TIMEOUT_SECONDS} seconds",
            ) from exc
        return proc.returncode == 0

    def read_blob(self, commit: str, rel: str) -> bytes:
        try:
            proc = subprocess.run(
                self._git_command(
                    "cat-file",
                    "blob",
                    f"{commit}:{rel}",
                ),
                cwd=str(self.workspace_dir),
                env=self._git_env(),
                capture_output=True,
                check=False,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise CheckpointError(
                "git cat-file timed out after "
                f"{_GIT_TIMEOUT_SECONDS} seconds",
            ) from exc
        if proc.returncode != 0:
            detail = proc.stderr.decode(errors="replace").strip()
            raise CheckpointError(
                f"Checkpoint {commit[:12]} does not contain file {rel}"
                + (f": {detail}" if detail else ""),
            )
        return proc.stdout

    def tree_has_blob(self, commit: str, rel: str) -> bool:
        """Return whether *rel* is a blob in *commit*."""
        output = self.run_git(
            "ls-tree",
            "-z",
            "--format=%(objecttype)",
            commit,
            "--",
            rel,
        )
        return any(item == "blob" for item in output.split("\0") if item)

    def _tree_entries(
        self,
        commit: str,
        paths: set[str],
    ) -> dict[str, _TreeEntry]:
        """Return requested tree entries without discarding Git modes."""
        if not paths:
            return {}
        output = self.run_git(
            "ls-tree",
            "-z",
            commit,
            "--",
            *sorted(paths),
        )
        entries: dict[str, _TreeEntry] = {}
        for item in output.split("\0"):
            if not item:
                continue
            header, separator, path = item.partition("\t")
            fields = header.split()
            if not separator or not path or len(fields) != 3:
                raise CheckpointError(
                    "Checkpoint contains malformed Git tree entry "
                    f"in {commit[:12]}",
                )
            mode, object_type, _object_id = fields
            if object_type != "blob" or mode not in _RESTORABLE_TREE_MODES:
                raise CheckpointError(
                    "Checkpoint contains unsupported Git tree entry "
                    f"{path}: mode={mode}, type={object_type}",
                )
            entries[path] = _TreeEntry(
                mode=mode,
                content=self.read_blob(commit, path),
            )
        return entries

    def list_tree_paths(self, commit: str, *prefixes: str) -> list[str]:
        """List blob paths below one or more checkpoint tree prefixes."""
        output = self.run_git(
            "ls-tree",
            "-r",
            "--name-only",
            commit,
            "--",
            *prefixes,
        )
        return sorted({line for line in output.splitlines() if line})

    def workspace_path(self, rel: str) -> Path:
        """Return a lexical target after validating its real parent chain."""
        target = Path(os.path.abspath(self.workspace_dir / rel))
        if not target.is_relative_to(self.workspace_dir):
            raise CheckpointError(
                f"Refusing to write outside workspace: {rel}",
            )
        try:
            resolved_parent = target.parent.resolve(strict=False)
        except OSError as exc:
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
        return False

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

    def _same_workspace_entry(self, rel: str, entry: _TreeEntry) -> bool:
        target = self.workspace_path(rel)
        try:
            target_stat = os.lstat(target)
            if entry.mode == _SYMLINK_TREE_MODE:
                return stat.S_ISLNK(target_stat.st_mode) and (
                    os.fsencode(os.readlink(target)) == entry.content
                )
            if self._is_reparse_stat(target_stat) or not stat.S_ISREG(
                target_stat.st_mode,
            ):
                return False
            if os.name != "nt":
                expected_executable = entry.mode == "100755"
                actual_executable = bool(target_stat.st_mode & 0o111)
                if actual_executable != expected_executable:
                    return False
            return self._same_regular_content(
                target,
                target_stat,
                entry.content,
            )
        except OSError:
            return False

    def plan_tree_restore(
        self,
        commit: str,
        paths: set[str],
    ) -> tuple[list[str], list[str]]:
        """Return paths that restoring from *commit* would write/delete."""
        restored: list[str] = []
        deleted: list[str] = []
        entries = self._tree_entries(commit, paths)
        for rel in sorted(paths):
            if rel not in entries:
                target = self.workspace_path(rel)
                try:
                    os.lstat(target)
                except FileNotFoundError:
                    pass
                else:
                    deleted.append(rel)
                continue
            if not self._same_workspace_entry(rel, entries[rel]):
                restored.append(rel)
        return restored, deleted

    def restore_tree_paths(
        self,
        commit: str,
        paths: set[str],
    ) -> tuple[list[str], list[str]]:
        """Restore selected workspace paths from a checkpoint tree."""
        restored: list[str] = []
        deleted: list[str] = []
        entries = self._tree_entries(commit, paths)
        for rel in sorted(paths - set(entries), reverse=True):
            if self.delete_workspace_path(rel):
                deleted.append(rel)
        for rel, entry in sorted(entries.items()):
            if self._same_workspace_entry(rel, entry):
                continue
            target = self.workspace_path(rel)
            try:
                target_stat = os.lstat(target)
            except FileNotFoundError:
                target_stat = None
            if target_stat is not None and stat.S_ISDIR(target_stat.st_mode):
                self.delete_workspace_path(rel)
            self._restore_tree_entry(rel, entry)
            restored.append(rel)
        return restored, sorted(deleted)

    def _restore_tree_entry(self, rel: str, entry: _TreeEntry) -> None:
        if entry.mode == _SYMLINK_TREE_MODE:
            self._restore_symlink(rel, entry.content)
            return
        self._restore_regular_file(
            rel,
            entry.content,
            mode=_REGULAR_TREE_MODES[entry.mode],
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
        temp_path: Path | None = None
        try:
            target, parent_identity = self._prepare_workspace_target(rel)
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.ckpt-",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)
            os.chmod(temp_path, mode)
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
