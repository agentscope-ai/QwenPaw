# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=unused-argument
"""Download and content-address visual grounding candidates."""

from __future__ import annotations

import io
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from models import config as model_config
from services.storage_root import (
    CreatorDataRootError,
    require_creator_data_root,
)
from services.workspace.content_store import ContentStore, atomic_replace_bytes
from utils.logger import setup_logger

DEFAULT_TIMEOUT = 8.0
DEFAULT_VISUAL_DOWNLOAD_MAX_BYTES = 8 * 1024 * 1024
USER_AGENT = "QwenPaw-Creator/0.1 web-grounding"
logger = setup_logger("services.web_grounding.staging")

_IMAGE_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def visual_download_max_bytes() -> int:
    try:
        value = int(
            os.environ.get(
                "WEB_GROUNDING_IMAGE_MAX_BYTES",
                DEFAULT_VISUAL_DOWNLOAD_MAX_BYTES,
            ),
        )
    except (TypeError, ValueError):
        value = DEFAULT_VISUAL_DOWNLOAD_MAX_BYTES
    return max(256 * 1024, min(value, model_config.get_vlm_max_inline_bytes()))


def mime_extension(media_type: str, url: str = "") -> str:
    normalized = media_type.split(";", 1)[0].strip().lower()
    if normalized in _IMAGE_MIME_EXTENSIONS:
        return _IMAGE_MIME_EXTENSIONS[normalized]
    guessed = mimetypes.guess_extension(normalized)
    if guessed:
        return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    return (
        suffix
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
        else ".img"
    )


def sniff_image_media_type(
    payload: bytes,
    content_type: str = "",
    url: str = "",
) -> str:
    declared = content_type.split(";", 1)[0].strip().lower()
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if payload.startswith(b"BM"):
        return "image/bmp"
    if declared in _IMAGE_MIME_EXTENSIONS:
        raise ValueError(
            "downloaded visual reference declares an image type but has invalid image bytes",
        )
    raise ValueError(
        "downloaded visual reference is not a supported raster image",
    )


def validate_raster_image(payload: bytes) -> None:
    """Decode enough of the payload to reject truncated or mislabeled images."""
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
            width, height = image.size
    except Exception as exc:  # Pillow exposes several decoder-specific errors.
        raise ValueError(
            "downloaded visual reference cannot be decoded as an image",
        ) from exc
    if width <= 0 or height <= 0:
        raise ValueError("downloaded visual reference has invalid dimensions")


def grounding_visual_delivery_path(
    digest: str,
    media_type: str,
    source_url: str = "",
) -> Path:
    data_root = require_creator_data_root()
    extension = mime_extension(media_type, source_url)
    return (
        data_root
        / "grounding-visuals"
        / "sha256"
        / digest[:2]
        / f"{digest}{extension}"
    )


async def download_visual_source(
    client: httpx.AsyncClient,
    source: dict[str, Any],
    *,
    max_bytes: int,
) -> dict[str, Any]:
    url = str(source.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("visual reference URL must be http(s)")
    async with client.stream(
        "GET",
        url,
        headers={
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.1",
            "User-Agent": USER_AGENT,
        },
    ) as response:
        response.raise_for_status()
        raw_length = response.headers.get("content-length")
        if raw_length:
            try:
                declared_length = int(raw_length)
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > max_bytes:
                raise ValueError(
                    f"visual reference is too large: {raw_length} bytes",
                )
        chunks: list[bytes] = []
        total_size = 0
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            total_size += len(chunk)
            if total_size > max_bytes:
                raise ValueError(
                    f"visual reference is too large: {total_size} bytes",
                )
            chunks.append(chunk)
        payload = b"".join(chunks)
        content_type = response.headers.get("content-type", "")
        final_url = str(response.url)
    if not payload:
        raise ValueError("visual reference download returned empty body")
    media_type = sniff_image_media_type(payload, content_type, final_url)
    validate_raster_image(payload)
    return {
        "payload": payload,
        "media_type": media_type,
        "final_url": final_url,
        "byte_size": len(payload),
    }


async def stage_visual_grounding_sources(
    visual_sources: list[dict[str, Any]],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int | None = None,
    downloader=download_visual_source,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not visual_sources:
        return [], {
            "status": "skipped",
            "detail": "no visual sources to stage",
            "downloaded_count": 0,
            "failed_count": 0,
        }
    try:
        data_root = require_creator_data_root()
    except CreatorDataRootError as exc:
        return [], {
            "status": "degraded",
            "detail": f"CREATOR_DATA_ROOT unavailable for visual grounding image staging: {exc}",
            "downloaded_count": 0,
            "failed_count": len(visual_sources),
            "issues": ["creator_data_root_unavailable"],
        }
    store = ContentStore(data_root)
    effective_max_bytes = max_bytes or visual_download_max_bytes()
    staged: list[dict[str, Any]] = []
    issues: list[str] = []
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for source in visual_sources:
            source_url = str(source.get("url") or "")
            try:
                downloaded = await downloader(
                    client,
                    source,
                    max_bytes=effective_max_bytes,
                )
                payload = bytes(downloaded["payload"])
                stored = store.put_bytes(payload, namespace="blob")
                delivery_path = grounding_visual_delivery_path(
                    stored.sha256,
                    str(downloaded["media_type"]),
                    source_url,
                )
                if (
                    not delivery_path.is_file()
                    or delivery_path.stat().st_size != len(payload)
                ):
                    atomic_replace_bytes(delivery_path, payload)
                enriched = dict(source)
                enriched.update(
                    {
                        "download": {
                            "status": "success",
                            "media_type": downloaded["media_type"],
                            "byte_size": downloaded["byte_size"],
                            "final_url": downloaded["final_url"],
                        },
                        "grounding_ref": f"grounding-image://sha256/{stored.sha256}",
                        "media_type": downloaded["media_type"],
                        "storage_namespace": "blob",
                        "storage_sha256": stored.sha256,
                        "storage_path": str(stored.path),
                        "local_path": str(delivery_path),
                        "local_url": delivery_path.as_uri(),
                        "vlm_image_url": delivery_path.as_uri(),
                    },
                )
                staged.append(enriched)
            except Exception as exc:  # noqa: BLE001
                reason = f"{type(exc).__name__}: {exc}"
                issues.append(f"visual_download_failed:{source_url}:{reason}")
                logger.info(
                    "Visual grounding candidate download failed url=%r error=%s",
                    source_url,
                    reason,
                )
    status = "success" if staged else "degraded"
    logger.info(
        "Visual grounding staging completed status=%s downloaded=%d failed=%d",
        status,
        len(staged),
        len(visual_sources) - len(staged),
    )
    return staged, {
        "status": status,
        "downloaded_count": len(staged),
        "failed_count": len(visual_sources) - len(staged),
        "max_bytes": effective_max_bytes,
        "storage_root": str(data_root / "grounding-visuals"),
        "issues": issues,
    }
