# -*- coding: utf-8 -*-
"""AG-UI protocol router for QwenPaw.

This module provides the /protocol/agui/chat endpoint that streams
agent responses in AG-UI protocol format (standard SSE transport).
"""
import json
import logging
from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from qwenpaw.schemas import AgentRequest
from ...agent_context import get_agent_for_request
from .converter import create_converter, create_run_error_event


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/protocol/agui", tags=["agui-protocol"])


class AGUIErrorResponse(BaseModel):
    """错误响应模型."""

    detail: str
    error_code: str = "agui_error"


def _normalize_request(
    request_data: Union[AgentRequest, dict],
) -> AgentRequest:
    """Ensure request_data is a proper AgentRequest with populated input.

    FastAPI may deliver the body as a dict (when the JSON does not fully
    match the schema) or as a validated AgentRequest. We coerce both to a
    real AgentRequest so that ``workspace.stream_query`` receives a request
    whose ``input`` field actually carries the user's message — the native
    ``{content_parts, ...}`` dict shape is channel-internal and must NOT be
    passed to the runtime directly (its ``input`` would default to empty).
    """
    if isinstance(request_data, AgentRequest):
        return request_data
    return AgentRequest.model_validate(request_data)


def _sse_frame(payload: dict) -> str:
    """Serialize an AG-UI event dict into a standard SSE frame.

    SSE spec: each event is ``data: <json>\\n\\n``.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_agui_events(
    workspace,
    agent_request: AgentRequest,
    converter,
) -> AsyncGenerator[str, None]:
    """Generate AG-UI protocol events from agent response as SSE frames.

    Args:
        workspace: Workspace instance
        agent_request: Validated AgentRequest carrying the user's input
        converter: AG-UI event converter instance (per-request)

    Yields:
        SSE frames (``data: <json>\\n\\n``), one per AG-UI event.
    """
    try:
        # Pass the real AgentRequest (with input) to the runtime.
        async for event in workspace.stream_query(agent_request):
            try:
                agui_dict = converter.convert(event)
            except Exception:
                # A single malformed/unexpected event must not abort the
                # whole stream — log and continue with the next event.
                logger.exception(
                    "Failed to convert agent event to AG-UI format; skipping",
                )
                continue
            yield _sse_frame(agui_dict)
    except Exception as e:  # noqa: BLE001 - surface as a protocol error event
        logger.exception("Error in AG-UI event streaming")
        # Emit a spec-compliant RUN_ERROR event and end the stream.
        yield _sse_frame(create_run_error_event(str(e)))


@router.post(
    "/chat",
    summary="Chat with AG-UI protocol (streaming)",
    description="Stream agent response in AG-UI protocol format over SSE. "
    "Each event is a ``data: <json>`` line per the Server-Sent Events spec.",
    responses={
        500: {"model": AGUIErrorResponse, "description": "ag-ui-protocol not installed"},
    },
)
async def post_agui_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response in AG-UI protocol format (SSE).

    Args:
        request_data: Agent request (AgentRequest or dict format)
        request: FastAPI request object

    Returns:
        StreamingResponse with AG-UI protocol events as SSE frames.

    Raises:
        HTTPException: If ag-ui-protocol is not installed
    """
    # 检查 ag-ui-protocol 是否可用
    try:
        from ag_ui.core.events import BaseEvent  # noqa: F401
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "AG-UI protocol requires 'ag-ui-protocol' package. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            ),
        ) from e

    # 规范化为带 input 的 AgentRequest，避免用户消息被丢弃
    agent_request = _normalize_request(request_data)

    # 获取 workspace 实例
    workspace = await get_agent_for_request(request)

    # 创建独立的 converter 实例（避免并发冲突）
    converter = create_converter()

    # 创建流式响应（标准 SSE 传输）
    return StreamingResponse(
        content=_stream_agui_events(workspace, agent_request, converter),
        media_type="text/event-stream",
        headers={
            "X-Protocol": "ag-ui",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
