# -*- coding: utf-8 -*-
"""File System Backend Package for CoPaw."""

from .fs_backend import (
    FileSystemBackend,
    FileInfo,
    FileChange,
    OperationResult,
)
from .local_backend import LocalFileSystemBackend
from .opensandbox_backend import OpenSandboxFileSystemBackend
from .adapter import (
    FileSystemAdapter,
    get_fs_adapter,
    initialize_fs_backend,
    read_file,
    write_file,
    edit_file,
    append_file,
    delete_file,
    list_directory,
    create_directory,
    search_files,
    get_file_info,
)
from .config import (
    FSBackendConfig,
    get_config,
    set_config,
    load_config_from_dict,
    is_cloud_mode,
)

__all__ = [
    # Core interfaces
    'FileSystemBackend',
    'FileInfo',
    'FileChange',
    'OperationResult',

    # Backend implementations
    'LocalFileSystemBackend',
    'OpenSandboxFileSystemBackend',

    # Adapter and utilities
    'FileSystemAdapter',
    'get_fs_adapter',
    'initialize_fs_backend',

    # Convenience functions (compatible with file_io.py)
    'read_file',
    'write_file',
    'edit_file',
    'append_file',
    'delete_file',
    'list_directory',
    'create_directory',
    'search_files',
    'get_file_info',

    # Configuration
    'FSBackendConfig',
    'get_config',
    'set_config',
    'load_config_from_dict',
    'is_cloud_mode',
]
