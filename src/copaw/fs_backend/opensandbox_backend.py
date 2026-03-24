# -*- coding: utf-8 -*-
"""OpenSandbox Cloud File System Backend Implementation.

This backend uses the OpenSandbox Python SDK to perform file operations
in a cloud sandbox environment. Requires an active OpenSandbox Sandbox instance.
"""

import asyncio
import logging
from typing import Any, Callable, List

from .fs_backend import (
    FileSystemBackend,
    FileInfo,
    FileChange,
    OperationResult,
)

logger = logging.getLogger(__name__)


class OpenSandboxFileSystemBackend(FileSystemBackend):
    """OpenSandbox cloud file system implementation.

    This backend delegates file operations to an OpenSandbox sandbox instance
    via its async Python SDK (``sandbox.files`` and ``sandbox.commands``).
    """

    def __init__(self, sandbox: Any):
        """Initialize OpenSandbox backend.

        Args:
            sandbox: An ``opensandbox.Sandbox`` instance (already created and
                running) that exposes ``.files`` and ``.commands`` services.
        """
        self.sandbox = sandbox
        self._watchers: List[asyncio.Task] = []

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    async def read_file(self, path: str) -> OperationResult:
        """Read file content from OpenSandbox filesystem."""
        try:
            content = await self.sandbox.files.read_file(path)
            return OperationResult(success=True, data=content)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to read file: {e}"
            )

    async def write_file(self, path: str, content: str) -> OperationResult:
        """Write content to OpenSandbox filesystem."""
        try:
            await self.sandbox.files.write_file(path, content)
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to write file: {e}"
            )

    async def delete_file(self, path: str) -> OperationResult:
        """Delete file from OpenSandbox filesystem."""
        try:
            await self.sandbox.files.delete_files([path])
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to delete file: {e}"
            )

    async def create_directory(self, path: str) -> OperationResult:
        """Create directory in OpenSandbox filesystem."""
        try:
            from opensandbox.models.filesystem import WriteEntry
            await self.sandbox.files.create_directories(
                [WriteEntry(path=path)]
            )
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to create directory: {e}"
            )

    async def list_directory(self, path: str) -> OperationResult:
        """List directory contents in OpenSandbox filesystem.

        Uses ``sandbox.files.search`` with pattern ``*`` scoped to *path*
        to emulate a single-level directory listing.
        """
        try:
            from opensandbox.models.filesystem import SearchEntry

            result = await self.sandbox.files.search(
                SearchEntry(path=path, pattern="*")
            )
            entries: List[FileInfo] = []
            for entry in result:
                # EntryInfo has: path, mode, owner, group, size, modified_at
                name = entry.path.rstrip("/").rsplit("/", 1)[-1]
                # Determine if directory by checking if mode indicates dir
                # or size is 0 (heuristic); rely on mode bits (dir = 0o40000)
                is_dir = (entry.mode & 0o40000) != 0
                mtime = (
                    entry.modified_at.timestamp()
                    if entry.modified_at
                    else 0.0
                )
                entries.append(FileInfo(
                    name=name,
                    path=entry.path,
                    is_directory=is_dir,
                    size=entry.size,
                    mtime=mtime,
                ))
            return OperationResult(success=True, data=entries)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to list directory: {e}"
            )

    async def get_file_info(self, path: str) -> OperationResult:
        """Get file/directory info from OpenSandbox filesystem."""
        try:
            info_map = await self.sandbox.files.get_file_info([path])
            if path in info_map:
                entry = info_map[path]
                is_dir = (entry.mode & 0o40000) != 0
                mtime = (
                    entry.modified_at.timestamp()
                    if entry.modified_at
                    else 0.0
                )
                name = path.rstrip("/").rsplit("/", 1)[-1]
                return OperationResult(
                    success=True,
                    data=FileInfo(
                        name=name,
                        path=path,
                        is_directory=is_dir,
                        size=entry.size,
                        mtime=mtime,
                        exists=True,
                    )
                )
            else:
                name = path.rstrip("/").rsplit("/", 1)[-1]
                return OperationResult(
                    success=True,
                    data=FileInfo(
                        name=name,
                        path=path,
                        is_directory=False,
                        exists=False,
                    )
                )
        except Exception as e:
            # Treat "not found" errors as exists=False
            name = path.rstrip("/").rsplit("/", 1)[-1]
            return OperationResult(
                success=True,
                data=FileInfo(
                    name=name,
                    path=path,
                    is_directory=False,
                    exists=False,
                )
            )

    async def exists(self, path: str) -> OperationResult:
        """Check if path exists in OpenSandbox filesystem."""
        try:
            info_result = await self.get_file_info(path)
            if info_result.success and info_result.data:
                return OperationResult(
                    success=True,
                    data=info_result.data.exists,
                )
            return OperationResult(success=True, data=False)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to check existence: {e}"
            )

    async def move_file(self, source: str, destination: str) -> OperationResult:
        """Move/rename file in OpenSandbox filesystem."""
        try:
            from opensandbox.models.filesystem import MoveEntry
            await self.sandbox.files.move_files(
                [MoveEntry(src=source, dest=destination)]
            )
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to move file: {e}"
            )

    async def search_files(self, path: str, pattern: str) -> OperationResult:
        """Search files in OpenSandbox filesystem."""
        try:
            from opensandbox.models.filesystem import SearchEntry

            result = await self.sandbox.files.search(
                SearchEntry(path=path, pattern=pattern)
            )
            matches = [entry.path for entry in result]
            return OperationResult(success=True, data=matches)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to search files: {e}"
            )

    # ------------------------------------------------------------------
    # Directory watching (polling-based)
    # ------------------------------------------------------------------

    async def watch_directory(
        self,
        path: str,
        callback: Callable[[List[FileChange]], None],
        interval: float = 2.0,
    ) -> OperationResult:
        """Watch directory for changes via polling.

        OpenSandbox does not provide a native watch API, so we poll
        ``search`` at *interval* seconds and compare snapshots.
        """
        try:
            from opensandbox.models.filesystem import SearchEntry

            last_state: dict[str, float] = {}

            # Initial scan
            try:
                entries = await self.sandbox.files.search(
                    SearchEntry(path=path, pattern="*")
                )
                for entry in entries:
                    mtime = (
                        entry.modified_at.timestamp()
                        if entry.modified_at
                        else 0.0
                    )
                    last_state[entry.path] = mtime
            except Exception:
                pass

            async def poll_loop():
                nonlocal last_state
                while True:
                    await asyncio.sleep(interval)
                    try:
                        current_state: dict[str, float] = {}
                        changes: List[FileChange] = []

                        entries = await self.sandbox.files.search(
                            SearchEntry(path=path, pattern="*")
                        )
                        for entry in entries:
                            mtime = (
                                entry.modified_at.timestamp()
                                if entry.modified_at
                                else 0.0
                            )
                            current_state[entry.path] = mtime
                            is_dir = (entry.mode & 0o40000) != 0

                            if entry.path not in last_state:
                                changes.append(FileChange(
                                    path=entry.path,
                                    event_type="created",
                                    is_directory=is_dir,
                                ))
                            elif mtime != last_state[entry.path]:
                                changes.append(FileChange(
                                    path=entry.path,
                                    event_type="modified",
                                    is_directory=is_dir,
                                ))

                        for prev_path in last_state:
                            if prev_path not in current_state:
                                changes.append(FileChange(
                                    path=prev_path,
                                    event_type="deleted",
                                    is_directory=False,
                                ))

                        if changes:
                            callback(changes)

                        last_state = current_state
                    except Exception as exc:
                        logger.debug("OpenSandbox watch poll error: %s", exc)

            task = asyncio.create_task(poll_loop())
            self._watchers.append(task)
            return OperationResult(success=True, data=task)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to watch directory: {e}"
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close OpenSandbox backend and stop watchers."""
        for watcher in self._watchers:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        self._watchers.clear()
