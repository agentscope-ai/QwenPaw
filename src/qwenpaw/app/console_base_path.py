# -*- coding: utf-8 -*-
"""Console base-path helpers for reverse-proxy subpath deployments."""
from __future__ import annotations

from urllib.parse import urlsplit

from ..constant import EnvVarLoader

CONSOLE_BASE_PATH_ENV = "QWENPAW_BASE_PATH"
LEGACY_CONSOLE_BASE_PATH_ENV = "COPAW_BASE_PATH"


def normalize_console_base_path(value: str | None) -> str:
    """Return a normalized URL path prefix without a trailing slash."""
    raw = (value or "").strip()
    if not raw or raw == "/":
        return ""

    if "://" in raw or raw.startswith("//"):
        raw = urlsplit(raw).path

    raw = "/" + raw.strip("/")
    if raw == "/":
        return ""

    segments = raw.split("/")[1:]
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError(
            "console base path must not contain empty, '.', or '..' segments",
        )
    return raw


def resolve_console_base_path() -> str:
    """Read the configured console URL prefix from environment variables."""
    value = EnvVarLoader.get_str(CONSOLE_BASE_PATH_ENV)
    if not value:
        value = EnvVarLoader.get_str(LEGACY_CONSOLE_BASE_PATH_ENV)
    return normalize_console_base_path(value)


class BasePathMiddleware:
    """Strip a configured URL prefix before FastAPI route matching."""

    def __init__(self, app, base_path: str):
        self.app = app
        self.base_path = normalize_console_base_path(base_path)
        self._base_path_bytes = self.base_path.encode("ascii")

    async def __call__(self, scope, receive, send):
        if self.base_path and scope["type"] in {"http", "websocket"}:
            path = scope.get("path") or ""
            if path == self.base_path or path.startswith(
                f"{self.base_path}/",
            ):
                scope = dict(scope)
                stripped = path[len(self.base_path) :] or "/"
                scope["path"] = stripped

                raw_path = scope.get("raw_path")
                if raw_path and raw_path.startswith(self._base_path_bytes):
                    scope["raw_path"] = (
                        raw_path[len(self._base_path_bytes) :] or b"/"
                    )

                root_path = (scope.get("root_path") or "").rstrip("/")
                if not root_path.endswith(self.base_path):
                    scope["root_path"] = f"{root_path}{self.base_path}"

        await self.app(scope, receive, send)
