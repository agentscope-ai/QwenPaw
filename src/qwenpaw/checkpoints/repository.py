# -*- coding: utf-8 -*-
"""Shadow Git persistence and restore orchestration."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

from ..utils.io_utils import read_json, write_json_atomic, write_text_atomic
from .policy import (
    DEFAULT_CONFIG,
    EXCLUDE_PATTERNS,
    GIT_REQUIRED_MESSAGE,
    SNAPSHOT_EXCLUDE_PATHSPECS,
    ensure_git_available,
)
from .git_batch import GitBlobBatch
from .models import CheckpointError
from .safe_workspace_fs import SafeWorkspaceFS
from .tree_entries import TreeEntry, parse_tree_entries

_GIT_TIMEOUT_SECONDS = 120
_INDEX_CONTENT_POLICY = "byte-preserving"
_BYTE_PRESERVING_ATTRIBUTES = (
    "* -text -eol -filter -ident -working-tree-encoding\n"
)


class CheckpointRepository:
    """Own shadow Git persistence without checkpoint business semantics."""

    def __init__(self, workspace_dir: str | Path):
        ensure_git_available()
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self._workspace_fs = SafeWorkspaceFS(self.workspace_dir)
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
        return self._read_blob_spec(
            f"{commit}:{rel}",
            error_message=(
                f"Checkpoint {commit[:12]} does not contain file {rel}"
            ),
        )

    def _read_blob_spec(self, spec: str, *, error_message: str) -> bytes:
        try:
            proc = subprocess.run(
                self._git_command(
                    "cat-file",
                    "blob",
                    spec,
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
                error_message + (f": {detail}" if detail else ""),
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
    ) -> dict[str, TreeEntry]:
        """Return requested tree entries without discarding Git modes."""
        if not paths:
            return {}
        output = self.run_git("ls-tree", "-r", "-z", "--full-tree", commit)
        return parse_tree_entries(output, commit=commit, paths=paths)

    def _blob_batch(self) -> GitBlobBatch:
        return GitBlobBatch(
            self._git_command("cat-file", "--batch"),
            cwd=self.workspace_dir,
            env=self._git_env(),
            timeout=_GIT_TIMEOUT_SECONDS,
        )

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
        """Return a validated workspace path."""
        return self._workspace_fs.workspace_path(rel)

    def delete_workspace_path(self, rel: str) -> bool:
        """Delete a workspace entry without traversing reparse points."""
        return self._workspace_fs.delete_workspace_path(rel)

    def same_workspace_content(self, rel: str, expected: bytes) -> bool:
        """Return whether a workspace file exactly matches *expected*."""
        return self._workspace_fs.same_workspace_content(rel, expected)

    def plan_tree_restore(
        self,
        commit: str,
        paths: set[str],
    ) -> tuple[list[str], list[str]]:
        """Return paths that restoring from *commit* would write/delete."""
        restored: list[str] = []
        deleted: list[str] = []
        entries = self._tree_entries(commit, paths)
        for rel in sorted(paths - entries.keys()):
            target = self.workspace_path(rel)
            try:
                os.lstat(target)
            except FileNotFoundError:
                pass
            else:
                deleted.append(rel)
        if entries:
            with self._blob_batch() as blobs:
                for rel, entry in sorted(entries.items()):
                    with blobs.stream_blob(
                        entry.object_id,
                        error_message=(
                            f"Failed to read checkpoint file {rel}"
                        ),
                    ) as stream:
                        if not self._workspace_fs.same_tree_entry_stream(
                            rel,
                            entry.mode,
                            stream,
                            stream.size,
                        ):
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
        if entries:
            with self._blob_batch() as blobs:
                for rel, entry in sorted(entries.items()):
                    error_message = f"Failed to read checkpoint file {rel}"
                    with blobs.stream_blob(
                        entry.object_id,
                        error_message=error_message,
                    ) as stream:
                        matches = self._workspace_fs.same_tree_entry_stream(
                            rel,
                            entry.mode,
                            stream,
                            stream.size,
                        )
                    if matches:
                        continue
                    with blobs.stream_blob(
                        entry.object_id,
                        error_message=error_message,
                    ) as stream:
                        self._workspace_fs.restore_tree_entry_stream(
                            rel,
                            entry.mode,
                            stream,
                        )
                    restored.append(rel)
        return restored, sorted(deleted)

    def restore_internal_paths(self, blobs: dict[str, bytes]) -> None:
        """Restore checkpoint-internal regular files with private mode."""
        self._workspace_fs.restore_internal_paths(blobs)
