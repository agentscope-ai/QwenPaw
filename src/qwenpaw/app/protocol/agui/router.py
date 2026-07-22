# -*- coding: utf-8 -*-
"""AG-UI protocol router for QwenPaw.

This module provides the /protocol/agui/chat endpoint that streams
agent responses in AG-UI protocol format.
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from qwenpaw.schemas import AgentRequest
from ...agent_context import get_agent_for_request
from .converter import create_converter


def _extract_session_and_payload(request_data: Union[AgentRequest, dict]):
    """Extract session and payload from request data.

    This is a simplified version of the console.py helper.
    """
    if isinstance(request_data, AgentRequest):
        channel_id = getattr(request_data, "channel", "console")
        sender_id = request_data.user_id or "default"
        session_id = request_data.session_id or "default"
        content_parts = list(request_data.input[0].content) if request_data.input else []
    else:
        channel_id = request_data.get("channel", "console")
        sender_id = request_data.get("user_id", "default")
        session_id = request_data.get("session_id", "default")
        input_data = request_data.get("input", [])
        content_parts = []
        for content_part in input_data:
            if hasattr(content_part, "content"):
                content_parts.extend(list(content_part.content or []))
            elif isinstance(content_part, dict) and "content" in content_part:
                content_parts.extend(
                    c for c in (content_part["content"] or [])
                )

    return {
        "channel_id": channel_id,
        "sender_id": sender_id,
        "session_id": session_id,
        "content_parts": content_parts,
    }


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/protocol/agui", tags=["agui-protocol"])


class AGUIErrorResponse(BaseModel):
    """错误响应模型."""

    detail: str
    error_code: str = "agui_error"


async def _stream_agui_events(
    workspace,
    request_data: Union[AgentRequest, dict],
    converter,
) -> AsyncGenerator[str, None]:
    """Generate AG-UI protocol events from agent response.

    Args:
        workspace: Workspace instance
        request_data: Request data
        converter: AG-UI event converter instance

    Yields:
        JSON-encoded AG-UI events (one per line)
    """
    try:
        # 构建 runtime request（参考 console.py 的流程）
        native_payload = _extract_session_and_payload(request_data)

        # 使用 workspace.stream_query 处理请求
        async for event in workspace.stream_query(native_payload):
            # 转换为 AG-UI 格式（使用独立的 converter 实例）
            agui_dict = converter.convert(event)
            # 输出为 JSON 行
            yield json.dumps(agui_dict, ensure_ascii=False) + "\n"
    except Exception as e:
        logger.exception("Error in AG-UI event streaming")
        # 输出错误事件
        error_event = {
            "type": "error",
            "message": str(e),
        }
        yield json.dumps(error_event, ensure_ascii=False) + "\n"


@router.post(
    "/chat",
    summary="Chat with AG-UI protocol (streaming)",
    description="Stream agent response in AG-UI protocol format. "
    "Each line is a JSON object representing an AG-UI event.",
    responses={
        500: {"model": AGUIErrorResponse, "description": "ag-ui-protocol not installed"},
    },
)
async def post_agui_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response in AG-UI protocol format.

    Args:
        request_data: Agent request (AgentRequest or dict format)
        request: FastAPI request object

    Returns:
        StreamingResponse with AG-UI protocol events (one JSON per line)

    Raises:
        HTTPException: If ag-ui-protocol is not installed
    """
    # 检查 ag-ui-protocol 是否可用
    try:
        from ag_ui.core.events import BaseEvent
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "AG-UI protocol requires 'ag-ui-protocol' package. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            ),
        ) from e

    # 获取 workspace 实例
    workspace = await get_agent_for_request(request)

    # 创建独立的 converter 实例（避免并发冲突）
    converter = create_converter()

    # 创建流式响应
    return StreamingResponse(
        content=_stream_agui_events(workspace, request_data, converter),
        media_type="text/event-stream",
        headers={
            "X-Protocol": "ag-ui",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
