# -*- coding: utf-8 -*-
from pathlib import Path
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

router = APIRouter(prefix="/files", tags=["files"])


@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file",
)
async def preview_file(
    filepath: str,
):
    """Preview file."""
    normalized = unquote(filepath)

    # Tolerate duplicated preview prefix from some clients, e.g.
    # /api/files/preview/api/files/preview/C%3A/Users/...
    while True:
        trimmed = normalized.lstrip("/")
        prefix = "api/files/preview/"
        if trimmed.startswith(prefix):
            normalized = trimmed[len(prefix) :]
            continue
        break

    # Normalize /C:/... to C:/... on Windows.
    if (
        len(normalized) >= 4
        and normalized[0] == "/"
        and normalized[2] == ":"
        and normalized[1].isalpha()
    ):
        normalized = normalized[1:]

    path = Path(normalized)
    if not path.is_absolute():
        path = Path("/" + normalized)
    path = path.resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename=path.name)
