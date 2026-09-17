# -*- coding: utf-8 -*-
"""PRD API router for CloudPaw plugin.

GET /api/prd?loop_dir=... — read prd.json or a snapshot.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("qwenpaw").getChild("plugin.cloudpaw.routers.prd")

router = APIRouter(prefix="", tags=["prd"])


@router.get("")
async def read_prd(
    loop_dir: str = Query(...),
    timestamp: str = Query(None, description="Snapshot timestamp"),
) -> dict:
    """Read prd.json (or a historical snapshot) from a mission loop dir."""
    base = Path(loop_dir).expanduser().resolve()
    prd_path = base / "prd.json"

    if timestamp:
        snap_path = base / "snapshots" / f"{timestamp}.json"
        if snap_path.exists():
            prd_path = snap_path

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
