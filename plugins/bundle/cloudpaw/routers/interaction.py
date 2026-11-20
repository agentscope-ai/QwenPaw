# -*- coding: utf-8 -*-
"""Interaction API router for CloudPaw plugin.

POST /api/interaction — resolve a pending user interaction.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# pylint: disable=no-name-in-module
from qwenpaw.app.interaction import InteractionManager

logger = logging.getLogger("qwenpaw").getChild(
    "plugin.cloudpaw.routers.interaction",
)

router = APIRouter(prefix="", tags=["interaction"])


class InteractionRequest(BaseModel):
    session_id: str
    result: str
    pending_id: str


@router.get("/pending")
async def get_pending(session_id: str):
    pending = InteractionManager.pending(session_id)
    if pending is None or pending.event.is_set():
        return None
    return {"id": pending.id, "names": pending.names, "proposals": pending.proposals}


@router.post("")
async def resolve_interaction(body: InteractionRequest) -> dict:
    success = InteractionManager.resolve(body.session_id, body.result, body.pending_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="No pending interaction for this session",
        )
    return {"status": "ok"}
