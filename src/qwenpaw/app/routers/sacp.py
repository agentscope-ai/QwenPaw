# -*- coding: utf-8 -*-
"""SACP (Simple Agent Communication Protocol) API endpoints.

Provides chat and health check interfaces for agent communication.
Supports both internal qwenpaw agents (via MultiAgentManager) and
external SACP agents (via HTTP).
"""

from __future__ import annotations

import logging
import traceback
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.meetings.models import SACPAgentConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sacp", tags=["sacp"])


class SACPChatRequest(BaseModel):
    """SACP chat request model."""

    session_id: str = Field(
        None,
        description="ID of the session, eg:meeting_id",
    )
    reply_agent_id: str = Field(
        None,
        description="ID of agent who needs reply",
    )
    ask_agent_id: str = Field(None, description="ID of agent who is asking")
    message: str = Field(..., description="Message content")
    stream: bool = Field(True, description="Whether to stream response")


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    agent_id: Optional[str] = None
    role: Optional[str] = None
    version: str = "1.0.0"


def _get_multi_agent_manager(request: Request) -> MultiAgentManager:
    """Get MultiAgentManager from app state."""
    if not hasattr(request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    return request.app.state.multi_agent_manager


def _get_agent_storage():
    """Load agent storage for external agent configuration."""
    from qwenpaw.app.routers.sacp_agents import _load_storage

    return _load_storage()


async def _authenticate(
    agent_id: Optional[str],
    x_auth_key: Optional[str],
) -> SACPAgentConfig:
    """Authenticate an SACP request.
    pass rules:
     1. outer agent auth check always pass
     2. inner agent auth check:
       - agent_auth_key, global_key both empty, pass if x_auth_key empty
       - x_auth_key equals agent_auth_key or global_key, can pass
    """
    storage = _get_agent_storage()

    found_agent = None
    for agent in storage.agents:
        if agent_id in (agent.id, agent.internal_agent_id, agent.name):
            found_agent = agent
            break

    if found_agent and not found_agent.is_internal and found_agent.url:
        return found_agent

    if not found_agent:
        raise HTTPException(status_code=404, detail="Agent Not Found")

    global_key = storage.global_internal_auth_key or ""
    agent_auth_key = found_agent.auth_key or global_key or ""
    x_auth = x_auth_key or ""
    if global_key == "" and agent_auth_key == "" and x_auth == "":
        return found_agent
    if x_auth != "" and x_auth in [agent_auth_key, global_key]:
        return found_agent
    raise HTTPException(status_code=401, detail="Invalid X-Auth-Key")


TIMEOUT_AGENT_CALL = 120


async def _call_internal_agent(
    session_id: str,
    task_id: str,
    message: str,
    ask_agent_id: str,
    multi_agent_manager,
    agent: SACPAgentConfig,
) -> dict:
    """Call an internal qwenpaw agent via channel callback mechanism.

    通过 channel_manager.send_text() 发送消息，绑定回调接收响应，
    异步等待响应完成。

    Args:
        session_id: str, The
        task_id: str, The task ID for the request
        message: str, The message to send
        ask_agent_id: str, The target agent ID
        multi_agent_manager: MultiAgentManager, The MultiAgentManager instance
        agent: SACPAgentConfig, The SACPAgentConfig instance for reply agent
    Returns:
        dict: {"type": "text", "content": "main message",
               "reasons": ["list of reasons: CoT or error-message"]}
    """

    channel_id = "sacp"
    reply_agent_id = agent.internal_agent_id
    content, reasons = "", []
    try:
        workspace = await multi_agent_manager.get_agent(reply_agent_id)
        channel_manager = workspace.channel_manager

        # Bind the callback to the channel
        channel = await channel_manager.get_channel(channel_id)
        if channel is None:
            content, reasons = "no reply", [f"channel 404: {channel_id}"]
        else:
            await channel.new_reply(session_id)
            native_payload = {
                "channel_id": channel_id,
                "sender_id": ask_agent_id,
                "text": message,
                "attachments": [],
                "meta": {
                    "session_id": session_id,
                    "user_id": ask_agent_id,
                    "extra": {
                        "task_id": task_id,
                        "reply_agent_id": reply_agent_id,
                        "ask_agent_id": ask_agent_id,
                    },
                },
            }

            await channel.consume_one(native_payload)
            content, reasons = await channel.wait_reply(
                session_id,
                timeout=TIMEOUT_AGENT_CALL,
            )

    except Exception as e:
        content, reasons = f"遇到问题: {str(e)}", traceback.format_exception(e)
    reply = {"type": "text", "content": content, "reasons": reasons}
    logger.info(
        f"[sacp] <{session_id},internal> get reply {reply.__str__()[:500]}",
    )
    return reply


async def _call_external_agent(
    session_id: str,
    task_id: str,
    message: str,
    ask_agent_id: str,
    reply_agent_id: str,
    url: str,
    auth_key: str,
) -> dict:
    """Call an external SACP agent via HTTP.

    Args:
        url: The external agent's SACP endpoint URL
        auth_key: The auth key for the external agent
        message: The message to send
        session_id: Optional session ID
        agent_id: Optional target agent ID

    Returns:
        dict with 'type' and 'content' keys
    """
    content, reasons = "", []
    payload = {
        "session_id": session_id,
        "task_id": task_id,
        "ask_agent_id": ask_agent_id,
        "reply_agent_id": reply_agent_id,
        "message": message,
        "stream": False,
    }

    headers = {
        "X-Auth-Key": auth_key or "",
        "X-Agent-Id": reply_agent_id,
        "X-Task-Id": task_id,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_AGENT_CALL) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            content, reasons = result.get("content"), result.get("reasons")
    except Exception as e:
        content, reasons = f"遇到问题: {str(e)}", traceback.format_exception(e)
    reply = {"type": "text", "content": content, "reasons": reasons}
    logger.info(f"[sacp] <{session_id},internal> get reply {reply}")
    return reply


@router.post("/chat")
async def sacp_chat(
    request: Request,
    request_data: SACPChatRequest,
    x_auth_key: Optional[str] = Header(None, alias="X-Auth-Key"),
) -> dict | None:
    """Handle SACP chat request.

    Routes to internal or external agent based on configuration:
    - Internal agents: call via MultiAgentManager.get_agent()
    - External agents: HTTP POST to their SACP endpoint
    """
    agent_id = request_data.reply_agent_id or request.headers.get("X-Agent-Id")

    task_id = request.headers.get("X-Task-Id") or uuid.uuid4().hex[:8]
    reply_agent = await _authenticate(agent_id, x_auth_key)
    auth_mask = (
        f"{x_auth_key[:3]}****{x_auth_key[-3:]}" if x_auth_key else "None****"
    )
    logger.info(
        "SACP[%s]: find by <id:%s,auth:%s> and got %s",
        task_id,
        agent_id,
        auth_mask,
        reply_agent.name,
    )

    session_id = (
        f"sacp@{request_data.session_id}|"
        f"{request_data.ask_agent_id[:8]}>"
        f"{reply_agent.id[:8]}:{task_id}"
    )
    # if agent not none and is inner, then goto channels.sacp.channel
    if reply_agent.is_internal and reply_agent.internal_agent_id:
        multi_agent_manager = _get_multi_agent_manager(request)
        return await _call_internal_agent(
            session_id=session_id,
            task_id=task_id,
            message=request_data.message,
            ask_agent_id=request_data.ask_agent_id,
            multi_agent_manager=multi_agent_manager,
            agent=reply_agent,
        )

    # else if agent not none then regard as outer agent
    # (handle by the server itself)
    if reply_agent and reply_agent.url:
        if x_auth_key is None:
            return {
                "type": "text",
                "content": "x_auth_key is required for external agents",
            }
        return await _call_external_agent(
            session_id=session_id,
            task_id=task_id,
            message=request_data.message,
            ask_agent_id=request_data.ask_agent_id,
            reply_agent_id=reply_agent.id,
            url=reply_agent.url,
            auth_key=x_auth_key,
        )

    # else regard as offline agent
    reply_agent_id = reply_agent.id
    logger.warning(f"[sacp] agent<{reply_agent_id}> is offline")
    return {
        "type": "text",
        "content": f"{reply_agent_id}@{reply_agent.name}: 已离线",
    }


@router.get("/health")
async def sacp_health(
    request: Request,
    agent_id: Optional[str] = None,
) -> dict:
    """Health check for SACP agents."""
    storage = _get_agent_storage()

    # Check if it's an internal agent
    agent = None
    for a in storage.agents:
        if agent_id in (a.id, a.internal_agent_id, a.name):
            agent = a
            break
    if not agent and agent_id:
        return HealthResponse(
            status="unknown",
            agent_id=agent_id or "unknown",
            role="GENERIC",
            version="1.0.0",
        ).model_dump()

    if agent and agent.is_internal:
        try:
            multi_agent_manager = _get_multi_agent_manager(request)
            workspace = await multi_agent_manager.get_agent(
                agent.internal_agent_id,
            )
            if workspace:
                # If we can get the workspace for agent_id
                return HealthResponse(
                    status="healthy",
                    agent_id=agent_id,
                    role="INTERNAL",
                    version="1.0.0",
                ).model_dump()

        except Exception:
            return HealthResponse(
                status="unknown",
                agent_id=agent_id,
                role="INTERNAL",
                version="1.0.0",
            ).model_dump()

    return HealthResponse(
        status="unknown",
        agent_id=agent_id,
        role="GENERIC",
        version="1.0.0",
    ).model_dump()
