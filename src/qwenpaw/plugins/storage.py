# -*- coding: utf-8 -*-
"""Plugin-owned persistent storage and media references."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import AbstractContextManager as ContextManager
from contextlib import nullcontext
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any, Callable, Mapping, TypeVar

from .errors import SDKError
from .messages import Attachment

_T = TypeVar("_T")


def _comparison_path(path: PurePath) -> PurePath:
    """Windows resolve() can retain a prefix when a parent is created."""
    prefix = "\\\\?\\"
    if isinstance(path, PureWindowsPath) and path.drive.startswith(prefix):
        unc_prefix = prefix + "UNC\\"
        text = str(path)
        if text[: len(unc_prefix)].upper() == unc_prefix:
            return PureWindowsPath("\\\\" + text[len(unc_prefix) :])
        drive = path.drive[len(prefix) :]
        if len(drive) == 2 and drive.endswith(":"):
            return PureWindowsPath(text[len(prefix) :])
    return path


class PluginStorage:
    def __init__(
        self,
        root: Path,
        guard: Callable,
        *,
        _admission: Callable[[], ContextManager] = nullcontext,
        _legacy_sources: Mapping[str, Path] | None = None,
    ):
        self._root = root.resolve()
        self._comparison_root = _comparison_path(self._root)
        self._guard = guard
        self._admission = _admission
        self._legacy_sources = dict(_legacy_sources or {})

    async def _io(self, operation: Callable[[], _T]) -> _T:
        from ..utils.io_utils import run_sync_io

        self._guard()
        with self._admission():
            return await run_sync_io(operation)

    async def aread_bytes(self, name: str) -> bytes:
        return await self._io(lambda: self.read_bytes(name))

    async def awrite_bytes(self, name: str, data: bytes) -> None:
        await self._io(lambda: self.write_bytes(name, data))

    async def aread_json(self, name: str, default: Any = None) -> Any:
        return await self._io(lambda: self.read_json(name, default))

    async def awrite_json(self, name: str, value: Any) -> None:
        await self._io(lambda: self.write_json(name, value))

    async def adelete(self, name: str) -> None:
        await self._io(lambda: self.delete(name))

    def _path(self, name: str) -> Path:
        path = (self._root / name).resolve()
        candidate = _comparison_path(path)
        root = self._comparison_root
        if not candidate.is_relative_to(root) or candidate == root:
            raise SDKError(
                "Storage path must remain inside this plugin's data directory",
            )
        return path

    def path(self, name: str) -> Path:
        """Resolve a private file path for libraries such as SQLite.

        Creates parent directories, but not the file. The caller must keep
        open connections in ResourceScope; a returned Path is not revocable.
        """
        self._guard()
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def import_legacy(self, source: str, name: str) -> bool:
        """Copy a declared legacy file only if the private target is absent."""
        from ._storage_migration import copy_missing, declared_source

        self._guard()
        origin = declared_source(self._legacy_sources, source)
        if not origin.exists():
            return False
        return copy_missing(origin, self.path(name), self._guard)

    def import_legacy_tree(self, source: str, name: str) -> tuple[str, ...]:
        """Copy missing regular files; retain sources and allow safe retries.

        Returns copied paths relative to this storage. Symlinks and special
        files are rejected. A partial failure leaves completed copies intact.
        """
        from ._storage_migration import copy_missing, declared_source

        self._guard()
        origin = declared_source(self._legacy_sources, source)
        relative_target = _comparison_path(self._path(name)).relative_to(
            self._comparison_root,
        )
        if not origin.exists():
            return ()
        if not origin.is_dir():
            raise SDKError("Legacy tree source must be a directory")

        def raise_scan_error(error: OSError) -> None:
            raise error

        copied = []
        for directory, dirs, files in os.walk(
            origin,
            onerror=raise_scan_error,
            followlinks=False,
        ):
            for item in (*dirs, *files):
                path = Path(directory) / item
                if path.is_symlink():
                    raise SDKError("Legacy storage cannot contain symlinks")
            for filename in sorted(files):
                path = Path(directory) / filename
                relative = (
                    relative_target / path.relative_to(origin)
                ).as_posix()
                if copy_missing(path, self.path(relative), self._guard):
                    copied.append(relative)
        return tuple(copied)

    def read_bytes(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    def write_bytes(self, name: str, data: bytes) -> None:
        self._guard()
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._guard()
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def read_json(self, name: str, default: Any = None) -> Any:
        try:
            return json.loads(self.read_bytes(name))
        except FileNotFoundError:
            return default

    def write_json(self, name: str, value: Any) -> None:
        self.write_bytes(name, json.dumps(value, ensure_ascii=False).encode())

    def delete(self, name: str) -> None:
        self._guard()
        self._path(name).unlink(missing_ok=True)


class MediaStore:  # pylint: disable=protected-access
    def __init__(self, storage: PluginStorage, url_prefix: str):
        self._storage = storage
        self._url_prefix = url_prefix.rstrip("/")

    async def awrite(
        self,
        name: str,
        data: bytes,
        *,
        mime_type: str = "application/octet-stream",
    ) -> Attachment:
        return await self._storage._io(
            lambda: self.write(name, data, mime_type=mime_type),
        )

    def write(
        self,
        name: str,
        data: bytes,
        *,
        mime_type: str = "application/octet-stream",
    ) -> Attachment:
        from urllib.parse import quote

        self._storage.write_bytes(name, data)
        return Attachment(
            self._storage._path(name).as_uri(),
            mime_type,
            Path(name).name,
            f"{self._url_prefix}/{quote(name, safe='/')}",
        )


class PluginConfig:
    """Snapshot of plugin settings; secrets require explicit declaration."""

    def __init__(self, values: dict, declarations: dict):
        from copy import deepcopy

        self._values = deepcopy(values)
        self._secrets = frozenset(declarations.get("secrets", []))

    def get(self, name: str, default: Any = None) -> Any:
        from copy import deepcopy

        if name in self._secrets:
            raise SDKError("Use config.secret() for declared secrets")
        return deepcopy(self._values.get(name, default))

    def secret(self, name: str) -> str | None:
        if name not in self._secrets:
            raise SDKError(f"Secret {name!r} was not declared in sdk.secrets")
        value = self._values.get(name)
        return None if value is None else str(value)
