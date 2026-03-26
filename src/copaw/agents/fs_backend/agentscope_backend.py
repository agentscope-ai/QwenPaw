# -*- coding: utf-8 -*-
"""AgentScope sandbox backend.

Routes file system operations through sandbox-manager HTTP API.
Wraps an AgentscopeSandboxHandle to implement FileSystemBackend.
All operations go through the /call_tool endpoint.
"""

import logging
from typing import Any, Dict, List

from .fs_backend import CommandResult, FileEntry, FileSystemBackend

logger = logging.getLogger(__name__)


def _parse_call_tool_result(result: Dict[str, Any]) -> CommandResult:
    """Parse sandbox-manager /call_tool response into CommandResult."""
    data = result.get("data", result)
    if isinstance(data, dict):
        content_list = data.get("content")
        if isinstance(content_list, list):
            stdout = ""
            stderr = ""
            exit_code = 0
            for item in content_list:
                desc = (item.get("description") or "").lower()
                text = item.get("text", "")
                if desc == "stdout":
                    stdout = text
                elif desc == "stderr":
                    stderr = text
                elif desc == "returncode":
                    try:
                        exit_code = int(text)
                    except (ValueError, TypeError):
                        exit_code = 0
            return CommandResult(
                exit_code=exit_code,
                stdout=stdout.rstrip("\n"),
                stderr=stderr.rstrip("\n"),
            )
        else:
            return CommandResult(
                exit_code=int(
                    data.get(
                        "exit_code",
                        data.get("returncode", 0),
                    )
                    or 0
                ),
                stdout=(
                    data.get("stdout", data.get("output", "")) or ""
                ).rstrip("\n"),
                stderr=(data.get("stderr", "") or "").rstrip("\n"),
            )
    elif isinstance(data, str):
        return CommandResult(exit_code=0, stdout=data.rstrip("\n"), stderr="")
    else:
        return CommandResult(
            exit_code=0, stdout=str(data).rstrip("\n"), stderr=""
        )


class AgentscopeBackend(FileSystemBackend):
    """Backend routing ops through sandbox-manager /call_tool."""

    def __init__(self, sandbox_handle: object) -> None:
        """Init.

        Args:
            sandbox_handle: AgentscopeSandboxHandle with call_tool().
        """
        self._handle = sandbox_handle

    def is_cloud(self) -> bool:
        return True

    @property
    def sandbox_id(self) -> str:
        return getattr(self._handle, "sandbox_id", "?")

    async def run_command(
        self, command: str, timeout: int = 60
    ) -> CommandResult:
        cmd = (command or "").strip()
        if not cmd:
            return CommandResult(
                exit_code=-1, stdout="", stderr="Error: No command provided."
            )

        logger.info(
            "agentscope_backend: run_command in sandbox %s: %s",
            self.sandbox_id,
            cmd[:200],
        )
        try:
            result = await self._handle.call_tool(
                tool_name="run_shell_command",
                arguments={"command": cmd},
                timeout=timeout + 10,
            )
        except Exception as exc:
            logger.error(
                "agentscope_backend: command failed in sandbox %s: %s",
                self.sandbox_id,
                exc,
            )
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Sandbox command failed: {exc}",
            )

        return _parse_call_tool_result(result)

    async def run_python(
        self, code: str, timeout: float = 300
    ) -> CommandResult:
        if not (code or "").strip():
            return CommandResult(
                exit_code=-1, stdout="", stderr="Error: No code provided."
            )

        logger.info(
            "agentscope_backend: run_python in sandbox %s (%d chars)",
            self.sandbox_id,
            len(code),
        )
        try:
            result = await self._handle.call_tool(
                tool_name="run_ipython_cell",
                arguments={"code": code},
                timeout=timeout + 10,
            )
        except Exception as exc:
            logger.error(
                "agentscope_backend: python exec failed in sandbox %s: %s",
                self.sandbox_id,
                exc,
            )
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Sandbox Python execution failed: {exc}",
            )

        return _parse_call_tool_result(result)

    async def read_file(self, file_path: str) -> str:
        logger.info(
            "agentscope_backend: read_file '%s' from sandbox %s",
            file_path,
            self.sandbox_id,
        )
        try:
            result = await self._handle.call_tool(
                tool_name="run_shell_command",
                arguments={"command": f"cat {file_path}"},
                timeout=30,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to read '{file_path}': {exc}") from exc

        cr = _parse_call_tool_result(result)
        if cr.exit_code != 0:
            raise RuntimeError(f"Failed to read '{file_path}': {cr.stderr}")
        return cr.stdout

    async def write_file(self, file_path: str, content: str) -> None:
        logger.info(
            "agentscope_backend: write_file '%s' in sandbox %s",
            file_path,
            self.sandbox_id,
        )
        escaped_path = file_path.replace("'", "\\'")
        escaped_content = content.replace("\\", "\\\\").replace("'", "\\'")
        code = (
            "import os; "
            f"os.makedirs(os.path.dirname('{escaped_path}')"
            " or '.', exist_ok=True)\n"
            f"with open('{escaped_path}', 'w') as f:\n"
            f"    f.write('{escaped_content}')\n"
            "print('OK')"
        )
        try:
            result = await self._handle.call_tool(
                tool_name="run_ipython_cell",
                arguments={"code": code},
                timeout=30,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to write '{file_path}': {exc}"
            ) from exc

        cr = _parse_call_tool_result(result)
        if cr.exit_code != 0:
            raise RuntimeError(f"Failed to write '{file_path}': {cr.stderr}")

    async def list_files(
        self, dir_path: str = "/home/user", depth: int = 1
    ) -> List[FileEntry]:
        logger.info(
            "agentscope_backend: list_files '%s' in sandbox %s",
            dir_path,
            self.sandbox_id,
        )
        try:
            result = await self._handle.call_tool(
                tool_name="run_shell_command",
                arguments={"command": f"ls -la {dir_path}"},
                timeout=30,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to list '{dir_path}': {exc}") from exc

        cr = _parse_call_tool_result(result)
        if cr.exit_code != 0:
            raise RuntimeError(f"Failed to list '{dir_path}': {cr.stderr}")

        # Parse ls -la output into FileEntry objects
        entries = []
        for line in cr.stdout.splitlines():
            if not line or line.startswith("total"):
                continue
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            is_dir = parts[0].startswith("d")
            try:
                size = int(parts[4])
            except (ValueError, IndexError):
                size = None
            name = parts[8]
            if name in (".", ".."):
                continue
            full_path = f"{dir_path.rstrip('/')}/{name}"
            entries.append(FileEntry(path=full_path, is_dir=is_dir, size=size))
        return entries
