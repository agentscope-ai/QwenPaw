# -*- coding: utf-8 -*-
"""Abstract FileSystemBackend interface.

All sandbox backends (local, E2B, AgentScope) implement this interface.
Tools call these methods through the adapter singleton, making them
backend-agnostic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CommandResult:
    """Result of a shell command execution."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass
class FileEntry:
    """A single entry in a directory listing."""

    path: str
    is_dir: bool
    size: Optional[int] = None


class FileSystemBackend(ABC):
    """Abstract interface for file system operations.

    Concrete implementations:
      - LocalBackend: runs on the local filesystem
      - E2BBackend: routes through E2B SDK
      - AgentscopeBackend: routes through sandbox-manager HTTP API
    """

    @abstractmethod
    async def run_command(
        self, command: str, timeout: int = 60
    ) -> CommandResult:
        """Execute a shell command.

        Args:
            command: Shell command string.
            timeout: Max seconds to wait.

        Returns:
            CommandResult with exit_code, stdout, stderr.
        """

    @abstractmethod
    async def run_python(
        self, code: str, timeout: float = 300
    ) -> CommandResult:
        """Execute Python code.

        Args:
            code: Python source code.
            timeout: Max seconds to wait.

        Returns:
            CommandResult with exit_code, stdout, stderr.
        """

    @abstractmethod
    async def read_file(self, file_path: str) -> str:
        """Read file contents.

        Args:
            file_path: Absolute path to the file.

        Returns:
            File contents as string.

        Raises:
            FileNotFoundError: If file does not exist.
            RuntimeError: On other read errors.
        """

    @abstractmethod
    async def write_file(self, file_path: str, content: str) -> None:
        """Write content to a file (create or overwrite).

        Args:
            file_path: Absolute path to the file.
            content: Text content to write.

        Raises:
            RuntimeError: On write errors.
        """

    @abstractmethod
    async def list_files(
        self, dir_path: str = "/home/user", depth: int = 1
    ) -> List[FileEntry]:
        """List files in a directory.

        Args:
            dir_path: Directory path.
            depth: Recursion depth (1 = immediate children only).

        Returns:
            List of FileEntry objects.

        Raises:
            RuntimeError: On listing errors.
        """

    def is_cloud(self) -> bool:
        """Return True if this backend runs in a remote sandbox."""
        return False
