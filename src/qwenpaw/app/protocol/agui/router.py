# -*- coding: utf-8 -*-
"""AgentScope 2.0 native event stream — SSE endpoint at /protocol/agui/chat."""

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


def _normalize_request(
    request_data: Union[AgentRequest, dict],
) -> AgentRequest:
    """Validate the body, failing fast (422) when input is empty.

    FastAPI may deliver a ``dict`` that does not fully match the
    AgentRequest schema.  Passing a raw channel-native dict to
    ``workspace.stream_query`` would drop the user's message.
    """
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


async def _stream_events(
    workspace,
    agent_request: AgentRequest,
) -> AsyncGenerator[str, None]:
    """Stream AgentScope native events from the workspace as SSE frames.

    Yields one ``data: <json>\\n\\n`` frame per event.  A serialization
    failure is logged and skipped so the stream is not aborted by one
    unexpected envelope shape.
    """
    try:
        async for event in workspace.stream_query(agent_request):
            try:
                ev = (
                    event.model_dump(
                        exclude_none=True,
                    )
                    if hasattr(event, "model_dump")
                    else vars(event)
                )
            except Exception:
                logger.exception("Failed to serialize event; skipping")
                continue
            yield _sse_frame(ev)
    except Exception as e:  # noqa: BLE001
        logger.exception("Event stream error")
        yield _sse_frame({"type": "run_error", "message": str(e)})


@router.post(
    "/chat",
    summary="Stream AgentScope 2.0 native events",
    description=(
        "Stream the agent's native AgentScope 2.0 event stream over SSE. "
        "Each event is a ``data: <json>`` line per the SSE spec."
    ),
    responses={
        422: {"description": "Invalid or empty agent request"},
    },
)
async def post_agui_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream raw AgentScope 2.0 events from the agent over SSE."""
    agent_request = _normalize_request(request_data)
    workspace = await get_agent_for_request(request)

    return StreamingResponse(
        content=_stream_events(workspace, agent_request),
        media_type="text/event-stream",
        headers={
            "X-Protocol": "ag-ui",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
