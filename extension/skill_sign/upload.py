# -*- coding: utf-8 -*-
"""Upload helpers for skill secure import routes."""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

from qwenpaw.app.utils import check_upload_size

_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "multipart/x-zip",
    "application/octet-stream",
}


async def read_validated_zip_upload(file: UploadFile) -> bytes:
    if file.content_type and file.content_type not in _ALLOWED_ZIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Expected a zip file, "
                f"got content-type: {file.content_type}"
            ),
        )

    data = await file.read()
    check_upload_size(data)
    return data
