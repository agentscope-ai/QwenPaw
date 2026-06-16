# -*- coding: utf-8 -*-
"""WebSocket and REST endpoints for browser takeover bridge.

WS  /ws/browser           — Chrome Extension connects here
GET /browser-bridge/info  — Extension auto-discovery endpoint
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...agents.tools.browser_bridge import (
    get_or_create_bridge,
)

logger = logging.getLogger(__name__)

browser_bridge_router = APIRouter(
    tags=["browser-bridge"],
)


@browser_bridge_router.websocket("/ws/browser")
async def browser_ws_endpoint(
    websocket: WebSocket,
) -> None:
    """Chrome Extension WebSocket endpoint."""
    await websocket.accept()

    workspace_id = websocket.query_params.get("workspace", "") or "default"
    bridge = get_or_create_bridge(workspace_id)

    try:
        await bridge.accept(websocket)
    except WebSocketDisconnect:
        logger.info(
            "Extension WS disconnected (workspace=%s)",
            workspace_id,
        )


@browser_bridge_router.get("/browser-bridge/info")
async def bridge_info() -> dict:
    """Extension auto-discovery endpoint."""
    return {
        "ok": True,
        "ws_path": "/ws/browser",
        "product": "QwenPaw",
    }
