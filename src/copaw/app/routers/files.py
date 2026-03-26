# -*- coding: utf-8 -*-
from pathlib import Path
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
    path = Path(filepath)
    if not path.is_absolute():
        path = Path("/" + filepath)
    path = path.resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename=path.name)
