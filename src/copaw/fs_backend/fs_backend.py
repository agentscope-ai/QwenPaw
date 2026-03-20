# -*- coding: utf-8 -*-
"""File System Backend Abstraction for CoPaw.

This module defines the abstract interface for file system operations,
supporting both local and cloud sandbox backends (e.g. OpenSandbox).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Any


@dataclass
class FileInfo:
    """File information structure."""
    name: str
    path: str
    is_directory: bool
    size: int = 0
    mtime: float = 0.0
    exists: bool = True


@dataclass
class FileChange:
    """File change event structure."""
    path: str
    event_type: str  # created, modified, deleted
    is_directory: bool = False


@dataclass
class OperationResult:
    """Result of a file system operation."""
    success: bool
    error_message: str = ""
    data: Any = None


class FileSystemBackend(ABC):
    """Abstract base class for file system backends.

    This interface provides a unified API for both local and cloud-based
    file system operations, allowing CoPaw to work seamlessly in both
    environments.
    """

    @abstractmethod
    async def read_file(self, path: str) -> OperationResult:
        """Read file content.

        Args:
            path: File path to read.

        Returns:
            OperationResult with content in data field.
        """
        pass

    @abstractmethod
    async def write_file(self, path: str, content: str) -> OperationResult:
        """Write content to file.

        Args:
            path: File path to write.
            content: Content to write.

        Returns:
            OperationResult indicating success/failure.
        """
        pass

    @abstractmethod
    async def delete_file(self, path: str) -> OperationResult:
        """Delete a file.

        Args:
            path: File path to delete.

        Returns:
            OperationResult indicating success/failure.
        """
        pass

    @abstractmethod
    async def create_directory(self, path: str) -> OperationResult:
        """Create a directory.

        Args:
            path: Directory path to create.

        Returns:
            OperationResult indicating success/failure.
        """
        pass

    @abstractmethod
    async def list_directory(self, path: str) -> OperationResult:
        """List directory contents.

        Args:
            path: Directory path to list.

        Returns:
            OperationResult with list of FileInfo in data field.
        """
        pass

    @abstractmethod
    async def get_file_info(self, path: str) -> OperationResult:
        """Get file/directory information.

        Args:
            path: Path to get info for.

        Returns:
            OperationResult with FileInfo in data field.
        """
        pass

    @abstractmethod
    async def exists(self, path: str) -> OperationResult:
        """Check if path exists.

        Args:
            path: Path to check.

        Returns:
            OperationResult with boolean in data field.
        """
        pass

    @abstractmethod
    async def move_file(self, source: str, destination: str) -> OperationResult:
        """Move/rename a file or directory.

        Args:
            source: Source path.
            destination: Destination path.

        Returns:
            OperationResult indicating success/failure.
        """
        pass

    @abstractmethod
    async def search_files(self, path: str, pattern: str) -> OperationResult:
        """Search for files matching pattern.

        Args:
            path: Base path to search in.
            pattern: Glob pattern to match.

        Returns:
            OperationResult with list of matching paths in data field.
        """
        pass

    @abstractmethod
    async def watch_directory(
        self,
        path: str,
        callback,
        interval: float = 2.0
    ) -> OperationResult:
        """Watch directory for changes.

        Args:
            path: Directory path to watch.
            callback: Function to call on changes (receives List[FileChange]).
            interval: Polling interval in seconds.

        Returns:
            OperationResult with watcher handle in data field.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close backend and cleanup resources."""
        pass
