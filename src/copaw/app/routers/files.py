# -*- coding: utf-8 -*-
"""聊天附件（图片、文档等）的上传与访问 API。"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from ...constant import (
    WORKING_DIR,
    MEDIA_MAX_AGE_DAYS,
    MEDIA_MAX_SIZE_MB,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

MEDIA_DIR = WORKING_DIR / "media"

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


def _ensure_media_dir() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def _cleanup_by_age(
    entries: list[tuple[Path, float, int]],
    cutoff: float,
) -> tuple[int, int]:
    """内部函数：处理按时间过期的清理"""
    deleted, freed = 0, 0
    for p, mtime, size in entries:
        if mtime < cutoff:
            try:
                p.unlink()
                deleted += 1
                freed += size
            except OSError as e:
                logger.warning("Media cleanup: failed to remove %s: %s", p, e)
    return deleted, freed


def _cleanup_by_size(
    entries: list[tuple[Path, float, int]],
    max_size: int,
) -> tuple[int, int]:
    """内部函数：处理超出容量上限的清理"""
    deleted, freed = 0, 0
    total = sum(s for _, _, s in entries)
    if total <= max_size:
        return 0, 0

    entries.sort(key=lambda x: x[1])  # 最旧优先
    for p, _, size in entries:
        if total <= max_size:
            break
        try:
            p.unlink()
            deleted += 1
            freed += size
            total -= size
        except OSError as e:
            logger.warning("Media cleanup: failed to remove %s: %s", p, e)
    return deleted, freed


def run_media_cleanup() -> tuple[int, int]:
    if not MEDIA_DIR.is_dir():
        return 0, 0

    entries = []
    for p in MEDIA_DIR.iterdir():
        if p.is_file():
            try:
                stat = p.stat()
                entries.append((p, stat.st_mtime, stat.st_size))
            except OSError:
                continue

    deleted, freed = 0, 0

    # 1. 处理过期删除
    if MEDIA_MAX_AGE_DAYS > 0:
        cutoff = time.time() - (MEDIA_MAX_AGE_DAYS * 86400)
        d, f = _cleanup_by_age(entries, cutoff)
        deleted += d
        freed += f
        # 过滤掉已删除的
        entries = [(p, m, s) for p, m, s in entries if p.exists()]

    # 2. 处理超量删除
    max_size_bytes = MEDIA_MAX_SIZE_MB * 1024 * 1024
    if max_size_bytes > 0 and entries:
        d, f = _cleanup_by_size(entries, max_size_bytes)
        deleted += d
        freed += f

    if deleted:
        logger.info(
            "Media cleanup: removed %s file(s), freed %s bytes",
            deleted,
            freed,
        )
    return deleted, freed


def _safe_filename(original: str) -> str:
    """生成唯一文件名并保留原扩展名。"""
    suffix = Path(original).suffix if original else ""
    short_hash = hashlib.md5(
        f"{uuid.uuid4()}{original}".encode(),
    ).hexdigest()[:12]
    stem = Path(original).stem if original else "file"
    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    safe_stem = safe_stem[:60]
    return f"{safe_stem}_{short_hash}{suffix}"


@router.post(
    "/upload",
    summary="上传文件（图片、文档等）",
    description="上传单个文件作为聊天附件，返回可在消息中引用的 URL。",
)
async def upload_file(
    file: UploadFile = File(
        ...,
        description="要上传的文件",
    ),
) -> dict:
    """将上传文件保存到 WORKING_DIR/media 并返回其访问 URL。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    media_dir = _ensure_media_dir()
    safe_name = _safe_filename(file.filename)
    dest = media_dir / safe_name

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    dest.write_bytes(data)

    content_type = (
        file.content_type
        or mimetypes.guess_type(safe_name)[0]
        or "application/octet-stream"
    )

    return {
        "url": f"/files/serve/{safe_name}",
        "filename": file.filename,
        "size": len(data),
        "content_type": content_type,
    }


@router.get(
    "/serve/{filename:path}",
    summary="访问已上传文件",
    description="从媒体目录流式返回已上传的文件。",
)
async def serve_file(filename: str):
    """从 WORKING_DIR/media 返回指定文件。"""
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = MEDIA_DIR / filename
    resolved = file_path.resolve()
    if not str(resolved).startswith(str(MEDIA_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = (
        mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    return FileResponse(resolved, media_type=media_type)
