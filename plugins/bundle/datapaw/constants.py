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
DATAPAW_OSS_RELOAD_ENV = "DATAPAW_OSS_RELOAD"
DATAPAW_OSS_UPLOAD_ENV = "DATAPAW_OSS_UPLOAD"
DATAPAW_DATA_SOURCE_BACKEND_ENV = "DATAPAW_DATA_SOURCE_BACKEND"
DATAPAW_HOLOGRES_JDBC_URL_ENV = "DATAPAW_HOLOGRES_JDBC_URL"
DATAPAW_HOLOGRES_HOST_ENV = "DATAPAW_HOLOGRES_HOST"
DATAPAW_HOLOGRES_PORT_ENV = "DATAPAW_HOLOGRES_PORT"
DATAPAW_HOLOGRES_DB_ENV = "DATAPAW_HOLOGRES_DB"
DATAPAW_HOLOGRES_USER_ENV = "DATAPAW_HOLOGRES_USER"
DATAPAW_HOLOGRES_PASSWORD_ENV = "DATAPAW_HOLOGRES_PASSWORD"
DEFAULT_DATAPAW_CM_BASE_URL = "http://pre-context-management.alibaba-inc.com"
DEFAULT_DATAPAW_HOLOGRES_HOST = (
    "hgpostcn-cn-0w74oi088001-cn-hangzhou.hologres.aliyuncs.com"
)
DEFAULT_DATAPAW_HOLOGRES_PORT = 80
DEFAULT_DATAPAW_HOLOGRES_DB = "tongyi_datascope"


def get_datapaw_cm_base_url() -> str:
    """Return the configured CM base URL, falling back to the preprod default."""
    base = (os.environ.get(DATAPAW_CM_BASE_URL_ENV) or "").strip().rstrip("/")
    return base or DEFAULT_DATAPAW_CM_BASE_URL


def is_spawn_subagent_enabled() -> bool:
    """Return whether DataPaw should expose its spawn_subagent tool."""
    return EnvVarLoader.get_bool(DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV, True)
