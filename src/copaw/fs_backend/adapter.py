# -*- coding: utf-8 -*-
"""File System Backend Adapter for CoPaw.

This module provides a unified interface to switch between local and
OpenSandbox file system backends based on configuration.
"""

from typing import Optional, Any

from ..constant import WORKING_DIR


class FileSystemAdapter:
    """Adapter that switches between local and OpenSandbox backends.

    Usage:
        from copaw.fs_backend.adapter import get_fs_adapter

        adapter = get_fs_adapter()
        result = await adapter.read_file('config.json')
        if result.success:
            content = result.data
    """

    _instance: Optional['FileSystemAdapter'] = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._backend = None
        self._sandbox = None
        self._use_cloud = False
        self._initialized = True

    def initialize(
        self,
        use_cloud: bool = False,
        sandbox: Any = None,
    ):
        """Initialize the adapter with the specified backend.

        Args:
            use_cloud: If True, use OpenSandbox backend. Otherwise local.
            sandbox: OpenSandbox ``Sandbox`` instance (required if
                use_cloud=True).
        """
        self._use_cloud = use_cloud

        if use_cloud:
            if sandbox is None:
                raise ValueError(
                    "Sandbox instance is required for cloud mode"
                )
            from .opensandbox_backend import OpenSandboxFileSystemBackend
            self._backend = OpenSandboxFileSystemBackend(sandbox)
            self._sandbox = sandbox
        else:
            from .local_backend import LocalFileSystemBackend
            self._backend = LocalFileSystemBackend(
                working_dir=str(WORKING_DIR),
            )

    @property
    def is_cloud(self) -> bool:
        """Whether the adapter is using the cloud backend."""
        return self._use_cloud

    @property
    def sandbox(self) -> Any:
        """The underlying OpenSandbox ``Sandbox`` instance, or None."""
        return self._sandbox

    # -- delegate every FileSystemBackend method --------------------------

    async def read_file(self, path: str):
        return await self._backend.read_file(path)

    async def write_file(self, path: str, content: str):
        return await self._backend.write_file(path, content)

    async def delete_file(self, path: str):
        return await self._backend.delete_file(path)

    async def create_directory(self, path: str):
        return await self._backend.create_directory(path)

    async def list_directory(self, path: str):
        return await self._backend.list_directory(path)

    async def get_file_info(self, path: str):
        return await self._backend.get_file_info(path)

    async def exists(self, path: str):
        return await self._backend.exists(path)

    async def move_file(self, source: str, destination: str):
        return await self._backend.move_file(source, destination)

    async def search_files(self, path: str, pattern: str):
        return await self._backend.search_files(path, pattern)

    async def watch_directory(self, path: str, callback, interval: float = 2.0):
        return await self._backend.watch_directory(path, callback, interval)

    async def close(self):
        if self._backend:
            await self._backend.close()
            self._backend = None


# Global adapter instance
_adapter: Optional[FileSystemAdapter] = None


def get_fs_adapter() -> FileSystemAdapter:
    """Get the global file system adapter instance."""
    global _adapter
    if _adapter is None:
        _adapter = FileSystemAdapter()
    return _adapter


def initialize_fs_backend(
    use_cloud: bool = False,
    sandbox: Any = None,
):
    """Initialize the global file system backend.

    This should be called during CoPaw application startup.

    Args:
        use_cloud: If True, use OpenSandbox backend. Otherwise local.
        sandbox: OpenSandbox ``Sandbox`` instance (required if use_cloud=True).

    Example:
        # Local mode (default)
        initialize_fs_backend()

        # Cloud mode
        from opensandbox import Sandbox
        sandbox = await Sandbox.create("python:3.11", ...)
        initialize_fs_backend(use_cloud=True, sandbox=sandbox)
    """
    adapter = get_fs_adapter()
    adapter.initialize(use_cloud=use_cloud, sandbox=sandbox)


# Convenience functions for direct use (compatible with file_io.py API)

async def read_file(file_path: str, **kwargs):
    """Read file content."""
    adapter = get_fs_adapter()
    return await adapter.read_file(file_path)


async def write_file(file_path: str, content: str, **kwargs):
    """Write content to file."""
    adapter = get_fs_adapter()
    return await adapter.write_file(file_path, content)


async def edit_file(file_path: str, old_text: str, new_text: str, **kwargs):
    """Edit file by replacing text."""
    read_result = await read_file(file_path)
    if not read_result.success:
        return read_result

    current_content = read_result.data
    if old_text not in current_content:
        from .fs_backend import OperationResult
        return OperationResult(
            success=False,
            error_message=f"Text not found in {file_path}"
        )
    new_content = current_content.replace(old_text, new_text, 1)
    return await write_file(file_path, new_content)


async def append_file(file_path: str, content: str, **kwargs):
    """Append content to file."""
    adapter = get_fs_adapter()
    read_result = await adapter.read_file(file_path)
    current_content = read_result.data if read_result.success else ""
    new_content = current_content + content
    return await adapter.write_file(file_path, new_content)


async def delete_file(file_path: str, **kwargs):
    """Delete file."""
    adapter = get_fs_adapter()
    return await adapter.delete_file(file_path)


async def list_directory(path: str, **kwargs):
    """List directory contents."""
    adapter = get_fs_adapter()
    return await adapter.list_directory(path)


async def create_directory(path: str, **kwargs):
    """Create directory."""
    adapter = get_fs_adapter()
    return await adapter.create_directory(path)


async def search_files(path: str, pattern: str, **kwargs):
    """Search files."""
    adapter = get_fs_adapter()
    return await adapter.search_files(path, pattern)


async def get_file_info(path: str, **kwargs):
    """Get file information."""
    adapter = get_fs_adapter()
    return await adapter.get_file_info(path)
