# -*- coding: utf-8 -*-
"""Plugin-owned persistent storage and media references."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, ContextManager, TypeVar

from .errors import SDKError
from .messages import Attachment

_T = TypeVar("_T")


class PluginStorage:
    def __init__(
        self,
        root: Path,
        guard: Callable,
        *,
        _admission: Callable[[], ContextManager] = nullcontext,
    ):
        self._root = root.resolve()
        self._guard = guard
        self._admission = _admission

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
        if not path.is_relative_to(self._root) or path == self._root:
            raise SDKError(
                "Storage path must remain inside this plugin's data directory",
            )
        return path

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
