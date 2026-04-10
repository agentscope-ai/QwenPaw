# -*- coding: utf-8 -*-
"""API router for sending messages to channels."""
from __future__ import annotations

import logging
from typing import Optional

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])


def _get_multi_agent_manager(request: Request):
    """Get MultiAgentManager from app state.

    Args:
        request: FastAPI request object

    Returns:
        MultiAgentManager instance

    Raises:
        HTTPException: If manager not initialized
    """

    if not hasattr(request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    return request.app.state.multi_agent_manager


class SendMessageRequest(BaseModel):
    """Request model for sending a message to a channel."""

    model_config = ConfigDict(populate_by_name=True)

    channel: str = Field(
        ...,
        description=(
            "Target channel (e.g., console, dingtalk, feishu, discord)"
        ),
    )
    target_user: str = Field(
        ...,
        description="Target user ID in the channel",
    )
    target_session: str = Field(
        ...,
        description="Target session ID in the channel",
    )
    text: str = Field(
        ...,
        description="Text message to send",
    )


class SendMessageResponse(BaseModel):
    """Response model for send message endpoint."""

    success: bool = Field(
        ...,
        description="Whether the message was sent successfully",
    )
    message: str = Field(
        ...,
        description="Status message",
    )


@router.post("/send", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    http_request: Request,
    x_agent_id: Optional[str] = Header(None, alias="X-Agent-Id"),
) -> SendMessageResponse:
    """Send a text message to a channel.

    This endpoint allows agents to proactively send messages to users
    via configured channels.

    Args:
        request: Message send request with channel, target, and text
        http_request: FastAPI request object (for accessing app state)
        x_agent_id: Agent ID from X-Agent-Id header (defaults to "default")

    Returns:
        SendMessageResponse with success status

    Raises:
        HTTPException: If channel not found or send fails

    Example:
        ```bash
        curl -X POST "http://localhost:8088/api/messages/send" \\
          -H "Content-Type: application/json" \\
          -H "X-Agent-Id: my_bot" \\
          -d '{
            "channel": "console",
            "target_user": "alice",
            "target_session": "session_001",
            "text": "Hello from my_bot!"
          }'
        ```
    """
    # Get agent ID (default to "default" if not provided)
    agent_id = x_agent_id or "default"

    # Get multi-agent manager from app state (via request)
    multi_agent_manager = _get_multi_agent_manager(http_request)

    # Get workspace for the agent
    try:
        workspace = await multi_agent_manager.get_agent(agent_id)
    except (ValueError, AppBaseException) as e:
        logger.error("Agent not found: %s", e)
        raise HTTPException(
            status_code=404,
            detail=f"Agent not found: {agent_id}",
        ) from e
    except Exception as e:
        logger.error("Failed to get agent workspace: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent workspace: {str(e)}",
        ) from e

    # Get channel manager from workspace
    channel_manager = workspace.channel_manager
    if not channel_manager:
        raise HTTPException(
            status_code=500,
            detail=f"Channel manager not initialized for agent {agent_id}",
        )

    # Log the send request
    agent_info = f" (agent: {x_agent_id})" if x_agent_id else ""
    logger.info(
        "API send_message%s: channel=%s user=%s session=%s text_len=%d",
        agent_info,
        request.channel,
        request.target_user[:40] if request.target_user else "",
        request.target_session[:40] if request.target_session else "",
        len(request.text),
    )

    # Send the message via channel manager
    try:
        await channel_manager.send_text(
            channel=request.channel,
            user_id=request.target_user,
            session_id=request.target_session,
            text=request.text,
            meta={"agent_id": x_agent_id} if x_agent_id else None,
        )

        return SendMessageResponse(
            success=True,
            message=f"Message sent successfully to {request.channel}",
        )

    except KeyError as e:
        logger.warning("Channel not found: %s", e)
        raise HTTPException(
            status_code=404,
            detail=f"Channel not found: {request.channel}",
        ) from e

    except Exception as e:
        logger.error(
            "Failed to send message to %s: %s",
            request.channel,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send message: {str(e)}",
        ) from e
