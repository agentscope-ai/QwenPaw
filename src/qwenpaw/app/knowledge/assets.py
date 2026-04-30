# -*- coding: utf-8 -*-
from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

from .paths import knowledge_assets_dir, knowledge_document_assets_dir


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".webm"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def asset_kind_for_suffix(suffix: str) -> str:
    lowered = suffix.lower()
    if lowered in IMAGE_SUFFIXES:
        return "image"
    if lowered in AUDIO_SUFFIXES:
        return "audio"
    if lowered in VIDEO_SUFFIXES:
        return "video"
    return "file"


def save_asset_bytes(knowledge_id: str, document_id: str, name: str, raw_bytes: bytes) -> dict[str, Any]:
    suffix = Path(name).suffix.lower() or ".bin"
    asset_id = uuid.uuid4().hex[:12]
    target_dir = knowledge_document_assets_dir(knowledge_id, document_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_id}{suffix}"
    target_path = target_dir / filename
    target_path.write_bytes(raw_bytes)
    mime_type, _ = mimetypes.guess_type(str(target_path))
    return {
        "id": asset_id,
        "name": Path(name).name,
        "kind": asset_kind_for_suffix(suffix),
        "mime_type": mime_type or "application/octet-stream",
        "path": f"{knowledge_id}/{document_id}/{filename}",
        "url": f"/api/files/preview/knowledge-assets/{knowledge_id}/{document_id}/{filename}",
    }


def delete_document_assets(knowledge_id: str, document_id: str) -> None:
    shutil.rmtree(knowledge_document_assets_dir(knowledge_id, document_id), ignore_errors=True)


def delete_knowledge_assets(knowledge_id: str) -> None:
    shutil.rmtree(knowledge_assets_dir(knowledge_id), ignore_errors=True)