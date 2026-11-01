# -*- coding: utf-8 -*-
"""Tauri sidecar environment variable helpers.

Keep this dependency-light: the Tauri entry imports it before qwenpaw.constant
has read import-time environment variables.
"""

import os

DESKTOP_APP_ENV = "QWENPAW_DESKTOP_APP"
DESKTOP_CORS_ORIGINS_ENV = "QWENPAW_CORS_ORIGINS"
RUNTIME_CONTROL_TOKEN_ENV = "QWENPAW_RUNTIME_CONTROL_TOKEN"
DESKTOP_MANAGED_PLAYWRIGHT_ENV = "QWENPAW_DESKTOP_MANAGED_PLAYWRIGHT"

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
