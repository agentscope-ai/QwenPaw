# -*- coding: utf-8 -*-
"""Local filesystem backend: runs commands and file ops in the local process.

This is the default backend when no sandbox is configured.
"""

import asyncio
import logging
import os
import shlex
import sys
from pathlib import Path
from typing import List

from .fs_backend import CommandResult, FileEntry, FileSystemBackend

logger = logging.getLogger(__name__)


class LocalBackend(FileSystemBackend):
    """Backend that executes everything locally."""

    def __init__(self, working_dir: str = "/home/user") -> None:
        self._working_dir = working_dir

    async def run_command(
        self, command: str, timeout: int = 60
    ) -> CommandResult:
        cmd = (command or "").strip()
        if not cmd:
            return CommandResult(
                exit_code=-1, stdout="", stderr="Error: No command provided."
            )

        env = os.environ.copy()
        python_bin_dir = str(Path(sys.executable).parent)
        existing_path = env.get("PATH", "")
        env["PATH"] = (
            f"{python_bin_dir}{os.pathsep}{existing_path}"
            if existing_path
            else python_bin_dir
        )

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return CommandResult(
                exit_code=proc.returncode or 0,
                stdout=(stdout or b"")
                .decode("utf-8", errors="replace")
                .rstrip("\n"),
                stderr=(stderr or b"")
                .decode("utf-8", errors="replace")
                .rstrip("\n"),
            )
        except asyncio.TimeoutError:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2)
            except Exception:
                proc.kill()
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s.",
            )
        except Exception as exc:
            return CommandResult(exit_code=-1, stdout="", stderr=str(exc))

    async def run_python(
        self, code: str, timeout: float = 300
    ) -> CommandResult:
        if not (code or "").strip():
            return CommandResult(
                exit_code=-1, stdout="", stderr="Error: No code provided."
            )
        # Write to temp file and execute
        tmp_path = "/tmp/_copaw_local_exec.py"
        try:
            Path(tmp_path).write_text(code, encoding="utf-8")
        except Exception as exc:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Failed to write temp file: {exc}",
            )
        return await self.run_command(
            f"python3 {shlex.quote(tmp_path)}", timeout=int(timeout)
        )

    async def read_file(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return path.read_text(encoding="utf-8", errors="replace")

    async def write_file(self, file_path: str, content: str) -> None:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    async def list_files(
        self, dir_path: str = "/home/user", depth: int = 1
    ) -> List[FileEntry]:
        root = Path(dir_path)
        if not root.exists():
            raise RuntimeError(f"Directory not found: {dir_path}")
        entries = []
        for item in sorted(root.iterdir()):
            entries.append(
                FileEntry(
                    path=str(item),
                    is_dir=item.is_dir(),
                    size=item.stat().st_size if item.is_file() else None,
                )
            )
        return entries
