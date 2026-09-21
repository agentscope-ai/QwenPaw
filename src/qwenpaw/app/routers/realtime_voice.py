"""Authenticated relay for native realtime voice sessions.

HTTP/WebSocket boundary only: it authorizes requests, encodes/decodes the
renderer frame protocol and wires the socket lifecycle to
``RealtimeVoiceService``. All session business logic (coordination, admission,
presentation, provider I/O) lives in ``qwenpaw.app.realtime_voice``; keep this
module free of it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..agent_context import get_agent_for_request
from ..realtime_voice.contracts import (
    PROTOCOL_VERSION,
    AudioFrame,
    AudioFrameKind,
    CreateSessionRequest,
    RealtimeVoiceServiceError,
    SessionBootstrap,
    decode_audio_frame,
    encode_audio_frame,
)
from ..realtime_voice.coordinator import VoiceCoordinator
from ..realtime_voice.service import (
    LiveVoiceSession,
    RealtimeVoiceService,
    request_principal,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime-voice", tags=["realtime-voice"])


def _service(request_or_websocket) -> RealtimeVoiceService:
    service = getattr(
        request_or_websocket.app.state,
        "realtime_voice_service",
        None,
    )
    if service is None:
        raise RealtimeVoiceServiceError(
            "service_unavailable",
            "Realtime Voice service is not initialized.",
            503,
        )
    return service


def _raise_http(exc: RealtimeVoiceServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, **exc.details},
    ) from exc


@router.get("/capabilities")
async def get_realtime_voice_capabilities(
    request: Request,
    workspace: Annotated[Any, Depends(get_agent_for_request)],
) -> dict:
    try:
        return _service(request).capabilities(workspace)
    except RealtimeVoiceServiceError as exc:
        _raise_http(exc)


@router.post("/sessions", response_model=SessionBootstrap)
async def create_realtime_voice_session(
    body: CreateSessionRequest,
    request: Request,
    workspace: Annotated[Any, Depends(get_agent_for_request)],
) -> SessionBootstrap:
    try:
        return await _service(request).create_session(
            workspace,
            request_principal(request),
            body,
        )
    except RealtimeVoiceServiceError as exc:
        _raise_http(exc)


@router.delete("/sessions/{session_id}")
async def release_realtime_voice_session(
    session_id: str,
    request: Request,
    workspace: Annotated[Any, Depends(get_agent_for_request)],
) -> dict[str, bool]:
    try:
        await _service(request).release_session(
            session_id,
            request_principal(request),
            workspace.agent_id,
        )
        return {"released": True}
    except RealtimeVoiceServiceError as exc:
        _raise_http(exc)


async def _client_to_coordinator(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    live: LiveVoiceSession,
    coordinator: VoiceCoordinator,
) -> None:
    last_sequence: int | None = None
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        binary = message.get("bytes")
        if binary is not None:
            frame = decode_audio_frame(binary)
            if frame.kind != AudioFrameKind.INPUT_PCM16:
                raise ValueError("renderer sent a non-input audio frame")
            if (
                frame.sample_rate != live.media.input_sample_rate
                or frame.channels != live.media.channels
            ):
                raise ValueError("renderer audio format does not match session")
            expected = 0 if last_sequence is None else (last_sequence + 1) % (2**32)
            if frame.sequence != expected:
                raise ValueError("renderer audio sequence is not contiguous")
            last_sequence = frame.sequence
            await coordinator.send_audio(frame.payload)
            continue

        raw = message.get("text")
        if raw is None:
            continue
        try:
            control = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid realtime voice control JSON") from exc
        control_type = control.get("type") if isinstance(control, dict) else None
        if control_type == "interrupt":
            await coordinator.interrupt()
        elif control_type == "output.playback":
            if control.get("generation") != live.generation:
                continue
            output_id, status = control.get("output_id"), control.get("status")
            if not isinstance(output_id, str) or status not in {
                "drained",
                "interrupted",
                "failed",
            }:
                raise ValueError("invalid playback feedback")
            coordinator.playback_feedback(output_id, status)
        elif control_type == "agent.observe":
            await coordinator.observe_agent_run()
        elif control_type == "ping":
            async with send_lock:
                await websocket.send_json(
                    {
                        "type": "pong",
                        "generation": live.generation,
                        "nonce": control.get("nonce"),
                    }
                )
        elif control_type == "stop":
            return
        else:
            raise ValueError("unknown realtime voice control message")


async def _coordinator_to_client(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    live: LiveVoiceSession,
    coordinator: VoiceCoordinator,
) -> None:
    output_sequence = 0
    async for event in coordinator.events():
        if event.kind == "output.audio" and event.audio is not None:
            async with send_lock:
                await websocket.send_bytes(
                    encode_audio_frame(
                        AudioFrame(
                            kind=AudioFrameKind.OUTPUT_PCM16,
                            sequence=output_sequence,
                            sample_rate=live.media.output_sample_rate,
                            channels=live.media.channels,
                            payload=event.audio,
                        )
                    )
                )
            output_sequence = (output_sequence + 1) % (2**32)
            continue

        client_event = {
            "type": event.kind,
            "event_id": event.event_id,
            "generation": live.generation,
            "chat_id": live.chat.id,
            **event.data,
        }
        if event.correlation_id:
            client_event["correlation_id"] = event.correlation_id
        if event.response_origin:
            client_event["response_origin"] = event.response_origin
        async with send_lock:
            await websocket.send_json(client_event)


@router.websocket("/sessions/{session_id}/stream")
async def realtime_voice_stream(
    websocket: WebSocket,
    session_id: str,
) -> None:
    token = websocket.query_params.get("token", "")
    try:
        service = _service(websocket)
        if not token:
            raise RealtimeVoiceServiceError(
                "invalid_token",
                "Realtime Voice authorization is missing.",
                401,
            )
        live = await service.consume_grant(session_id, token)
    except RealtimeVoiceServiceError:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return

    await websocket.accept()
    close_code = 1000
    send_lock = asyncio.Lock()
    try:
        coordinator = await service.connect(live)
        async with send_lock:
            await websocket.send_json(
                {
                    "type": "session.connected",
                    "generation": live.generation,
                    "protocol_version": PROTOCOL_VERSION,
                }
            )
        timeout_task = asyncio.create_task(
            asyncio.sleep(live.config.max_session_seconds)
        )
        client_task = asyncio.create_task(
            _client_to_coordinator(
                websocket,
                send_lock,
                live,
                coordinator,
            )
        )
        coordinator_task = asyncio.create_task(
            _coordinator_to_client(
                websocket,
                send_lock,
                live,
                coordinator,
            )
        )
        tasks = {client_task, coordinator_task, timeout_task}
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        done_results = dict(
            zip(
                done,
                await asyncio.gather(*done, return_exceptions=True),
                strict=True,
            )
        )
        await asyncio.gather(*pending, return_exceptions=True)

        close_reason: str | None
        if coordinator_task in done:
            result = done_results[coordinator_task]
            if isinstance(result, BaseException):
                raise result
            # A clean coordinator stream has already forwarded its terminal
            # event. Any simultaneous input send belongs to the closed session.
            close_reason = None
        elif client_task in done:
            result = done_results[client_task]
            if isinstance(result, BaseException):
                raise result
            close_reason = "stopped"
        else:
            close_reason = "max_duration"

        if close_reason is not None:
            with suppress(Exception):
                async with send_lock:
                    await websocket.send_json(
                        {
                            "type": "session.closed",
                            "generation": live.generation,
                            "reason": close_reason,
                        }
                    )
    except WebSocketDisconnect:
        pass
    except ValueError as exc:
        close_code = 1003
        logger.info("Realtime Voice protocol error: %s", exc)
        with suppress(Exception):
            async with send_lock:
                await websocket.send_json(
                    {
                        "type": "error",
                        "generation": live.generation,
                        "code": "protocol_error",
                        "message": str(exc),
                        "recoverable": False,
                    }
                )
    except Exception:
        close_code = 1011
        logger.warning("Realtime Voice stream failed", exc_info=True)
        with suppress(Exception):
            async with send_lock:
                await websocket.send_json(
                    {
                        "type": "error",
                        "generation": live.generation,
                        "code": "upstream_unavailable",
                        "message": "Realtime voice connection failed.",
                        "recoverable": True,
                    }
                )
    finally:
        await service.end_session(live)
        with suppress(Exception):
            await websocket.close(code=close_code)


__all__ = ["router"]
