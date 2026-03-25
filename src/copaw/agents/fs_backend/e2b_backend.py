# -*- coding: utf-8 -*-
"""E2B sandbox backend: routes file system operations through E2B SDK.

Wraps an e2b.Sandbox instance to implement FileSystemBackend.
All SDK calls are synchronous, so we use asyncio.to_thread.
"""

import asyncio
import logging
import shlex
from typing import List

from .fs_backend import CommandResult, FileEntry, FileSystemBackend

logger = logging.getLogger(__name__)

_REMOTE_TMP_SCRIPT = "/tmp/_copaw_exec.py"


class E2BBackend(FileSystemBackend):
    """Backend that routes operations through an E2B sandbox instance."""

    def __init__(self, sandbox: object) -> None:
        """
        Args:
            sandbox: An e2b.Sandbox instance.
        """
        self._sandbox = sandbox

    def is_cloud(self) -> bool:
        return True

    @property
    def sandbox_id(self) -> str:
        return getattr(self._sandbox, "sandbox_id", "?")

    async def run_command(
        self, command: str, timeout: int = 60
    ) -> CommandResult:
        cmd = (command or "").strip()
        if not cmd:
            return CommandResult(
                exit_code=-1, stdout="", stderr="Error: No command provided."
            )

        logger.info(
            "e2b_backend: run_command in sandbox %s: %s",
            self.sandbox_id,
            cmd[:200],
        )
        try:
            result = await asyncio.to_thread(
                self._sandbox.commands.run, cmd, timeout=timeout
            )
        except Exception as exc:
            logger.error(
                "e2b_backend: command failed in sandbox %s: %s",
                self.sandbox_id,
                exc,
            )
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Sandbox command failed: {exc}",
            )

        return CommandResult(
            exit_code=result.exit_code if result.exit_code is not None else 0,
            stdout=(result.stdout or "").rstrip("\n"),
            stderr=(result.stderr or "").rstrip("\n"),
        )

    async def run_python(
        self, code: str, timeout: float = 300
    ) -> CommandResult:
        if not (code or "").strip():
            return CommandResult(
                exit_code=-1, stdout="", stderr="Error: No code provided."
            )

        logger.info(
            "e2b_backend: run_python in sandbox %s (%d chars)",
            self.sandbox_id,
            len(code),
        )
        try:

            def _run():
                self._sandbox.files.write(_REMOTE_TMP_SCRIPT, code)
                return self._sandbox.commands.run(
                    f"python3 {shlex.quote(_REMOTE_TMP_SCRIPT)}",
                    timeout=int(timeout),
                )

            result = await asyncio.to_thread(_run)
        except Exception as exc:
            logger.error(
                "e2b_backend: python exec failed in sandbox %s: %s",
                self.sandbox_id,
                exc,
            )
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Sandbox Python execution failed: {exc}",
            )

        return CommandResult(
            exit_code=result.exit_code if result.exit_code is not None else 0,
            stdout=(result.stdout or "").rstrip("\n"),
            stderr=(result.stderr or "").rstrip("\n"),
        )

    async def read_file(self, file_path: str) -> str:
        logger.info(
            "e2b_backend: read_file '%s' from sandbox %s",
            file_path,
            self.sandbox_id,
        )
        try:
            content = await asyncio.to_thread(
                self._sandbox.files.read, file_path
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to read '{file_path}': {exc}") from exc

        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content) if content is not None else ""

    async def write_file(self, file_path: str, content: str) -> None:
        logger.info(
            "e2b_backend: write_file '%s' in sandbox %s (%d bytes)",
            file_path,
            self.sandbox_id,
            len(content or ""),
        )
        try:
            await asyncio.to_thread(
                self._sandbox.files.write, file_path, content or ""
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to write '{file_path}': {exc}"
            ) from exc

    async def list_files(
        self, dir_path: str = "/home/user", depth: int = 1
    ) -> List[FileEntry]:
        logger.info(
            "e2b_backend: list_files '%s' (depth=%d) in sandbox %s",
            dir_path,
            depth,
            self.sandbox_id,
        )
        try:
            try:
                entries = await asyncio.to_thread(
                    self._sandbox.files.list, dir_path, depth
                )
            except TypeError:
                entries = await asyncio.to_thread(
                    self._sandbox.files.list, dir_path
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to list '{dir_path}': {exc}") from exc

        result = []
        for entry in entries:
            entry_path = getattr(entry, "path", None) or getattr(
                entry, "name", str(entry)
            )
            try:
                from e2b.sandbox.filesystem.filesystem import FileType

                is_dir = getattr(entry, "type", None) == FileType.DIR
            except ImportError:
                is_dir = False
            size = getattr(entry, "size", None)
            result.append(
                FileEntry(
                    path=str(entry_path),
                    is_dir=is_dir,
                    size=size,
                )
            )
        return result

    async def download_file(self, file_path: str) -> bytes:
        """Download file as bytes (E2B-specific)."""
        try:
            content = await asyncio.to_thread(
                self._sandbox.files.read, file_path, format="bytes"
            )
        except TypeError:
            content = await asyncio.to_thread(
                self._sandbox.files.read, file_path
            )
            if isinstance(content, str):
                content = content.encode("utf-8")
        return (
            content
            if isinstance(content, bytes)
            else str(content).encode("utf-8")
        )
