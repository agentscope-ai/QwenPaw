# -*- coding: utf-8 -*-
"""Outbound text send via ChannelManager (same path as cron task_type=text)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..agent_context import get_agent_for_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channel", tags=["channel"])


class SendTextRequest(BaseModel):
    """Send plain text to a channel target identified by session and user."""

    session_id: str = Field(
        ...,
        min_length=1,
        description="Session id for the target",
    )
    user_id: str = Field(
        default="",
        description="User id (may be empty for some channels)",
    )
    channel: str = Field(
        ...,
        min_length=1,
        description="Channel name, e.g. console, feishu, dingtalk",
    )
    text: str = Field(..., min_length=1, description="Message body")
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extra metadata passed to the channel",
    )


@router.post(
    "/send-text",
    status_code=200,
    summary="Send text to a channel by session",
)
async def post_channel_send_text(
    request: Request,
    body: SendTextRequest,
) -> dict:
    """Deliver text using :meth:`ChannelManager.send_text`.

    Requires the channel to be enabled and (for e.g. Feishu) a prior
    ``receive_id`` cached from an inbound message.
    """
    workspace = await get_agent_for_request(request)
    cm = workspace.channel_manager
    if cm is None:
        raise HTTPException(
            status_code=503,
            detail="Channel manager not available",
        )
    try:
        await cm.send_text(
            channel=body.channel,
            user_id=body.user_id,
            session_id=body.session_id,
            text=body.text,
            meta=body.meta,
        )
    except KeyError as e:
        logger.info("channel send-text: unknown channel: %s", e)
        raise HTTPException(
            status_code=404,
            detail=str(e) or "Channel not found",
        ) from e
    return {"ok": True}
