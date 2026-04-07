import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class RollbackEntry:
    id: str
    session_id: str
    before_hash: str
    after_hash: str
    files: List[str]
    created_at: float
    status: str  # 'applied' or 'undone'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RollbackEntry":
        return cls(**data)


class SnapshotService:
    """Provides workspace-level file snapshot and rollback using git-dir and work-tree."""

    _locks: Dict[Path, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.rollback_dir = self.workspace_dir / ".copaw" / "rollback"
        self.git_dir = self.rollback_dir / "git"
        self.history_file = self.rollback_dir / "history.json"

        # Git config to prevent interference with user's global settings
        self._git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "",
            "GIT_CONFIG_SYSTEM": "",
            "GIT_AUTHOR_NAME": "CoPaw Snapshot Service",
            "GIT_AUTHOR_EMAIL": "copaw@localhost",
            "GIT_COMMITTER_NAME": "CoPaw Snapshot Service",
            "GIT_COMMITTER_EMAIL": "copaw@localhost",
        }

    async def _run_git(self, *args: str) -> Tuple[int, str, str]:
        """Run a git command using the separate git-dir and work-tree."""
        cmd = [
            "git",
            "--git-dir",
            str(self.git_dir),
            "--work-tree",
            str(self.workspace_dir),
            "-c", "core.autocrlf=false",
            "-c", "core.longpaths=true",
            "-c", "core.symlinks=true",
            "-c", "core.quotepath=false",
            *args,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._git_env,
            cwd=str(self.workspace_dir),
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.debug(
                f"git {' '.join(args)} failed with {process.returncode}:\n"
                f"{stderr.decode()}"
            )

        return process.returncode or 0, stdout.decode().strip(), stderr.decode().strip()

    async def init(self) -> None:
        """Initialize the git-dir if it doesn't exist and set up exclusions."""
        async with self._locks[self.workspace_dir]:
            if not self.git_dir.exists():
                self.git_dir.parent.mkdir(parents=True, exist_ok=True)
                # init as a bare repo
                await self._run_git("init", "--bare", str(self.git_dir))

            # set up info/exclude
            info_dir = self.git_dir / "info"
            info_dir.mkdir(exist_ok=True)

            # Exclude CoPaw internal files and common noise
            exclusions = [
                ".copaw/",
                "sessions/",
                ".git/",
                "node_modules/",
                "venv/",
                ".venv/",
                "__pycache__/",
                ".pytest_cache/",
            ]

            with open(info_dir / "exclude", "w") as f:
                f.write("\n".join(exclusions) + "\n")

    async def track(self) -> Optional[str]:
        """Take a snapshot of the current workspace and return the tree hash."""
        await self.init()
        async with self._locks[self.workspace_dir]:
            # Add all files (respecting info/exclude)
            ret, _, _ = await self._run_git("add", "--sparse", ".")
            if ret != 0:
                logger.warning("Failed to add files to snapshot")
                return None

            # Write the tree object and get its hash
            ret, stdout, stderr = await self._run_git("write-tree")
            if ret != 0:
                logger.warning(f"Failed to write tree: {stderr}")
                return None

            return stdout

    async def patch(self, base_hash: str) -> List[str]:
        """Compute the files changed since the base_hash. Returns a list of file paths."""
        async with self._locks[self.workspace_dir]:
            # Ensure the index is up-to-date
            await self._run_git("add", "--sparse", ".")

            # Diff against the base hash
            ret, stdout, stderr = await self._run_git(
                "diff", "--cached", "--no-ext-diff", "--name-only", base_hash, "--", "."
            )

            if ret != 0:
                logger.warning(f"Failed to get patch diff: {stderr}")
                return []

            files = [f.strip() for f in stdout.split("\n") if f.strip()]
            return files

    async def revert(self, target_hash: str, files: List[str]) -> bool:
        """Revert the specified files to their state in target_hash."""
        if not files:
            return True

        async with self._locks[self.workspace_dir]:
            success = True
            for file_path in files:
                logger.info(f"Reverting {file_path} to state from {target_hash}")

                # Try to checkout the file from the target tree
                ret, _, _ = await self._run_git("checkout", target_hash, "--", file_path)

                if ret != 0:
                    # Checkout failed, which usually means the file didn't exist in target_hash
                    # Verify it didn't exist
                    ret_ls, stdout_ls, _ = await self._run_git("ls-tree", target_hash, "--", file_path)

                    if ret_ls == 0 and stdout_ls.strip():
                        # File did exist, checkout just failed for some reason
                        logger.warning(f"Failed to checkout {file_path} from {target_hash}")
                        success = False
                    else:
                        # File did not exist in the target snapshot, so we should delete it
                        logger.info(f"File {file_path} did not exist in {target_hash}, deleting it")
                        full_path = self.workspace_dir / file_path
                        if full_path.exists():
                            try:
                                if full_path.is_dir():
                                    shutil.rmtree(full_path)
                                else:
                                    full_path.unlink()
                            except Exception as e:
                                logger.warning(f"Failed to delete {file_path}: {e}")
                                success = False

            return success

    # --- History Management ---

    async def _load_history(self) -> List[RollbackEntry]:
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
                return [RollbackEntry.from_dict(entry) for entry in data]
        except Exception as e:
            logger.warning(f"Failed to load rollback history: {e}")
            return []

    async def _save_history(self, history: List[RollbackEntry]) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.history_file, "w") as f:
                json.dump([entry.to_dict() for entry in history], f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save rollback history: {e}")

    async def add_history_entry(
        self, session_id: str, before_hash: str, after_hash: str, files: List[str]
    ) -> None:
        """Add a new applied entry to the rollback history."""
        # Note: History management is now inside its own lock block
        # to prevent deadlock since _load_history and _save_history don't use locks.
        # But callers must make sure they don't hold the outer lock.
        async with self._locks[self.workspace_dir]:
            history = await self._load_history()

            # Truncate any 'undone' entries since we are adding a new linear commit
            # We want to keep everything before the current 'applied' tail.
            new_history = []
            for h in history:
                if h.status == "applied":
                    new_history.append(h)
                else:
                    # found first undone, we discard it and everything after
                    break

            entry_id = f"rev_{len(new_history) + 1}_{int(time.time())}"
            new_entry = RollbackEntry(
                id=entry_id,
                session_id=session_id,
                before_hash=before_hash,
                after_hash=after_hash,
                files=files,
                created_at=time.time(),
                status="applied",
            )

            new_history.append(new_entry)
            await self._save_history(new_history)

    async def get_latest_applied(self) -> Optional[RollbackEntry]:
        """Get the most recent applied entry (for undo)."""
        async with self._locks[self.workspace_dir]:
            history = await self._load_history()
            applied = [h for h in history if h.status == "applied"]
            return applied[-1] if applied else None

    async def get_latest_undone(self) -> Optional[RollbackEntry]:
        """Get the most recent undone entry (for redo)."""
        async with self._locks[self.workspace_dir]:
            history = await self._load_history()
            undone = [h for h in history if h.status == "undone"]
            return undone[0] if undone else None

    async def mark_undone(self, entry_id: str) -> None:
        """Mark a specific entry as undone."""
        async with self._locks[self.workspace_dir]:
            history = await self._load_history()
            for entry in history:
                if entry.id == entry_id:
                    entry.status = "undone"
                    break
            await self._save_history(history)

    async def mark_applied(self, entry_id: str) -> None:
        """Mark a specific entry as applied."""
        async with self._locks[self.workspace_dir]:
            history = await self._load_history()
            for entry in history:
                if entry.id == entry_id:
                    entry.status = "applied"
                    break
            await self._save_history(history)
