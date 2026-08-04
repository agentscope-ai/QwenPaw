# -*- coding: utf-8 -*-

from __future__ import annotations

import os


UI_HOST = os.getenv("QWENPAW_UI_HOST", "127.0.0.1")
UI_PORT = os.getenv("QWENPAW_UI_PORT", "5173")
BASE_URL = os.getenv("CREATOR_E2E_BASE_URL", f"http://{UI_HOST}:{UI_PORT}")
API_PREFIX = "/api/qwenpaw-creator"
STRICT = os.getenv("CREATOR_E2E_STRICT", "0") == "1"
