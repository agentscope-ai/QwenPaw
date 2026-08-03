# -*- coding: utf-8 -*-
"""AG-UI protocol endpoint — AgentEvent → AG-UI → SSE."""

import asyncio
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

# SSE heartbeat interval — keeps the connection alive during long tool
# waits (e.g. tool-guard approval) without producing data frames.
_SSE_HEARTBEAT_SECONDS = 15


class AGUIErrorResponse(BaseModel):
    detail: str
    error_code: str = "agui_error"


def _get_agui_converter():
    """Return an AG-UI conversion function (AgentEvent → dict).

    Validates that ``ag-ui-protocol`` (importable as ``ag_ui``) is
    installed before proceeding.
    """

    try:
        import ag_ui  # noqa: F401  # pylint: disable=unused-import
        from agentscope.app.middleware import AGUIProtocolMiddleware
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
    """Validate the body, failing fast (422) when input is empty.

    Accepts a QwenPaw ``AgentRequest`` (not AG-UI ``RunAgentInput``).
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


def _sse_heartbeat() -> str:
    """SSE comment line used as keep-alive (not a data frame)."""
    return ": heartbeat\n\n"


async def _stream_agui(
    workspace,
    agent_request: AgentRequest,
    convert,
) -> AsyncGenerator[str, None]:
    """Stream AgentEvents, convert to AG-UI, and frame as SSE.

    Conversion failures are fatal — a ``RUN_ERROR`` frame is emitted and
    the stream terminates immediately so lifecycle-critical events are
    never silently dropped.
    """
    try:
        async for event in workspace.stream_agent_events(agent_request):
            try:
                agui_dict = convert(event)
            except Exception:
                logger.exception(
                    "Failed to convert AgentEvent to AG-UI; "
                    "terminating stream",
                )
                yield _sse_frame(
                    {
                        "type": "RUN_ERROR",
                        "message": (
                            "AG-UI conversion failed for an agent event. "
                            "The stream has been terminated."
                        ),
                    },
                )
                return
            yield _sse_frame(agui_dict)
    except Exception:  # noqa: BLE001
        logger.exception("AG-UI stream error")
        yield _sse_frame(
            {"type": "RUN_ERROR", "message": "Agent stream error"},
        )


async def _heartbeat_wrapper(
    event_stream: AsyncGenerator[str, None],
    interval: float,
) -> AsyncGenerator[str, None]:
    """Interleave SSE heartbeat comments into *event_stream*.

    Emits ``: heartbeat\\n\\n`` comments every *interval* seconds when no
    data frame has been produced, keeping the SSE connection alive through
    long idle periods (tool-guard waits, slow model responses, etc.).

    Uses ``asyncio.ensure_future`` + ``asyncio.shield`` so the timeout
    never cancels the underlying ``__anext__()`` coroutine — the same
    pattern as ``_iter_with_heartbeat`` in ``runtime/heartbeat.py``.
    Without shielding, the first heartbeat would kill the async generator
    and terminate the SSE stream.
    """
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(event_stream.__anext__())
            try:
                frame = await asyncio.wait_for(
                    asyncio.shield(pending),
                    timeout=interval,
                )
            except asyncio.TimeoutError:
                yield _sse_heartbeat()
                continue
            except StopAsyncIteration:
                pending = None
                return
            pending = None
            yield frame
    finally:
        if pending is not None and not pending.done():
            pending.cancel()


@router.post(
    "/chat",
    summary="Chat (AG-UI protocol, SSE)",
    description=(
        "Stream the agent response as standard AG-UI protocol events "
        "over SSE.  Accepts a QwenPaw ``AgentRequest`` (not AG-UI "
        "``RunAgentInput``).  AgentScope ``AgentEvent`` objects are "
        "converted through the built-in ``AGUIProtocolMiddleware``."
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

    event_stream = _stream_agui(workspace, agent_request, convert)

    return StreamingResponse(
        content=_heartbeat_wrapper(
            event_stream,
            _SSE_HEARTBEAT_SECONDS,
        ),
        media_type="text/event-stream",
        headers={
            "X-Protocol": "ag-ui",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
