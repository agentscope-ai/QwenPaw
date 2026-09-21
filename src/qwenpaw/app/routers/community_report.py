# -*- coding: utf-8 -*-
"""Local report assistance; no community publication or filesystem access."""

import asyncio

from fastapi import APIRouter, HTTPException, Request

from ..community_report import (
    CommunityReportRequest,
    ReportGenerationError,
    generate_community_report,
)

router = APIRouter(prefix="/community/report", tags=["community"])


async def _wait_for_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.25)


@router.post("/generate")
async def generate_report(body: CommunityReportRequest, request: Request):
    generation = asyncio.create_task(generate_community_report(body))
    disconnect = asyncio.create_task(_wait_for_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            {generation, disconnect},
            timeout=120,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if disconnect in done:
            raise HTTPException(status_code=499, detail="report_cancelled")
        if generation not in done:
            raise HTTPException(status_code=504, detail="report_timeout")
        return {"report": generation.result()}
    except ReportGenerationError as exc:
        status = 422 if exc.code == "materials_not_reviewed" else 503
        raise HTTPException(status_code=status, detail=exc.code) from None
    finally:
        for task in (generation, disconnect):
            if not task.done():
                task.cancel()
        await asyncio.gather(generation, disconnect, return_exceptions=True)
