# -*- coding: utf-8 -*-
"""Shared desktop sidecar environment variable names.

Keep this module dependency-free: desktop_entry imports it before qwenpaw.constant
has read import-time environment variables.
"""

DESKTOP_APP_ENV = "QWENPAW_DESKTOP_APP"
DESKTOP_CORS_ORIGINS_ENV = "QWENPAW_CORS_ORIGINS"
DESKTOP_PORT_ENV = "QWENPAW_DESKTOP_PORT"
