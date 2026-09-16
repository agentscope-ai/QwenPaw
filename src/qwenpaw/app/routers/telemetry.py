# -*- coding: utf-8 -*-
"""Local Runtime activity signal; existing app authentication applies."""
from fastapi import APIRouter, Response

from ...utils.daily_telemetry import record_activity

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post("/activity", status_code=204)
async def record_page_activity() -> Response:
    """Observe a visible, user-initiated visit, never a background poll."""
    recorded = await record_activity("page")
    return Response(status_code=204 if recorded else 202)
