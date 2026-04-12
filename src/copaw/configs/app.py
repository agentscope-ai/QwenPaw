# -*- coding: utf-8 -*-
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    COPAW_WORKING_DIR: Path = Field(
        description="Working directory for CoPaw data and configuration files",
        default=Path("~/.copaw").expanduser().resolve(),
    )

    COPAW_RUNNING_IN_CONTAINER: bool = Field(
        description=(
            "Set to true if running inside Docker "
            "(Env: COPAW_RUNNING_IN_CONTAINER=1/true/yes)"
        ),
        default=False,
    )

    COPAW_OPENAPI_DOCS: bool = Field(
        description=(
            "When true, expose /docs, /redoc, /openapi.json (dev only)"
        ),
        default=False,
    )

    COPAW_MODEL_PROVIDER_CHECK_TIMEOUT: float = Field(
        description=(
            "Timeout in seconds for checking if a provider is reachable"
        ),
        default=5.0,
        ge=0,
    )

    COPAW_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS: float = Field(
        description="Tool guard approval timeout in seconds",
        default=600.0,
        ge=1.0,
    )

    COPAW_JOBS_FILE: str = Field(
        description="Filename for jobs data storage",
        default="jobs.json",
    )

    COPAW_CHATS_FILE: str = Field(
        description="Filename for chats data storage",
        default="chats.json",
    )

    COPAW_TOKEN_USAGE_FILE: str = Field(
        description="Filename for token usage tracking",
        default="token_usage.json",
    )

    COPAW_CONFIG_FILE: str = Field(
        description="Filename for main configuration file",
        default="config.json",
    )

    COPAW_HEARTBEAT_FILE: str = Field(
        description="Filename for heartbeat status file",
        default="HEARTBEAT.md",
    )

    COPAW_DEBUG_HISTORY_FILE: str = Field(
        description=(
            "Debug history file for /dump_history and /load_history commands"
        ),
        default="debug_history.jsonl",
    )

    COPAW_SECRET_DIR: Path | None = Field(
        description=(
            "Secret directory for sensitive data. "
            "Defaults to WORKING_DIR.parent / '.copaw.secret'"
        ),
        default=None,
    )
