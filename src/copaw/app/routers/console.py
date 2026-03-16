# -*- coding: utf-8 -*-
"""Console APIs for push messages."""

from fastapi import APIRouter, Query


router = APIRouter(prefix="/console", tags=["console"])


@router.get("/push-messages")
async def get_push_messages(
    session_id: str | None = Query(None, description="Optional session id"),
):
    """
    Return pending push messages. Without session_id: recent messages
    (all sessions, last 60s), not consumed so every tab sees them.
    """
    from ..console_push_store import get_recent, take

    if session_id:
        messages = await take(session_id)
    else:
        messages = await get_recent()
    return {"messages": messages}
