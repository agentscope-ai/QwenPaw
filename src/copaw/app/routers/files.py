from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse
from ..agent_context import get_agent_for_request
from logging import getLogger

logger = getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file"
)
async def preview_file(
    filepath: str,
):
    """Preview file."""
    path = Path(filepath) if filepath.startswith("/") else  Path(f"/{filepath}")
    path = path.resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename = path.name)
