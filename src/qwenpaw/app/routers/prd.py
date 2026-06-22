# -*- coding: utf-8 -*-
"""PRD API router — read prd.json or snapshots."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from qwenpaw.constant import WORKING_DIR

router = APIRouter(prefix="/prd", tags=["prd"])

_TIMESTAMP_RE = re.compile(r"^\d{8}-\d{6}$")

_ALLOWED_ROOT: Path = WORKING_DIR.resolve()


@router.get("")
async def read_prd(
    loop_dir: str = Query(...),
    timestamp: str = Query(None, description="Snapshot timestamp"),
) -> dict:
    """Read prd.json (or a historical snapshot) from a mission loop dir.

    If a timestamp is provided but the snapshot does not exist,
    falls back to the current prd.json for backward compatibility.
    """
    base = Path(loop_dir).expanduser().resolve()

    # Validate: resolved path must be under WORKING_DIR
    if not (base == _ALLOWED_ROOT or base.is_relative_to(_ALLOWED_ROOT)):
        raise HTTPException(
            status_code=403,
            detail="loop_dir must be within the working directory",
        )

    prd_path = base / "prd.json"

    if timestamp:
        if not _TIMESTAMP_RE.match(timestamp):
            raise HTTPException(
                status_code=400,
                detail="Invalid timestamp format. Expected: YYYYMMDD-HHMMSS",
            )
        snap_path = base / "snapshots" / f"{timestamp}.json"
        if snap_path.exists():
            prd_path = snap_path
        # else: snapshot not found (old data), fall back to prd.json

    if not prd_path.exists():
        raise HTTPException(
            status_code=404,
            detail="prd.json not found",
        )
    try:
        return json.loads(prd_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prd.json: {exc}",
        ) from exc
