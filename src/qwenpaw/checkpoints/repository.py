# -*- coding: utf-8 -*-
"""Git and filesystem persistence for workspace checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from .policy import (
    DEFAULT_CONFIG,
    EXCLUDE_PATTERNS,
    GIT_REQUIRED_MESSAGE,
    SNAPSHOT_EXCLUDE_PATHSPECS,
    ensure_git_available,
)
from .models import CheckpointError


class CheckpointRepository:
    """Own shadow Git persistence without checkpoint business semantics."""

    def __init__(self, workspace_dir: str | Path):
        ensure_git_available()
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.state_dir = self.workspace_dir / "checkpoints"
        self.git_dir = self.state_dir / "shadow.git"
        self.index_file = self.state_dir / "index"
        self.index_policy_file = self.state_dir / "index.policy"
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
                "GIT_AUTHOR_NAME": "QwenPaw",
                "GIT_AUTHOR_EMAIL": "checkpoints@qwenpaw.local",
                "GIT_COMMITTER_NAME": "QwenPaw",
                "GIT_COMMITTER_EMAIL": "checkpoints@qwenpaw.local",
            },
        )
        return env

    def _git_env(self) -> dict[str, str]:
        """Return the immutable process environment shared by Git calls."""
        return self._git_process_env

    def run_git(self, *args: str, input_text: str | None = None) -> str:
        try:
            proc = subprocess.run(
                ["git", "-c", "core.quotePath=false", *args],
                cwd=str(self.workspace_dir),
                env=self._git_env(),
                input=(
                    input_text.encode("utf-8")
                    if input_text is not None
                    else None
                ),
                capture_output=True,
                check=False,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise CheckpointError(GIT_REQUIRED_MESSAGE) from exc
        except subprocess.TimeoutExpired as exc:
            raise CheckpointError(
                f"git {' '.join(args)} timed out after 120 seconds",
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
        if not self.git_dir.exists():
            try:
                subprocess.run(
                    ["git", "init", "--bare", str(self.git_dir)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                )
            except FileNotFoundError as exc:
                raise CheckpointError(GIT_REQUIRED_MESSAGE) from exc
        info_dir = self.git_dir / "info"
        info_dir.mkdir(parents=True, exist_ok=True)
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
            data = json.loads(self.heads_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
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
            "\0".join(pathspecs).encode("utf-8"),
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
        temp = self.index_policy_file.with_suffix(".policy.tmp")
        try:
            temp.write_text(digest + "\n", encoding="ascii")
            os.replace(temp, self.index_policy_file)
        except OSError as exc:
            temp.unlink(missing_ok=True)
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
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                json.dump(
                    payload,
                    temp_file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)
            os.replace(temp_path, path)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise CheckpointError(
                f"Failed to write checkpoint state {path.name}: {exc}",
            ) from exc

    def ref_exists(self, ref: str) -> bool:
        proc = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", ref],
            cwd=str(self.workspace_dir),
            env=self._git_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode == 0

    def read_blob(self, commit: str, rel: str) -> bytes:
        proc = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{rel}"],
            cwd=str(self.workspace_dir),
            env=self._git_env(),
            capture_output=True,
            check=False,
        )
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
