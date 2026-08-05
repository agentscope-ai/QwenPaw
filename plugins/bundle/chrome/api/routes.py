# -*- coding: utf-8 -*-
"""HTTP-only Chrome extension installation and status routes."""
# pylint: disable=relative-beyond-top-level

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from qwenpaw.browser.control_link.chrome.bridge import (
    NMBridgeError,
    get_nm_bridge,
)

from ..extension_setup import (
    CHROME_EXTENSIONS_URL,
    atomic_write_json_0600,
    extension_install_status,
    BridgeEndpointUnavailable,
    InstallModeError,
    open_extension_folder,
    require_bridge_endpoint,
    setup_extension_files,
)
from ..transport.state import get_nm_bridge_route_state

api_router = APIRouter(tags=["chrome"])
router = api_router
DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"
_state = get_nm_bridge_route_state()
_SETUP_LOCK = threading.Lock()


class ExtensionSetupRequest(BaseModel):
    """Request for installing or repairing the local Chrome extension."""

    model_config = ConfigDict(extra="forbid")
    install_mode: str = "unpacked"
    reset: bool = False


def _read_existing_token(config_path: Path) -> str | None:
    """Return the installed core bridge token, if one is available."""
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = str(config.get("token") or "").strip()
    return token or None


def _write_private_bridge_config(
    config_path: Path,
    *,
    token: str,
    ws_url: str,
) -> None:
    """Atomically update the configuration shared with the core WS handler."""
    atomic_write_json_0600(config_path, {"ws_url": ws_url, "token": token})


def configure_nm_bridge(
    *,
    token: str | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> str:
    """Write the Native Messaging host's single backend configuration."""
    ws_url = require_bridge_endpoint()
    path = Path(config_path)
    if token is not None and not token.strip():
        raise ValueError("Native Messaging bridge token must not be empty")
    token = token or _read_existing_token(path) or secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_private_bridge_config(path, token=token, ws_url=ws_url)
    _state.token = token
    _state.ws_url = ws_url
    _state.config_path = path
    return token


async def get_extension_status() -> dict[str, Any]:
    """Return install state plus the core endpoint the host will contact."""
    status = extension_install_status()
    bridge_endpoint = require_bridge_endpoint()
    configured_endpoint = status.pop("ws_url", None)
    return {
        **status,
        "bridge_endpoint": bridge_endpoint,
        "configured_endpoint": configured_endpoint,
        "bridge_endpoint_stale": configured_endpoint != bridge_endpoint,
    }


def _setup_extension_files_serially(
    *,
    install_mode: str,
    reset: bool,
) -> dict[str, str | bool]:
    """Run one local setup operation at a time within this backend process."""
    with _SETUP_LOCK:
        return setup_extension_files(
            install_mode=install_mode,
            reset=reset,
        )


@api_router.get("/install-status")
async def extension_status() -> dict[str, Any]:
    """Return Chrome extension installation status."""
    return await get_extension_status()


@api_router.post("/setup")
async def extension_setup(
    request: ExtensionSetupRequest,
) -> dict[str, Any]:
    """Install or repair the extension and its Native Messaging host."""
    try:
        result = await asyncio.to_thread(
            _setup_extension_files_serially,
            install_mode=request.install_mode,
            reset=request.reset,
        )
    except InstallModeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BridgeEndpointUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**result, **await get_extension_status()}


@api_router.post("/open-chrome-extensions")
async def open_chrome_extensions() -> dict[str, str | bool | None]:
    """Ask the connected extension to open Chrome's extensions manager."""
    bridge = get_nm_bridge()
    if not bridge.is_connected():
        return {
            "opened": False,
            "url": CHROME_EXTENSIONS_URL,
            "error": "Chrome extension is not connected.",
        }
    try:
        result = await bridge.request(
            "extension.open_extensions_manager",
            timeout=5.0,
        )
    except NMBridgeError:
        return {
            "opened": False,
            "url": CHROME_EXTENSIONS_URL,
            "error": "Chrome extension could not open the extensions page.",
        }
    if not isinstance(result, dict) or result.get("opened") is not True:
        return {
            "opened": False,
            "url": CHROME_EXTENSIONS_URL,
            "error": "Chrome extension could not open the extensions page.",
        }
    return {"opened": True, "url": CHROME_EXTENSIONS_URL, "error": None}


@api_router.post("/open-extension-folder")
async def open_local_extension_folder() -> dict[str, str | bool | None]:
    """Open the unpacked extension directory."""
    return open_extension_folder()
