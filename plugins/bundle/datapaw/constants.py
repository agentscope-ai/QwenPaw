# -*- coding: utf-8 -*-
"""DataPaw plugin shared constants."""

from __future__ import annotations

import os
from pathlib import Path

from qwenpaw.constant import EnvVarLoader

PLUGIN_ID = "datapaw"
BUILTIN_DATAPAW_AGENT_ID = "datapaw"
PLUGIN_DIR = Path(__file__).resolve().parent
DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV = "DATAPAW_SPAWN_SUBAGENT_ENABLED"
DATAPAW_CM_BASE_URL_ENV = "DATAPAW_CM_BASE_URL"
DEFAULT_DATAPAW_CM_BASE_URL = "http://pre-context-management.alibaba-inc.com"


def get_datapaw_cm_base_url() -> str:
    """Return the configured CM base URL, falling back to the preprod default."""
    base = (os.environ.get(DATAPAW_CM_BASE_URL_ENV) or "").strip().rstrip("/")
    return base or DEFAULT_DATAPAW_CM_BASE_URL


def is_spawn_subagent_enabled() -> bool:
    """Return whether DataPaw should expose its spawn_subagent tool."""
    return EnvVarLoader.get_bool(DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV, True)
