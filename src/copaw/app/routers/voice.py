# -*- coding: utf-8 -*-
"""Voice channel routers.

Two routers are exported:

* ``voice_router`` -- Twilio-facing endpoints mounted at the app root
  (``/voice/incoming``, ``/voice/ws``, ``/voice/status-callback``).
* ``voice_api_router`` -- Console-facing API endpoints mounted under
  ``/api/`` (``/api/voice/status``, ``/api/voice/numbers/search``, etc.).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Twilio-facing router (mounted at root level)
# ---------------------------------------------------------------------------
voice_router = APIRouter(tags=["voice"])


def _get_voice_channel(request_or_ws):
    """Retrieve the VoiceChannel from app state, or None."""
    app = getattr(request_or_ws, "app", None)
    if not app:
        return None
    cm = getattr(app.state, "channel_manager", None)
    if not cm:
        return None
    for ch in cm.channels:
        if ch.channel == "voice":
            return ch
    return None


async def _validate_twilio_signature(request: Request) -> None:
    """Validate that the request originated from Twilio.

    Uses Twilio's ``RequestValidator`` to verify the
    ``X-Twilio-Signature`` header.  If the voice channel has no
    auth token configured the check is skipped (dev mode).
    """
    voice_ch = _get_voice_channel(request)
    if not voice_ch:
        return

    auth_token = getattr(voice_ch.config, "twilio_auth_token", "")
    if not auth_token:
        # No token configured -- skip validation (local dev)
        return

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Missing Twilio signature")

    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    form = await request.form()
    url = str(request.url)
    params = {k: str(v) for k, v in form.items()}

    if not validator.validate(url, params, signature):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@voice_router.post(
    "/voice/incoming",
    dependencies=[Depends(_validate_twilio_signature)],
)
async def voice_incoming(request: Request) -> Response:
    """Twilio webhook: return TwiML for an incoming call."""
    from ..channels.voice.twiml import (
        build_busy_twiml,
        build_conversation_relay_twiml,
        build_error_twiml,
    )

    voice_ch = _get_voice_channel(request)
    if not voice_ch:
        twiml = build_error_twiml("Voice channel is not available.")
        return Response(content=twiml, media_type="application/xml")

    config = voice_ch.config
    max_calls = getattr(config, "max_concurrent_calls", 1)
    if voice_ch.session_mgr.active_count() >= max_calls:
        twiml = build_busy_twiml()
        return Response(content=twiml, media_type="application/xml")

    # Build the WebSocket URL for ConversationRelay
    wss_url = voice_ch.get_tunnel_wss_url()
    if not wss_url:
        twiml = build_error_twiml("Tunnel not available. Please try later.")
        return Response(content=twiml, media_type="application/xml")

    ws_url = f"{wss_url}/voice/ws"
    twiml = build_conversation_relay_twiml(
        ws_url,
        welcome_greeting=getattr(
            config,
            "welcome_greeting",
            "Hi! This is CoPaw. How can I help you?",
        ),
        tts_provider=getattr(config, "tts_provider", "google"),
        tts_voice=getattr(config, "tts_voice", "en-US-Journey-D"),
        stt_provider=getattr(config, "stt_provider", "deepgram"),
        language=getattr(config, "language", "en-US"),
    )
    return Response(content=twiml, media_type="application/xml")


@voice_router.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket) -> None:
    """ConversationRelay WebSocket endpoint."""
    from ..channels.voice.conversation_relay import ConversationRelayHandler

    voice_ch = _get_voice_channel(websocket)
    if not voice_ch:
        await websocket.close(code=1008, reason="Voice channel not available")
        return

    await websocket.accept()

    handler = ConversationRelayHandler(
        ws=websocket,
        process=voice_ch.process,
        session_mgr=voice_ch.session_mgr,
        channel_type=voice_ch.channel,
    )
    try:
        await handler.handle()
    except WebSocketDisconnect:
        logger.info("Voice WS disconnected: call_sid=%s", handler.call_sid)
    finally:
        if handler.call_sid:
            voice_ch.session_mgr.end_session(handler.call_sid)


@voice_router.post(
    "/voice/status-callback",
    dependencies=[Depends(_validate_twilio_signature)],
)
async def voice_status_callback(request: Request) -> Response:
    """Twilio call status change webhook."""
    form = await request.form()
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    logger.info(
        "Call status callback: call_sid=%s status=%s",
        call_sid,
        call_status,
    )

    if call_status in ("completed", "busy", "no-answer", "canceled", "failed"):
        voice_ch = _get_voice_channel(request)
        if voice_ch:
            voice_ch.session_mgr.end_session(str(call_sid))

    return Response(content="", status_code=204)


# ---------------------------------------------------------------------------
# Console-facing API router (mounted under /api/)
# NOTE: Authentication is not yet implemented for any CoPaw API route.
# When project-wide auth is added, these endpoints should be gated too.
# ---------------------------------------------------------------------------
voice_api_router = APIRouter(prefix="/voice", tags=["voice"])


@voice_api_router.get("/status")
async def voice_status(request: Request):
    """Return voice channel status: tunnel, active calls, phone number."""
    voice_ch = _get_voice_channel(request)
    if not voice_ch:
        return {
            "enabled": False,
            "tunnel_url": None,
            "active_calls": 0,
            "phone_number": None,
        }

    config = voice_ch.config
    return {
        "enabled": getattr(config, "enabled", False),
        "tunnel_url": voice_ch.get_tunnel_url(),
        "active_calls": voice_ch.session_mgr.active_count(),
        "phone_number": getattr(config, "phone_number", ""),
        "phone_number_sid": getattr(config, "phone_number_sid", ""),
        "sessions": [
            {
                "call_sid": s.call_sid,
                "from_number": s.from_number,
                "to_number": s.to_number,
                "started_at": s.started_at.isoformat(),
                "status": s.status,
            }
            for s in voice_ch.session_mgr.all_sessions()
        ],
    }


@voice_api_router.get("/numbers/search")
async def voice_numbers_search(
    request: Request,
    country: str = "US",
    area_code: Optional[str] = None,
):
    """Search for available Twilio phone numbers."""
    voice_ch = _get_voice_channel(request)
    if not voice_ch or not voice_ch.twilio_mgr:
        return {"error": "Voice channel or Twilio credentials not configured"}

    try:
        numbers = await voice_ch.twilio_mgr.search_available_numbers(
            country=country,
            area_code=area_code,
        )
        return {
            "numbers": [
                {
                    "phone_number": n.phone_number,
                    "friendly_name": n.friendly_name,
                    "locality": n.locality,
                    "region": n.region,
                    "country": n.country,
                }
                for n in numbers
            ],
        }
    except Exception as e:
        logger.exception("Failed to search numbers")
        return {"error": str(e)}


@voice_api_router.post("/numbers/provision")
async def voice_numbers_provision(request: Request):
    """Provision (purchase) a Twilio phone number."""
    voice_ch = _get_voice_channel(request)
    if not voice_ch or not voice_ch.twilio_mgr:
        return {"error": "Voice channel or Twilio credentials not configured"}

    body = await request.json()
    phone_number = body.get("phone_number", "")
    if not phone_number:
        return {"error": "phone_number is required"}

    tunnel_url = voice_ch.get_tunnel_url()
    if not tunnel_url:
        return {"error": "Tunnel is not running; cannot configure webhook"}
    webhook_url = f"{tunnel_url}/voice/incoming"

    try:
        result = await voice_ch.twilio_mgr.provision_number(
            phone_number=phone_number,
            voice_url=webhook_url,
        )
        return {
            "sid": result.sid,
            "phone_number": result.phone_number,
            "friendly_name": result.friendly_name,
        }
    except Exception as e:
        logger.exception("Failed to provision number")
        return {"error": str(e)}


@voice_api_router.get("/calls")
async def voice_calls(request: Request):
    """List call sessions (active and recent)."""
    voice_ch = _get_voice_channel(request)
    if not voice_ch:
        return {"calls": []}

    return {
        "calls": [
            {
                "call_sid": s.call_sid,
                "from_number": s.from_number,
                "to_number": s.to_number,
                "started_at": s.started_at.isoformat(),
                "status": s.status,
            }
            for s in voice_ch.session_mgr.all_sessions()
        ],
    }
