# -*- coding: utf-8 -*-
"""Workspace snapshot and rollback support."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback handled below
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX fallback handled above
    msvcrt = None

logger = logging.getLogger(__name__)

_UNDO_OK = "ok"
_UNDO_EMPTY = "empty"
_UNDO_DIVERGED = "diverged"
_UNDO_FAILED = "failed"


@dataclass
class RollbackEntry:
    """A single linear workspace rollback record."""

    id: str
    session_id: str
    before_hash: str
    after_hash: str
    files: list[str]
    created_at: float
    status: str  # "applied" or "undone"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entry for JSON persistence."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RollbackEntry:
        """Deserialize an entry from JSON payload."""
        return cls(**cast(dict[str, Any], data))


class SnapshotService:
    """Workspace-level file snapshot and rollback service."""

    _locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.rollback_dir = self.workspace_dir / ".copaw" / "rollback"
        self.git_dir = self.rollback_dir / "git"
        self.history_file = self.rollback_dir / "history.json"
        self.lock_file = self.rollback_dir / "workspace.lock"
        self._lock_key = str(self.workspace_dir)
        self._git_error_logged = False
        self._git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "",
            "GIT_CONFIG_SYSTEM": "",
            "GIT_AUTHOR_NAME": "CoPaw Snapshot Service",
            "GIT_AUTHOR_EMAIL": "copaw@localhost",
            "GIT_COMMITTER_NAME": "CoPaw Snapshot Service",
            "GIT_COMMITTER_EMAIL": "copaw@localhost",
        }

    @staticmethod
    def _acquire_file_lock(handle) -> None:
        """Take an exclusive cross-process workspace lock."""
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            return
        if msvcrt is not None:  # pragma: no cover - Windows only
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    @staticmethod
    def _release_file_lock(handle) -> None:
        """Release the cross-process workspace lock."""
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return
        if msvcrt is not None:  # pragma: no cover - Windows only
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    @asynccontextmanager
    async def _workspace_lock(self):
        """Serialize workspace rollback state across tasks and processes."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.rollback_dir.mkdir(parents=True, exist_ok=True)
        async with self._locks[self._lock_key]:
            with open(self.lock_file, "a+b") as handle:
                await asyncio.to_thread(self._acquire_file_lock, handle)
                try:
                    yield
                finally:
                    await asyncio.to_thread(
                        self._release_file_lock,
                        handle,
                    )

    def _git_cmd(self, *args: str) -> list[str]:
        return [
            "git",
            "--git-dir",
            str(self.git_dir),
            "--work-tree",
            str(self.workspace_dir),
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.longpaths=true",
            "-c",
            "core.symlinks=true",
            "-c",
            "core.quotepath=false",
            *args,
        ]

    async def _run_command(
        self,
        cmd: list[str],
    ) -> tuple[int, str, str]:
        """Run a subprocess and return (code, stdout, stderr)."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._git_env,
                cwd=str(self.workspace_dir),
            )
        except (FileNotFoundError, OSError) as exc:
            if not self._git_error_logged:
                logger.warning(
                    "Rollback disabled for %s because git is unavailable: %s",
                    self.workspace_dir,
                    exc,
                )
                self._git_error_logged = True
            return 127, "", str(exc)
        stdout, stderr = await process.communicate()
        return (
            process.returncode or 0,
            stdout.decode().strip(),
            stderr.decode().strip(),
        )

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        """Run git against the internal git-dir/work-tree pair."""
        code, stdout, stderr = await self._run_command(self._git_cmd(*args))
        if code != 0:
            logger.debug(
                "git %s failed with %s:\n%s",
                " ".join(args),
                code,
                stderr,
            )
        return code, stdout, stderr

    async def _bootstrap_git_dir_locked(self) -> bool:
        """Create the internal git-dir once for this workspace."""
        if (self.git_dir / "HEAD").exists():
            return True

        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        code, _, stderr = await self._run_command(
            ["git", "init", "--bare", str(self.git_dir)],
        )
        if code != 0:
            logger.warning(
                "Failed to initialize rollback git-dir: %s",
                stderr,
            )
            return False
        return True

    def _write_excludes_locked(self) -> None:
        """Exclude CoPaw runtime noise from rollback snapshots."""
        info_dir = self.git_dir / "info"
        info_dir.mkdir(parents=True, exist_ok=True)
        exclusions = [
            ".copaw/",
            ".git/",
            "agent.json",
            "sessions/",
            "chat.json",
            "chats.json",
            "dialog/",
            "file_store/",
            "memory/",
            "memory_file_metadata.json",
            "skill.json",
            ".skill.json.lock",
            "token_usage.json",
            ".reme_store_*",
            "node_modules/",
            "venv/",
            ".venv/",
            "__pycache__/",
            ".pytest_cache/",
        ]
        with open(
            info_dir / "exclude",
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("\n".join(exclusions) + "\n")

    async def _stage_all_locked(self) -> bool:
        """Refresh the index from the current workspace state."""
        code, _, stderr = await self._run_git("add", "-A", "--", ".")
        if code != 0:
            logger.warning("Failed to add files to snapshot: %s", stderr)
            return False
        return True

    async def _write_tree_locked(self) -> str | None:
        """Write and return the current tree hash."""
        code, stdout, stderr = await self._run_git("write-tree")
        if code != 0:
            logger.warning("Failed to write tree: %s", stderr)
            return None
        return stdout

    async def _track_locked(self) -> str | None:
        """Capture the current workspace tree under the service lock."""
        if not await self._stage_all_locked():
            return None
        return await self._write_tree_locked()

    async def _patch_locked(self, base_hash: str) -> list[str]:
        """Compute changed files since ``base_hash`` under the lock."""
        if not await self._stage_all_locked():
            return []

        code, stdout, stderr = await self._run_git(
            "diff",
            "--cached",
            "--no-ext-diff",
            "--find-renames",
            "--name-status",
            base_hash,
            "--",
            ".",
        )
        if code != 0:
            logger.warning("Failed to get patch diff: %s", stderr)
            return []
        return self._parse_changed_paths(stdout)

    @staticmethod
    def _parse_changed_paths(diff_output: str) -> list[str]:
        """Return rollback-relevant paths from git name-status output."""
        paths: list[str] = []
        seen: set[str] = set()

        for line in diff_output.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            status = parts[0]
            candidates = parts[1:]
            if status.startswith(("R", "C")) and len(candidates) >= 2:
                chosen = candidates[:2]
            elif candidates:
                chosen = candidates[:1]
            else:
                continue

            for path in chosen:
                if path not in seen:
                    seen.add(path)
                    paths.append(path)

        return paths

    async def _files_match_tree_locked(
        self,
        target_hash: str,
        files: list[str],
    ) -> bool:
        """Return whether current workspace matches target tree for files."""
        if not files:
            return True
        if not await self._stage_all_locked():
            return False

        code, _, stderr = await self._run_git(
            "diff",
            "--cached",
            "--quiet",
            target_hash,
            "--",
            *files,
        )
        if code == 0:
            return True
        if code == 1:
            return False
        logger.warning("Failed to validate rollback divergence: %s", stderr)
        return False

    async def _path_exists_in_tree_locked(
        self,
        target_hash: str,
        file_path: str,
    ) -> bool:
        """Return whether ``file_path`` exists in ``target_hash``."""
        code, stdout, _ = await self._run_git(
            "ls-tree",
            target_hash,
            "--",
            file_path,
        )
        return code == 0 and bool(stdout.strip())

    async def _revert_locked(
        self,
        target_hash: str,
        files: list[str],
    ) -> bool:
        """Restore ``files`` to the state stored in ``target_hash``."""
        success = True
        for file_path in files:
            logger.info(
                "Reverting %s to state from %s",
                file_path,
                target_hash,
            )
            code, _, _ = await self._run_git(
                "checkout",
                target_hash,
                "--",
                file_path,
            )
            if code == 0:
                continue

            if await self._path_exists_in_tree_locked(target_hash, file_path):
                logger.warning(
                    "Failed to checkout %s from %s",
                    file_path,
                    target_hash,
                )
                success = False
                continue

            full_path = self.workspace_dir / file_path
            if not full_path.exists():
                continue

            try:
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                else:
                    full_path.unlink()
            except OSError as exc:
                logger.warning(
                    "Failed to delete %s: %s",
                    file_path,
                    exc,
                )
                success = False
        return success

    async def _load_history_locked(self) -> list[RollbackEntry]:
        if not self.history_file.exists():
            return []
        try:
            with open(
                self.history_file,
                "r",
                encoding="utf-8",
            ) as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load rollback history: %s", exc)
            return []
        if not isinstance(payload, list):
            logger.warning(
                "Rollback history is not a list, ignoring: %s",
                self.history_file,
            )
            return []

        valid_entries: list[RollbackEntry] = []
        invalid_count = 0
        for entry in payload:
            if not isinstance(entry, dict):
                invalid_count += 1
                continue
            try:
                valid_entries.append(RollbackEntry.from_dict(entry))
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "Skipping invalid rollback history entry in %s: %s",
                    self.history_file,
                    exc,
                )
                invalid_count += 1

        if invalid_count:
            logger.warning(
                "Skipped %s invalid rollback history entr%s in %s",
                invalid_count,
                "y" if invalid_count == 1 else "ies",
                self.history_file,
            )
        return valid_entries

    async def _save_history_locked(
        self,
        history: list[RollbackEntry],
    ) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=self.history_file.parent,
                prefix=f".{self.history_file.stem}_",
                suffix=self.history_file.suffix,
                delete=False,
                encoding="utf-8",
            ) as handle:
                json.dump(
                    [entry.to_dict() for entry in history],
                    handle,
                    indent=2,
                    ensure_ascii=False,
                )
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            temp_path.replace(self.history_file)
        except OSError as exc:
            logger.warning("Failed to save rollback history: %s", exc)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _latest_applied(
        history: list[RollbackEntry],
    ) -> RollbackEntry | None:
        applied = [entry for entry in history if entry.status == "applied"]
        return applied[-1] if applied else None

    @staticmethod
    def _latest_undone(
        history: list[RollbackEntry],
    ) -> RollbackEntry | None:
        undone = [entry for entry in history if entry.status == "undone"]
        return undone[0] if undone else None

    async def init(self) -> None:
        """Initialize the internal git-dir and exclusions."""
        async with self._workspace_lock():
            if await self._bootstrap_git_dir_locked():
                self._write_excludes_locked()

    async def track(self) -> str | None:
        """Take a snapshot of the current workspace."""
        await self.init()
        async with self._workspace_lock():
            return await self._track_locked()

    async def patch(self, base_hash: str) -> list[str]:
        """Compute file paths changed since ``base_hash``."""
        await self.init()
        async with self._workspace_lock():
            return await self._patch_locked(base_hash)

    async def revert(self, target_hash: str, files: list[str]) -> bool:
        """Revert the specified files to their state in ``target_hash``."""
        if not files:
            return True

        await self.init()
        async with self._workspace_lock():
            return await self._revert_locked(target_hash, files)

    async def record_history_if_changed(
        self,
        session_id: str,
        before_hash: str | None,
    ) -> RollbackEntry | None:
        """Persist a linear rollback entry when workspace files changed."""
        if not before_hash:
            return None

        await self.init()
        async with self._workspace_lock():
            after_hash = await self._track_locked()
            if not after_hash or after_hash == before_hash:
                return None

            files = await self._patch_locked(before_hash)
            if not files:
                return None

            history = await self._load_history_locked()
            history = [entry for entry in history if entry.status == "applied"]
            new_entry = RollbackEntry(
                id=f"rev_{len(history) + 1}_{int(time.time())}",
                session_id=session_id,
                before_hash=before_hash,
                after_hash=after_hash,
                files=files,
                created_at=time.time(),
                status="applied",
            )
            history.append(new_entry)
            await self._save_history_locked(history)
            return new_entry

    async def add_history_entry(
        self,
        session_id: str,
        before_hash: str,
        after_hash: str,
        files: list[str],
    ) -> None:
        """Add a new applied entry to the rollback history."""
        await self.init()
        async with self._workspace_lock():
            history = await self._load_history_locked()
            history = [entry for entry in history if entry.status == "applied"]
            history.append(
                RollbackEntry(
                    id=f"rev_{len(history) + 1}_{int(time.time())}",
                    session_id=session_id,
                    before_hash=before_hash,
                    after_hash=after_hash,
                    files=files,
                    created_at=time.time(),
                    status="applied",
                ),
            )
            await self._save_history_locked(history)

    async def get_latest_applied(self) -> RollbackEntry | None:
        """Get the most recent applied entry."""
        await self.init()
        async with self._workspace_lock():
            return self._latest_applied(await self._load_history_locked())

    async def get_latest_undone(self) -> RollbackEntry | None:
        """Get the next redo entry from the linear history."""
        await self.init()
        async with self._workspace_lock():
            return self._latest_undone(await self._load_history_locked())

    async def mark_undone(self, entry_id: str) -> None:
        """Mark a specific entry as undone."""
        await self.init()
        async with self._workspace_lock():
            history = await self._load_history_locked()
            for entry in history:
                if entry.id == entry_id:
                    entry.status = "undone"
                    break
            await self._save_history_locked(history)

    async def mark_applied(self, entry_id: str) -> None:
        """Mark a specific entry as applied."""
        await self.init()
        async with self._workspace_lock():
            history = await self._load_history_locked()
            for entry in history:
                if entry.id == entry_id:
                    entry.status = "applied"
                    break
            await self._save_history_locked(history)

    async def undo_latest(self) -> tuple[str, RollbackEntry | None]:
        """Undo the latest applied workspace change atomically."""
        await self.init()
        async with self._workspace_lock():
            history = await self._load_history_locked()
            entry = self._latest_applied(history)
            if entry is None:
                return _UNDO_EMPTY, None

            if not await self._files_match_tree_locked(
                entry.after_hash,
                entry.files,
            ):
                return _UNDO_DIVERGED, entry

            if not await self._revert_locked(entry.before_hash, entry.files):
                return _UNDO_FAILED, entry

            for item in history:
                if item.id == entry.id:
                    item.status = "undone"
                    break
            await self._save_history_locked(history)
            return _UNDO_OK, entry

    async def redo_latest(self) -> tuple[str, RollbackEntry | None]:
        """Redo the next undone workspace change atomically."""
        await self.init()
        async with self._workspace_lock():
            history = await self._load_history_locked()
            entry = self._latest_undone(history)
            if entry is None:
                return _UNDO_EMPTY, None

            if not await self._files_match_tree_locked(
                entry.before_hash,
                entry.files,
            ):
                return _UNDO_DIVERGED, entry

            if not await self._revert_locked(entry.after_hash, entry.files):
                return _UNDO_FAILED, entry

            for item in history:
                if item.id == entry.id:
                    item.status = "applied"
                    break
            await self._save_history_locked(history)
            return _UNDO_OK, entry
