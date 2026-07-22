# -*- coding: utf-8 -*-
"""AG-UI protocol router — SSE endpoint at /protocol/agui/chat."""

import json
import logging
from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError
from starlette.responses import StreamingResponse

from qwenpaw.schemas import AgentRequest
from ...agent_context import get_agent_for_request
from .converter import create_converter, create_run_error_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/protocol/agui", tags=["agui-protocol"])


class AGUIErrorResponse(BaseModel):
    detail: str
    error_code: str = "agui_error"


def _normalize_request(request_data: Union[AgentRequest, dict]) -> AgentRequest:
    """Coerce the request body to a validated AgentRequest with non-empty input.

    FastAPI may deliver a ``dict`` when the JSON does not fully match the
    AgentRequest schema.  Passing a raw channel-native dict (``{content_parts,
    ...}``) to ``workspace.stream_query`` would drop the user's message because
    ``Runtime._normalize`` creates an ``AgentRequest`` whose ``input`` defaults
    to an empty list.  We re-validate here so we can fail fast with a clear
    422 if the body is malformed or has no input.
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


async def _stream_agui_events(
    workspace,
    agent_request: AgentRequest,
    converter,
) -> AsyncGenerator[str, None]:
    """Stream agent output as AG-UI SSE frames.

    Yields one ``data: <json>\\n\\n`` frame per AG-UI event.  A single
    conversion failure is logged and skipped so the stream is not aborted
    by one unexpected envelope shape.
    """
    try:
        async for event in workspace.stream_query(agent_request):
            try:
                agui_dict = converter.convert(event)
            except Exception:
                logger.exception(
                    "Failed to convert agent event to AG-UI format; skipping",
                )
                continue
            yield _sse_frame(agui_dict)
    except Exception as e:  # noqa: BLE001
        logger.exception("AG-UI event stream error")
        yield _sse_frame(create_run_error_event(str(e)))


@router.post(
    "/chat",
    summary="Chat with AG-UI protocol (streaming)",
    description=(
        "Stream agent response in AG-UI protocol format over SSE. "
        "Each event is a ``data: <json>`` line per the SSE spec."
    ),
    responses={
        422: {"description": "Invalid or empty agent request"},
        500: {"model": AGUIErrorResponse, "description": "ag-ui-protocol not installed"},
    },
)
async def post_agui_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response in AG-UI protocol format (SSE)."""
    try:
        from ag_ui.core.events import BaseEvent  # noqa: F401,F811
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "AG-UI protocol requires 'ag-ui-protocol' package. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            ),
        ) from exc

    agent_request = _normalize_request(request_data)
    workspace = await get_agent_for_request(request)
    converter = create_converter()

    return StreamingResponse(
        content=_stream_agui_events(workspace, agent_request, converter),
        media_type="text/event-stream",
        headers={
            "X-Protocol": "ag-ui",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
