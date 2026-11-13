# -*- coding: utf-8 -*-
"""Core Native Messaging WebSocket route for Chrome control links."""

# pylint: disable=too-many-branches,too-many-statements

from __future__ import annotations

import contextlib
import json
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.responses import JSONResponse

from ....utils.logging import sanitize_log_value
from ....utils.io_utils import write_json_atomic
from .bridge import get_nm_bridge, shutdown_nm_bridge as shutdown_global_bridge
from .state import get_nm_bridge_route_state

ws_router = APIRouter(prefix="/ws", tags=["browser"])

DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"
DEFAULT_WS_URL = "ws://127.0.0.1:8088/api/ws/chrome"
BRIDGE_DISCONNECTED = "bridge_disconnected"
logger = logging.getLogger(__name__)


def resolve_default_ws_url() -> str:
    """Resolve the WebSocket endpoint of the current core API instance."""
    try:
        from qwenpaw.config.utils import read_last_api

        api_info = read_last_api()
    except Exception:
        api_info = None
    if not api_info:
        return DEFAULT_WS_URL
    host, port = api_info
    host = "127.0.0.1" if host in {"", "0.0.0.0"} else str(host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"ws://{host}:{port}/api/ws/chrome"


_bridge_state = get_nm_bridge_route_state()
if _bridge_state.config_path is None:
    _bridge_state.config_path = DEFAULT_CONFIG_PATH


def _read_existing_token(config_path: Path) -> str | None:
    if not config_path.exists():
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = str(raw.get("token") or "").strip()
    return token or None


def _write_private_bridge_config(
    config_path: Path,
    *,
    token: str,
    ws_url: str,
) -> None:
    write_json_atomic(
        config_path,
        {"ws_url": ws_url, "token": token},
        new_file_mode=0o600,
    )


def configure_nm_bridge(
    *,
    token: str | None = None,
    ws_url: str | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> str:
    """Configure Native Messaging authentication and host bridge config."""
    ws_url = ws_url or resolve_default_ws_url()
    config_path = Path(config_path)
    token = token or _read_existing_token(config_path)
    token = token or secrets.token_urlsafe(32)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private_bridge_config(
        config_path,
        token=token,
        ws_url=ws_url,
    )

    _bridge_state.token = token
    _bridge_state.config_path = config_path
    return token


def _expected_token() -> str:
    """Return the bridge token, treating the config file as the authority.

    The plugin installer rotates the token in-place on repair(reset); the
    in-memory value is only a fallback for transient read failures and
    must never win over a readable config file.
    """
    config_path = _bridge_state.config_path or DEFAULT_CONFIG_PATH
    file_token = _read_existing_token(config_path)
    if file_token:
        _bridge_state.token = file_token
        return file_token
    if _bridge_state.token is not None:
        return _bridge_state.token
    return configure_nm_bridge(config_path=config_path)


def _request_token(websocket: WebSocket) -> str:
    header = websocket.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return websocket.query_params.get("token", "").strip()


async def _deny(websocket: WebSocket, status_code: int, detail: str) -> None:
    client = getattr(getattr(websocket, "client", None), "host", "unknown")
    logger.warning("browser.ws.deny client=%s reason=%s", client, detail)
    await websocket.send_denial_response(
        JSONResponse({"detail": detail}, status_code=status_code),
    )


def _resolve_bridge(websocket: WebSocket) -> Any | None:
    bridge = getattr(websocket.app.state, "nm_bridge", None)
    if bridge is not None:
        return bridge

    return get_nm_bridge()


def _default_bridge() -> Any | None:
    return get_nm_bridge()


async def _drop_connected_websockets(
    bridge: Any | None,
    *,
    reason: str = "replaced",
) -> None:
    if bridge is None or not hasattr(bridge, "websocket"):
        return
    websocket = bridge.websocket
    if websocket is None:
        return
    await bridge.detach_websocket(websocket, reason=reason)
    with contextlib.suppress(Exception):
        await websocket.close(code=1000)


async def shutdown_nm_bridge() -> None:
    """Close the active native bridge connection before plugin unload."""
    bridge = _default_bridge()
    await _drop_connected_websockets(bridge, reason="shutdown")
    await shutdown_global_bridge()


def prime_bridge_token() -> None:
    """Materialize the bridge token before the first websocket handshake."""
    _expected_token()


@ws_router.websocket("/chrome")
async def nm_bridge_ws(websocket: WebSocket) -> None:
    """Accept the Native Messaging host WebSocket connection."""
    if not secrets.compare_digest(
        _request_token(websocket) or "",
        _expected_token(),
    ):
        await _deny(websocket, 401, "Invalid Native Messaging bridge token")
        return

    bridge = _resolve_bridge(websocket)
    if bridge is not None and getattr(bridge, "websocket", None) is not None:
        await _drop_connected_websockets(bridge, reason="replaced")

    await websocket.accept()
    client = getattr(getattr(websocket, "client", None), "host", "unknown")
    started = datetime.now(UTC)
    logger.info("browser.ws.accept client=%s", client)

    if bridge is not None and hasattr(bridge, "attach_websocket"):
        await bridge.attach_websocket(websocket)

    protocol_failure: tuple[str, str] | None = None
    bridge_detached = False
    close_code: int | None = None
    close_reason = ""
    try:
        while True:
            message = await websocket.receive_json()
            if bridge is not None and not bridge.owns_websocket(websocket):
                if bridge is not None and hasattr(bridge, "detach_websocket"):
                    await bridge.detach_websocket(websocket)
                    bridge_detached = True
                with contextlib.suppress(Exception):
                    await websocket.close(code=1000)
                return

            response = None
            if bridge is not None and hasattr(bridge, "handle_ws_message"):
                response = await bridge.handle_ws_message(message)
            if response is not None:
                await websocket.send_json(response)

            if message.get("type") == "hello":
                if _is_successful_hello_ack(response):
                    # pylint: disable-next=protected-access
                    bridge._mark_ready(websocket, message)
                    continue
                protocol_failure = _hello_failure(response)
                with contextlib.suppress(Exception):
                    await websocket.close(code=1002)
                return

            if _observe_bridge_message(bridge, websocket, message):
                if bridge is not None and hasattr(bridge, "detach_websocket"):
                    params = message.get("params")
                    reason = str(
                        params.get("reason")
                        if isinstance(params, dict)
                        else "disconnected",
                    )
                    await bridge.detach_websocket(websocket, reason=reason)
                    bridge_detached = True
                with contextlib.suppress(Exception):
                    await websocket.close(code=1000)
                return
    except WebSocketDisconnect as exc:
        close_code = exc.code
        close_reason = exc.reason
    finally:
        if (
            not bridge_detached
            and bridge is not None
            and hasattr(bridge, "detach_websocket")
        ):
            await bridge.detach_websocket(
                websocket,
                close_code=close_code,
                close_reason=close_reason,
            )
        logger.info(
            "browser.ws.disconnect client=%s reason=%s duration_s=%.1f "
            "close_code=%s close_reason=%s",
            client,
            protocol_failure[0]
            if protocol_failure
            else "websocket_disconnect",
            (datetime.now(UTC) - started).total_seconds(),
            close_code,
            sanitize_log_value(close_reason),
        )


def _is_successful_hello_ack(response: Any) -> bool:
    return bool(
        isinstance(response, dict)
        and response.get("type") == "hello_ack"
        and response.get("status") == "ok",
    )


def _hello_failure(response: Any) -> tuple[str, str]:
    if not isinstance(response, dict):
        return (
            "bridge_hello_unavailable",
            "Native Messaging bridge did not acknowledge hello.",
        )
    return (
        str(response.get("code") or "bridge_hello_rejected"),
        str(
            response.get("message")
            or "Native Messaging bridge rejected hello.",
        ),
    )


def _observe_bridge_message(
    bridge: Any | None,
    websocket: WebSocket,
    message: dict[str, Any],
) -> bool:
    if bridge is None or not bridge.owns_websocket(websocket):
        return False
    method = str(message.get("method") or "")
    params = message.get("params")
    payload = params if isinstance(params, dict) else {}
    if method == "bridge.connected":
        # pylint: disable-next=protected-access
        bridge._update_extension_version(payload)
    elif method == "bridge.disconnected":
        return True
    return False
