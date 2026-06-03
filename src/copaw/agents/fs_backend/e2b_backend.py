# -*- coding: utf-8 -*-
"""E2B sandbox backend — routes file system operations through E2BSandboxHandle.

Uses the gRPC-Web / HTTP protocol via E2BSandboxHandle to execute commands
and manage files in a remote sandbox Pod.
"""

import logging
import shlex
from typing import List

from .fs_backend import CommandResult, FileEntry, FileSystemBackend

logger = logging.getLogger(__name__)


class E2BBackend(FileSystemBackend):
    """Backend that routes operations through an E2BSandboxHandle."""

    def __init__(self, sandbox) -> None:
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
            exit_code, stdout, stderr = await self._sandbox.run_command(
                cmd, timeout=timeout
            )
        except Exception as exc:
            logger.error(
                "e2b_backend: command failed in sandbox %s: %s",
                self.sandbox_id,
                exc,
            )
            return CommandResult(exit_code=1, stdout="", stderr=str(exc))

        return CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    async def run_python(
        self, code: str, timeout: int = 300
    ) -> CommandResult:
        escaped = code.replace("\\", "\\\\").replace("'", "'\\''")
        cmd = f"python3 -c '{escaped}'"
        return await self.run_command(cmd, timeout=timeout)

    async def read_file(self, file_path: str) -> str:
        logger.info(
            "e2b_backend: read_file in sandbox %s: %s",
            self.sandbox_id,
            file_path,
        )
        try:
            data = await self._sandbox.read_file(file_path)
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")
            return data
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to read {file_path}: {exc}") from exc

    async def write_file(self, file_path: str, content: str) -> None:
        logger.info(
            "e2b_backend: write_file in sandbox %s: %s (%d chars)",
            self.sandbox_id,
            file_path,
            len(content),
        )
        await self._sandbox.run_command(
            f"mkdir -p $(dirname {shlex.quote(file_path)})"
        )
        await self._sandbox.write_file(file_path, content)

    async def list_files(
        self, dir_path: str = "/home/user", depth: int = 1
    ) -> List[FileEntry]:
        logger.info(
            "e2b_backend: list_files in sandbox %s: %s",
            self.sandbox_id,
            dir_path,
        )
        try:
            entries = await self._sandbox.list_dir(dir_path)
            result = []
            for e in entries:
                name = e.get("name", "")
                if name in (".", ".."):
                    continue
                is_dir = e.get("type", "") == "FILE_TYPE_DIRECTORY"
                size = int(e.get("size", 0))
                result.append(
                    FileEntry(
                        path=e.get("path", f"{dir_path}/{name}"),
                        is_dir=is_dir,
                        size=size,
                    )
                )
            return result
        except Exception as exc:
            logger.error(
                "e2b_backend: list_files failed: %s", exc, exc_info=True
            )
            return []

    async def download_file(self, file_path: str) -> bytes:
        return await self._sandbox.read_file(file_path)
