# -*- coding: utf-8 -*-
"""File upload API for console attachments."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = WORKING_DIR / "uploads"

_ALLOWED_EXTENSIONS = {
    # images
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".ico",
    # video
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
    ".flv",
    # audio
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".aac",
    ".amr",
    ".opus",
    ".m4a",
    # documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".rtf",
    # archives
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",
    # code
    ".py",
    ".js",
    ".ts",
    ".java",
    ".c",
    ".cpp",
    ".go",
    ".rs",
    ".sh",
    ".bat",
    ".ps1",
}

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def _safe_filename(original: str) -> str:
    """Generate an unpredictable unique filename preserving the extension."""
    suffix = Path(original).suffix.lower()
    return f"{uuid.uuid4().hex}{suffix}"


@router.post(
    "",
    summary="Upload a file",
    description="Upload a file (image, video, pdf, etc.) for use in chat",
)
async def upload_file(file: UploadFile = File(...)):
    """Upload a file and return its serving URL."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{suffix}' is not allowed",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(file.filename)
    dest = UPLOAD_DIR / safe_name

    size = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File too large "
                        f"(max {MAX_FILE_SIZE // (1024 * 1024)} MB)"
                    ),
                )
            f.write(chunk)

    logger.info(
        "Uploaded file: %s -> %s (%d bytes)",
        file.filename,
        dest,
        size,
    )

    return {
        "url": f"/api/upload/files/{safe_name}",
        "filename": file.filename,
        "size": size,
    }


@router.get(
    "/files/{filename}",
    summary="Serve an uploaded file",
    description="Serve a previously uploaded file by filename",
)
async def serve_uploaded_file(filename: str):
    """Serve a file from the uploads directory."""
    file_path = (UPLOAD_DIR / filename).resolve()
    upload_root = UPLOAD_DIR.resolve()

    try:
        file_path.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Access denied") from exc

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        filename=filename,
        content_disposition_type="attachment",
    )
