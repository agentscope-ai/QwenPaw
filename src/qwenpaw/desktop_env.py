# -*- coding: utf-8 -*-
"""Shared desktop sidecar environment variable names.

Keep this dependency-free: desktop_entry imports it before qwenpaw.constant
has read import-time environment variables.
"""

import os

DESKTOP_APP_ENV = "QWENPAW_DESKTOP_APP"
DESKTOP_CORS_ORIGINS_ENV = "QWENPAW_CORS_ORIGINS"
DESKTOP_PORT_ENV = "QWENPAW_DESKTOP_PORT"

DESKTOP_CORS_ORIGINS = (
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
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
