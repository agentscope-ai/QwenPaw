# -*- coding: utf-8 -*-
"""AG-UI protocol endpoint — raw AgentEvent → AGUI → SSE."""

import json
import logging
from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError
from starlette.responses import StreamingResponse

from qwenpaw.schemas import AgentRequest
from ...agent_context import get_agent_for_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/protocol/agui", tags=["agui-protocol"])


class AGUIErrorResponse(BaseModel):
    detail: str
    error_code: str = "agui_error"


def _get_agui_converter():
    """Return an AG-UI conversion function (AgentEvent → dict)."""

    try:
        from agentscope.app.middleware._protocol._agui import (
            AGUIProtocolMiddleware,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "AG-UI protocol requires 'ag-ui-protocol' package. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            ),
        ) from exc

    from starlette.applications import Starlette

    # AGUIProtocolMiddleware expects an ASGI app but we only call
    # _convert_to_protocol (a pure method), so a dummy app is fine.
    middleware = AGUIProtocolMiddleware(Starlette())
    # pylint: disable=protected-access
    return middleware._convert_to_protocol


def _normalize_request(
    request_data: Union[AgentRequest, dict],
) -> AgentRequest:
    """Validate the body, failing fast (422) when input is empty."""
    if isinstance(request_data, AgentRequest):
        req = request_data
    else:
        try:
            req = AgentRequest.model_validate(request_data)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid agent request: {exc}",
            ) from exc
    if not req.input:
        raise HTTPException(
            status_code=422,
            detail="Agent request must include at least one input message",
        )
    return req


def _sse_frame(payload: dict) -> str:
    """Format *payload* as a standard SSE ``data:`` frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_agui(
    workspace,
    agent_request: AgentRequest,
    convert,
) -> AsyncGenerator[str, None]:
    """Stream raw AgentScope AgentEvents, converted to AG-UI over SSE."""
    try:
        async for event in workspace.stream_query(agent_request, raw=True):
            try:
                agui_dict = convert(event)
            except Exception:
                logger.exception("Failed to convert AgentEvent; skipping")
                continue
            yield _sse_frame(agui_dict)
    except Exception as e:  # noqa: BLE001
        logger.exception("AG-UI stream error")
        yield _sse_frame({"type": "RUN_ERROR", "message": str(e)})


@router.post(
    "/chat",
    summary="Chat (AG-UI protocol, SSE)",
    description=(
        "Stream the agent response as standard AG-UI protocol events "
        "over SSE.  Raw AgentScope AgentEvents are converted through "
        "AgentScope 2.0's built-in AGUIProtocolMiddleware."
    ),
    responses={
        422: {"description": "Invalid or empty agent request"},
        500: {"model": AGUIErrorResponse},
    },
)
async def post_agui_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response as AG-UI protocol events over SSE."""
    convert = _get_agui_converter()
    agent_request = _normalize_request(request_data)
    workspace = await get_agent_for_request(request)

    return StreamingResponse(
        content=_stream_agui(workspace, agent_request, convert),
        media_type="text/event-stream",
        headers={
            "X-Protocol": "ag-ui",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
