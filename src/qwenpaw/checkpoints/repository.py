# -*- coding: utf-8 -*-
"""Git and filesystem persistence for workspace checkpoints."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
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

    def tree_blob_paths(self, commit: str, paths: set[str]) -> set[str]:
        """Return the requested paths that are blobs, using one Git call."""
        if not paths:
            return set()
        output = self.run_git(
            "ls-tree",
            "-z",
            commit,
            "--",
            *sorted(paths),
        )
        blobs: set[str] = set()
        for item in output.split("\0"):
            header, separator, path = item.partition("\t")
            fields = header.split()
            if separator and len(fields) >= 2 and fields[1] == "blob":
                blobs.add(path)
        return blobs

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
        target = Path(os.path.abspath(self.workspace_dir / rel))
        if not target.is_relative_to(self.workspace_dir):
            raise CheckpointError(
                f"Refusing to write outside workspace: {rel}",
            )
        parent = target.parent
        while parent != self.workspace_dir:
            if parent.is_symlink():
                raise CheckpointError(
                    f"Refusing to follow workspace symlink for path: {rel}",
                )
            parent = parent.parent
        return target

    def delete_workspace_path(self, rel: str) -> bool:
        target = self.workspace_path(rel)
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
                return True
            if target.exists() or target.is_symlink():
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
            if (
                target.is_symlink()
                or not target.is_file()
                or target.stat().st_size != len(expected)
            ):
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
        blob_paths = self.tree_blob_paths(commit, paths)
        for rel in sorted(paths):
            if rel not in blob_paths:
                target = self.workspace_path(rel)
                if target.exists() or target.is_symlink():
                    deleted.append(rel)
                continue
            blob = self.read_blob(commit, rel)
            if not self.same_workspace_content(rel, blob):
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
        blob_paths = self.tree_blob_paths(commit, paths)
        for rel in sorted(paths - blob_paths, reverse=True):
            if self.delete_workspace_path(rel):
                deleted.append(rel)
        for rel in sorted(blob_paths):
            blob = self.read_blob(commit, rel)
            if self.same_workspace_content(rel, blob):
                continue
            target = self.workspace_path(rel)
            if target.is_dir() and not target.is_symlink():
                self.delete_workspace_path(rel)
            self.restore_paths({rel: blob})
            restored.append(rel)
        return restored, sorted(deleted)

    def restore_paths(self, blobs: dict[str, bytes]) -> None:
        for rel, content in blobs.items():
            target = self.workspace_path(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_path: Path | None = None
            try:
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
                os.replace(temp_path, target)
            except OSError as exc:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
                raise CheckpointError(
                    f"Failed to restore file {rel}: {exc}",
                ) from exc
