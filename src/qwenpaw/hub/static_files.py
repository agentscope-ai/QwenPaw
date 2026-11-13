# -*- coding: utf-8 -*-
"""Console asset resolution and precompressed static responses."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _accepted_asset_encodings(scope: Scope) -> list[tuple[str, str]]:
    headers = {name.lower(): value for name, value in scope.get("headers", [])}
    raw = headers.get(b"accept-encoding", b"").decode("latin-1")
    quality_by_name: dict[str, float] = {}
    for item in raw.split(","):
        parts = [part.strip() for part in item.split(";")]
        name = parts[0].lower()
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
        quality_by_name[name] = quality
    wildcard_quality = quality_by_name.get("*", 0.0)
    supported = [("br", ".br"), ("gzip", ".gz")]
    candidates = [
        (quality_by_name.get(name, wildcard_quality), index, name, suffix)
        for index, (name, suffix) in enumerate(supported)
        if quality_by_name.get(name, wildcard_quality) > 0
    ]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [(name, suffix) for _, _, name, suffix in candidates]


class CompressedStaticFiles(StaticFiles):
    """Serve precompressed hashed assets with production cache headers."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Negotiate Brotli or gzip while retaining identity fallback."""
        for encoding, suffix in _accepted_asset_encodings(scope):
            try:
                response = await super().get_response(
                    f"{path}{suffix}",
                    scope,
                )
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            if response.status_code == 404:
                continue
            media_type, _ = mimetypes.guess_type(path)
            if media_type:
                response.headers["Content-Type"] = media_type
            response.headers["Content-Encoding"] = encoding
            response.headers["Vary"] = "Accept-Encoding"
            response.headers["Cache-Control"] = _ASSET_CACHE_CONTROL
            return response
        response = await super().get_response(path, scope)
        response.headers["Vary"] = "Accept-Encoding"
        response.headers["Cache-Control"] = _ASSET_CACHE_CONTROL
        return response


def resolve_console_response(
    static_dir: Path,
    path: str,
) -> tuple[Path | None, Path | None]:
    """Resolve static response paths outside the asyncio event loop."""
    index_file = static_dir / "index.html"
    requested = (static_dir / path).resolve()
    if requested.is_file() and static_dir in requested.parents:
        return requested, None
    if index_file.is_file():
        return None, index_file
    return None, None


def resolve_console_static_dir() -> Path:
    """Find an explicit, packaged, or repository Console build."""
    configured = os.environ.get("QWENPAW_CONSOLE_STATIC_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    package_root = Path(__file__).resolve().parents[1]
    packaged = package_root / "console"
    if (packaged / "index.html").is_file():
        return packaged
    repository = Path(__file__).resolve().parents[3]
    return repository / "console" / "dist"
