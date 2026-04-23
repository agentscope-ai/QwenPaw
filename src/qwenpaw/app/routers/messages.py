# -*- coding: utf-8 -*-
"""API router for sending messages to channels."""
from __future__ import annotations

import logging
import os
import tempfile
import base64
import re
from typing import List, Optional
from pathlib import Path
from urllib.parse import urlparse

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)
from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    FileContent,
    ContentType,
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


class MediaContent(BaseModel):
    """多媒体内容（统一按文件处理）"""
    model_config = ConfigDict(populate_by_name=True)
    type: str = Field(default="file", description="媒体类型：file（统一）或 image（兼容）")
    url: Optional[str] = Field(default=None, description="远程 URL")
    base64: Optional[str] = Field(default=None, description="Base64 数据（仅图片）")
    file_path: Optional[str] = Field(default=None, description="本地文件路径")
    filename: Optional[str] = Field(default=None, description="文件名")

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
        default="",
        description="Text message to send",
    )
    media: Optional[List[MediaContent]] = Field(
        default=None,
        description="Media content (images/files)",
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

    # Build content parts
    content_parts = []
    temp_files = []  # Track temp files for cleanup
    
    # Add text content
    if request.text:
        content_parts.append(TextContent(
            type=ContentType.TEXT,
            text=request.text
        ))
    
    # Add media content (auto-detect type)
    if request.media:
        logger.info(f"Processing {len(request.media)} media item(s)")
        for media in request.media:
            logger.info(f"Processing media item: type={media.type}, has_base64={bool(media.base64)}, has_path={bool(media.file_path)}, has_url={bool(media.url)}")
            try:
                file_url = None
                is_image = False
                
                # Handle base64: save to temp file
                if media.base64:
                    b64_data = media.base64
                    if b64_data.startswith("data:"):
                        b64_data = b64_data.split(",", 1)[1]
                    file_data = base64.b64decode(b64_data)
                    
                    # Determine file extension: priority 1) filename 2) data URI prefix 3) media.type
                    ext = None
                    if media.filename and "." in media.filename:
                        ext = media.filename.rsplit(".", 1)[1].lower()
                    if not ext:
                        mime_match = re.search(r'data:(\w+/\w+);', media.base64)
                        if mime_match:
                            mime_type = mime_match.group(1)
                            ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", 
                                      "image/webp": "webp", "text/plain": "txt", "text/markdown": "md",
                                      "application/json": "json", "audio/wav": "wav", "audio/mp4": "mp4",
                                      "video/mp4": "mp4"}
                            ext = ext_map.get(mime_type)
                    if not ext:
                        ext = "image" if media.type.lower() == "image" else "bin"
                    
                    fd, temp_path = tempfile.mkstemp(suffix=f".{ext}", prefix="copaw_")
                    try:
                        os.write(fd, file_data)
                        os.close(fd)
                        file_url = f"file://{temp_path}"
                        # Use media.type to determine content type
                        is_image = media.type.lower() == "image"
                        temp_files.append(temp_path)  # Track for cleanup
                    except Exception:
                        os.close(fd)
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                        raise
                
                # Handle local file path
                elif media.file_path:
                    file_path = Path(media.file_path)
                    if not file_path.exists():
                        logger.warning(f"File not found: {media.file_path}")
                        continue
                    try:
                        file_path.resolve().relative_to(Path.home().resolve())
                    except ValueError:
                        logger.warning(f"File path outside home directory: {media.file_path}")
                        continue
                    file_url = f"file://{file_path}"
                    # Auto-detect: image extensions
                    is_image = file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp']
                
                # Handle remote URL
                elif media.url:
                    file_url = media.url
                    # Auto-detect from URL using urlparse
                    parsed = urlparse(media.url)
                    path = parsed.path.lower()
                    is_image = any(path.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])
                
                if file_url:
                    if is_image:
                        content_parts.append(ImageContent(
                            type=ContentType.IMAGE,
                            image_url=file_url
                        ))
                    else:
                        content_parts.append(FileContent(
                            type=ContentType.FILE,
                            file_url=file_url,
                            filename=media.filename or (Path(media.file_path).name if media.file_path else "file")
                        ))
                        logger.info(f"Added FileContent: {file_url}")
            
            except Exception as e:
                logger.warning(f"Failed to process media item: {e}")
                continue

    # Send the message via channel manager
    try:
        if content_parts:
            await channel_manager.send_content(
                channel=request.channel,
                user_id=request.target_user,
                session_id=request.target_session,
                content_parts=content_parts,
                meta={"agent_id": x_agent_id} if x_agent_id else None,
            )
        else:
            logger.warning("No content to send (empty text and media)")
            return SendMessageResponse(
                success=False,
                message="No content to send (provide text or media)",
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

    finally:
        # Cleanup temp files after sending (always execute)
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
                    logger.info(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")
