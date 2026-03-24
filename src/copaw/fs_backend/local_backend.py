# -*- coding: utf-8 -*-
"""Local File System Backend Implementation."""

import asyncio
import shutil
from pathlib import Path
from typing import Callable, List, Optional

from .fs_backend import (
    FileSystemBackend,
    FileInfo,
    FileChange,
    OperationResult,
)


class LocalFileSystemBackend(FileSystemBackend):
    """Local file system implementation using standard Python libraries."""

    def __init__(self, working_dir: Optional[str] = None):
        """Initialize local backend.

        Args:
            working_dir: Working directory for relative paths.
        """
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self._watchers: List[asyncio.Task] = []

    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to working directory."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self.working_dir / p

    async def read_file(self, path: str) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return OperationResult(
                    success=False,
                    error_message=f"File not found: {path}"
                )
            if not resolved.is_file():
                return OperationResult(
                    success=False,
                    error_message=f"Not a file: {path}"
                )
            content = await asyncio.to_thread(resolved.read_text, encoding='utf-8')
            return OperationResult(success=True, data=content)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to read file: {e}"
            )

    async def write_file(self, path: str, content: str) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(resolved.write_text, content, encoding='utf-8')
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to write file: {e}"
            )

    async def delete_file(self, path: str) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return OperationResult(
                    success=False,
                    error_message=f"File not found: {path}"
                )
            if resolved.is_file():
                await asyncio.to_thread(resolved.unlink)
            elif resolved.is_dir():
                await asyncio.to_thread(shutil.rmtree, resolved)
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to delete: {e}"
            )

    async def create_directory(self, path: str) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            await asyncio.to_thread(resolved.mkdir, parents=True, exist_ok=True)
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to create directory: {e}"
            )

    async def list_directory(self, path: str) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return OperationResult(
                    success=False,
                    error_message=f"Directory not found: {path}"
                )
            if not resolved.is_dir():
                return OperationResult(
                    success=False,
                    error_message=f"Not a directory: {path}"
                )
            entries = []
            for item in resolved.iterdir():
                stat = item.stat()
                entries.append(FileInfo(
                    name=item.name,
                    path=str(item),
                    is_directory=item.is_dir(),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                ))
            return OperationResult(success=True, data=entries)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to list directory: {e}"
            )

    async def get_file_info(self, path: str) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return OperationResult(
                    success=True,
                    data=FileInfo(
                        name=resolved.name,
                        path=str(resolved),
                        is_directory=False,
                        exists=False
                    )
                )
            stat = resolved.stat()
            return OperationResult(
                success=True,
                data=FileInfo(
                    name=resolved.name,
                    path=str(resolved),
                    is_directory=resolved.is_dir(),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    exists=True
                )
            )
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to get file info: {e}"
            )

    async def exists(self, path: str) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            return OperationResult(success=True, data=resolved.exists())
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to check existence: {e}"
            )

    async def move_file(self, source: str, destination: str) -> OperationResult:
        try:
            src = self._resolve_path(source)
            dst = self._resolve_path(destination)
            if not src.exists():
                return OperationResult(
                    success=False,
                    error_message=f"Source not found: {source}"
                )
            dst.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, src, dst)
            return OperationResult(success=True)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to move: {e}"
            )

    async def search_files(self, path: str, pattern: str) -> OperationResult:
        try:
            base = self._resolve_path(path)
            if not base.exists():
                return OperationResult(
                    success=False,
                    error_message=f"Path not found: {path}"
                )
            matches = []
            if base.is_file():
                if base.match(pattern):
                    matches.append(str(base))
            else:
                for item in base.rglob(pattern):
                    matches.append(str(item))
            return OperationResult(success=True, data=matches)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to search files: {e}"
            )

    async def watch_directory(
        self,
        path: str,
        callback: Callable[[List[FileChange]], None],
        interval: float = 2.0
    ) -> OperationResult:
        try:
            resolved = self._resolve_path(path)
            last_state = {}
            if resolved.exists() and resolved.is_dir():
                for item in resolved.rglob('*'):
                    try:
                        stat = item.stat()
                        last_state[str(item)] = stat.st_mtime
                    except OSError:
                        pass

            async def poll_loop():
                nonlocal last_state
                while True:
                    await asyncio.sleep(interval)
                    try:
                        current_state = {}
                        changes = []
                        if resolved.exists() and resolved.is_dir():
                            for item in resolved.rglob('*'):
                                try:
                                    stat = item.stat()
                                    current_state[str(item)] = stat.st_mtime
                                    if str(item) not in last_state:
                                        changes.append(FileChange(
                                            path=str(item),
                                            event_type='created',
                                            is_directory=item.is_dir()
                                        ))
                                    elif stat.st_mtime != last_state[str(item)]:
                                        changes.append(FileChange(
                                            path=str(item),
                                            event_type='modified',
                                            is_directory=item.is_dir()
                                        ))
                                except OSError:
                                    pass
                            for prev_path in last_state:
                                if prev_path not in current_state:
                                    changes.append(FileChange(
                                        path=prev_path,
                                        event_type='deleted',
                                        is_directory=False
                                    ))
                        if changes:
                            callback(changes)
                        last_state = current_state
                    except Exception:
                        pass

            task = asyncio.create_task(poll_loop())
            self._watchers.append(task)
            return OperationResult(success=True, data=task)
        except Exception as e:
            return OperationResult(
                success=False,
                error_message=f"Failed to watch directory: {e}"
            )

    async def close(self) -> None:
        for watcher in self._watchers:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        self._watchers.clear()
