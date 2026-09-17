# -*- coding: utf-8 -*-
"""Tauri sidecar environment variable helpers.

Keep this dependency-light: the Tauri entry imports it before qwenpaw.constant
has read import-time environment variables.
"""

import os
import re

DESKTOP_APP_ENV = "QWENPAW_DESKTOP_APP"
DESKTOP_AUTH_ENV = "QWENPAW_DESKTOP_AUTH"
DESKTOP_CORS_ORIGINS_ENV = "QWENPAW_CORS_ORIGINS"
DESKTOP_SHUTDOWN_TOKEN_ENV = "QWENPAW_DESKTOP_SHUTDOWN_TOKEN"
DESKTOP_MANAGED_PLAYWRIGHT_ENV = "QWENPAW_DESKTOP_MANAGED_PLAYWRIGHT"
DESKTOP_READY_PREFIX = "QWENPAW_BACKEND_READY"
DESKTOP_SESSION_ENV = "QWENPAW_DESKTOP_SESSION"
DESKTOP_SESSION_HEADER = "X-Desktop-Session"

# Consume the launch credential before initialization can spawn tools. Only
# this backend process keeps it; normal subprocess environment inheritance must
# not turn every tool into a desktop API client.
_desktop_token = ""
_desktop_origin = ""


def desktop_auth_enabled() -> bool:
    """Only a host with native request authentication enables this boundary."""
    return (
        os.environ.get(DESKTOP_APP_ENV) == "1"
        and os.environ.get(DESKTOP_AUTH_ENV) == "1"
    )


def consume_desktop_session() -> None:
    global _desktop_token, _desktop_origin
    token = os.environ.pop(DESKTOP_SESSION_ENV, "")
    _desktop_token = ""
    _desktop_origin = ""
    if not desktop_auth_enabled():
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise RuntimeError("Desktop launch session is missing or invalid")
    _desktop_token = token


def set_desktop_origin(port: int) -> None:
    global _desktop_origin
    if not desktop_auth_enabled():
        return
    if not _desktop_token or not 0 < port < 65536:
        raise RuntimeError("Desktop launch session is not initialized")
    _desktop_origin = f"http://127.0.0.1:{port}"


def get_desktop_session() -> tuple[str, str] | None:
    """Return the private process identity after the real socket is bound."""
    if _desktop_token and _desktop_origin:
        return _desktop_origin, _desktop_token
    return None


DESKTOP_CORS_ORIGINS = (
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
)


def ensure_desktop_cors_origins() -> None:
    origins = [
        origin.strip()
        for origin in os.environ.get(DESKTOP_CORS_ORIGINS_ENV, "").split(",")
        if origin.strip()
    ]
    for origin in DESKTOP_CORS_ORIGINS:
        if origin not in origins:
            origins.append(origin)
    os.environ[DESKTOP_CORS_ORIGINS_ENV] = ",".join(origins)
