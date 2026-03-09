# -*- coding: utf-8 -*-
"""Feishu (Lark) Simple Notification Router.

Provides a simple HTTP endpoint to send messages to Feishu.
Uses environment variables for target configuration (chat_id or open_id).

Example usage:
    curl -X POST \
        "http://localhost:8000/api/v1/notify/feishu?message=Server+alert"

Environment variables:
    FEISHU_NOTIFY_CHAT_ID: Target chat ID (group chat)
    FEISHU_NOTIFY_OPEN_ID: Target user open ID (private message)
"""

import json
import logging
import os
import time
import uuid
from typing import Optional, Tuple

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_feishu_channel(request: Request):
    """Get FeishuChannel instance from channel manager."""
    cm = getattr(request.app.state, "channel_manager", None)
    if cm is None:
        return None

    if hasattr(cm, "channels"):
        channels = cm.channels
        if isinstance(channels, dict):
            channel_iter = channels.values()
        else:
            channel_iter = channels
        for ch in channel_iter:
            if getattr(ch, "channel", None) == "feishu":
                return ch
    return None


def _get_target_id() -> Tuple[Optional[str], Optional[str]]:
    """Get target ID from environment variables.

    Returns:
        Tuple of (receive_id_type, receive_id) or (None, None) if not
        configured.
    """
    chat_id = os.environ.get("FEISHU_NOTIFY_CHAT_ID")
    open_id = os.environ.get("FEISHU_NOTIFY_OPEN_ID")

    if not chat_id and not open_id:
        logger.warning(
            "Feishu notify: FEISHU_NOTIFY_CHAT_ID or "
            "FEISHU_NOTIFY_OPEN_ID not set",
        )
        return None, None

    if chat_id:
        return "chat_id", chat_id
    return "open_id", open_id


async def _parse_message_from_request(
    request: Request,
    message: Optional[str],
    source: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Parse message and source from request.

    Tries to read from query params first, then from JSON body or raw body.

    Returns:
        Tuple of (message, source) with updated values.
    """
    if message is not None and source is not None:
        return message, source

    try:
        body = await request.body()
        body_str = body.decode("utf-8").strip()

        if not body_str:
            return message, source

        # Try JSON parsing
        try:
            json_data = json.loads(body_str)
            if isinstance(json_data, dict):
                if message is None and "message" in json_data:
                    message = json_data["message"]
                if source is None and "source" in json_data:
                    source = json_data["source"]
            if message is None:
                message = body_str
        except json.JSONDecodeError:
            # Not JSON, use raw body as message
            if message is None:
                message = body_str
    except Exception as e:
        logger.warning(f"Failed to read request body: {e}")

    return message, source


def _validate_request(
    receive_id_type: Optional[str],
    message: Optional[str],
) -> Optional[JSONResponse]:
    """Validate notification request parameters.

    Returns:
        JSONResponse with error if validation fails, None if valid.
    """
    if not receive_id_type:
        return JSONResponse(
            content={
                "code": 400,
                "message": "FEISHU_NOTIFY_CHAT_ID or "
                "FEISHU_NOTIFY_OPEN_ID not set",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not message or not message.strip():
        return JSONResponse(
            content={"code": 400, "message": "Message is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return None


def _build_simulated_event(
    formatted_message: str,
    source_name: str,
    receive_id_type: Optional[str],
    chat_id: Optional[str],
    open_id: Optional[str],
) -> dict:
    """Build simulated webhook event for agent processing."""
    if receive_id_type is None:
        receive_id_type = "open_id"
    chat_type = "group" if receive_id_type == "chat_id" else "p2p"
    simulated_sender_id = open_id or f"virtual_notify_{uuid.uuid4().hex[:8]}"

    return {
        "event": {
            "message": {
                "message_id": f"simulated_{uuid.uuid4().hex}_"
                f"{int(time.time())}",
                "chat_id": chat_id or open_id,
                "chat_type": chat_type,
                "message_type": "text",
                "content": json.dumps({"text": formatted_message}),
            },
            "sender": {
                "sender_type": "user",
                "sender_id": {"open_id": simulated_sender_id},
                "name": source_name,
                "nickname": source_name,
            },
        },
    }


async def _send_direct_message(
    feishu_channel,
    receive_id_type: Optional[str],
    receive_id: Optional[str],
    formatted_message: str,
) -> Tuple[bool, Optional[JSONResponse]]:
    """Send direct message via Feishu channel.

    Returns:
        Tuple of (success, error_response).
    """
    try:
        direct_result = await feishu_channel.send_text(
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            body=formatted_message,
        )

        if not direct_result:
            logger.error("Feishu notify: send_text returned False")
            return False, JSONResponse(
                content={
                    "code": 500,
                    "message": "Failed to send direct message",
                },
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return True, None
    except Exception as e:
        logger.exception(f"Feishu notify: failed to send message: {e}")
        return False, JSONResponse(
            content={"code": 500, "message": f"Internal error: {str(e)}"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


async def _queue_for_agent_processing(
    feishu_channel,
    formatted_message: str,
    source_name: str,
    receive_id_type: Optional[str],
    chat_id: Optional[str],
    open_id: Optional[str],
):
    """Queue message for agent processing via simulated webhook event."""
    simulated_event = _build_simulated_event(
        formatted_message,
        source_name,
        receive_id_type,
        chat_id,
        open_id,
    )

    if hasattr(feishu_channel, "handle_webhook_event"):
        await feishu_channel.handle_webhook_event(simulated_event)
        logger.info(
            "Feishu notify: queued for agent processing via webhook event",
        )
    else:
        logger.warning(
            "Feishu notify: handle_webhook_event not available, "
            "skipping agent processing",
        )


@router.post("/v1/notify/feishu")
async def notify_feishu(
    request: Request,
    message: Optional[str] = None,
    source: Optional[str] = None,
) -> JSONResponse:
    """Send a simple text message to Feishu.

    Args:
        message: The message content to send (from query param or body)
        source: Source identifier for the message (default: "System")

    Environment:
        FEISHU_NOTIFY_CHAT_ID: Target chat ID for group messages
        FEISHU_NOTIFY_OPEN_ID: Target user ID for private messages

    Returns:
        JSONResponse with code and message

    Examples:
        # Query parameter with source
        curl -X POST "http://localhost:8000/api/v1/notify/feishu\
?message=Test message&source=Zabbix"

        # JSON body with source
        curl -X POST http://localhost:8000/api/v1/notify/feishu \
          -H "Content-Type: application/json" \
          -d '{"message": "Test message", "source": "Zabbix"}'

        # Pipe input
        echo "Server alert" | curl -X POST -d @- \
          http://localhost:8000/api/v1/notify/feishu
    """
    # 1. Get target configuration
    receive_id_type, receive_id = _get_target_id()

    # 2. Parse message from request
    message, source = await _parse_message_from_request(
        request,
        message,
        source,
    )

    # 3. Validate request
    error_response = _validate_request(receive_id_type, message)
    if error_response:
        return error_response

    message = message.strip()
    source_name = source or "System"
    formatted_message = f"[{source_name}] {message}"

    # 4. Get FeishuChannel instance
    feishu_channel = _get_feishu_channel(request)
    if feishu_channel is None:
        logger.error("Feishu notify: Feishu channel not found")
        return JSONResponse(
            content={"code": 503, "message": "Feishu channel not available"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # 5. Send direct message
    display_id = receive_id[:20] if receive_id else "unknown"
    logger.info(
        "Feishu notify: sending message to "
        f"{receive_id_type}={display_id}... "
        f"message_len={len(formatted_message)}",
    )

    success, error_response = await _send_direct_message(
        feishu_channel,
        receive_id_type,
        receive_id,
        formatted_message,
    )
    if not success:
        return error_response

    # 6. Queue for agent processing
    chat_id = os.environ.get("FEISHU_NOTIFY_CHAT_ID")
    open_id = os.environ.get("FEISHU_NOTIFY_OPEN_ID")
    await _queue_for_agent_processing(
        feishu_channel,
        formatted_message,
        source_name,
        receive_id_type,
        chat_id,
        open_id,
    )

    return JSONResponse(
        content={
            "code": 0,
            "message": "Direct message sent and queued "
            "for agent processing",
        },
        status_code=status.HTTP_200_OK,
    )
