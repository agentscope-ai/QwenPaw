# -*- coding: utf-8 -*-
"""API endpoint for resolving interactive tool calls."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..interaction import InteractionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interaction", tags=["interaction"])


class InteractionRequest(BaseModel):
    session_id: str
    result: str


@router.post("")
async def resolve_interaction(body: InteractionRequest) -> dict:
    """Receive the user's interactive choice and unblock the tool."""
    success = InteractionManager.resolve(body.session_id, body.result)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="No pending interaction for this session",
        )
    return {"status": "ok"}
