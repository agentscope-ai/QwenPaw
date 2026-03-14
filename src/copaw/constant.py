# -*- coding: utf-8 -*-
import os
from pathlib import Path

from ._env_compat import (
    get_app_env,
    get_app_env_bool,
    get_app_env_float,
    get_app_env_int,
)


class EnvVarLoader:
    """Utility to load and parse environment variables with type safety
    and defaults.
    """

    @staticmethod
    def get_bool(env_var: str, default: bool = False) -> bool:
        """Get a boolean environment variable,
        interpreting common truthy values."""
        val = os.environ.get(env_var, str(default)).lower()
        return val in ("true", "1", "yes")

    @staticmethod
    def get_float(
        env_var: str,
        default: float = 0.0,
        min_value: float | None = None,
        max_value: float | None = None,
        allow_inf: bool = False,
    ) -> float:
        """Get a float environment variable with optional bounds
        and infinity handling."""
        try:
            value = float(os.environ.get(env_var, str(default)))
            if min_value is not None and value < min_value:
                return min_value
            if max_value is not None and value > max_value:
                return max_value
            if not allow_inf and (
                value == float("inf") or value == float("-inf")
            ):
                return default
            return value
        except (TypeError, ValueError):
            return default

    @staticmethod
    def get_int(
        env_var: str,
        default: int = 0,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        """Get an integer environment variable with optional bounds."""
        try:
            value = int(os.environ.get(env_var, str(default)))
            if min_value is not None and value < min_value:
                return min_value
            if max_value is not None and value > max_value:
                return max_value
            return value
        except (TypeError, ValueError):
            return default

    @staticmethod
    def get_str(env_var: str, default: str = "") -> str:
        """Get a string environment variable with a default fallback."""
        return os.environ.get(env_var, default)


WORKING_DIR = (
    Path(get_app_env("WORKING_DIR", "~/.boostclaw")).expanduser().resolve()
)
SECRET_DIR = (
    Path(get_app_env("SECRET_DIR", f"{WORKING_DIR}.secret"))
    .expanduser()
    .resolve()
)

JOBS_FILE = get_app_env("JOBS_FILE", "jobs.json")
CHATS_FILE = get_app_env("CHATS_FILE", "chats.json")
TOKEN_USAGE_FILE = get_app_env("TOKEN_USAGE_FILE", "token_usage.json")
CONFIG_FILE = get_app_env("CONFIG_FILE", "config.json")
HEARTBEAT_FILE = get_app_env("HEARTBEAT_FILE", "HEARTBEAT.md")
HEARTBEAT_DEFAULT_EVERY = "6h"
HEARTBEAT_DEFAULT_TARGET = "main"
HEARTBEAT_TARGET_LAST = "last"

# Env key for app log level (used by CLI when setting level). Reading uses get_app_log_level().
LOG_LEVEL_ENV = "COPAW_LOG_LEVEL"

RUNNING_IN_CONTAINER = get_app_env_bool("RUNNING_IN_CONTAINER", False)
MODEL_PROVIDER_CHECK_TIMEOUT = get_app_env_float(
    "MODEL_PROVIDER_CHECK_TIMEOUT", 5.0, min_value=0, allow_inf=False
)

# Playwright: use system Chromium when set (e.g. in Docker).
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"

DOCS_ENABLED = get_app_env_bool("OPENAPI_DOCS", False)

# Skills directories
# Active skills directory (activated skills that agents use)
ACTIVE_SKILLS_DIR = WORKING_DIR / "active_skills"
# Customized skills directory (user-created skills)
CUSTOMIZED_SKILLS_DIR = WORKING_DIR / "customized_skills"

# Memory directory
MEMORY_DIR = WORKING_DIR / "memory"

# Custom channel modules (installed via `copaw channels install`); manager
# loads BaseChannel subclasses from here.
CUSTOM_CHANNELS_DIR = WORKING_DIR / "custom_channels"

# Local models directory
MODELS_DIR = WORKING_DIR / "models"

# Memory compaction configuration
MEMORY_COMPACT_KEEP_RECENT = get_app_env_int(
    "MEMORY_COMPACT_KEEP_RECENT", 3, min_value=0
)
MEMORY_COMPACT_RATIO = get_app_env_float(
    "MEMORY_COMPACT_RATIO", 0.7, min_value=0, allow_inf=False
)

DASHSCOPE_BASE_URL = EnvVarLoader.get_str(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# CORS configuration — comma-separated list of allowed origins for dev mode.
CORS_ORIGINS = get_app_env("CORS_ORIGINS", "").strip()

# LLM API retry configuration
LLM_MAX_RETRIES = get_app_env_int("LLM_MAX_RETRIES", 3, min_value=0)
LLM_BACKOFF_BASE = get_app_env_float("LLM_BACKOFF_BASE", 1.0, min_value=0.1)
LLM_BACKOFF_CAP = get_app_env_float("LLM_BACKOFF_CAP", 10.0, min_value=0.5)

# Tool guard approval timeout (seconds).
try:
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = max(
        float(get_app_env("TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS", "600")), 1.0
    )
except (TypeError, ValueError):
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = 600.0


def get_app_log_level() -> str:
    """Return effective log level from BOOSTCLAW_LOG_LEVEL or COPAW_LOG_LEVEL."""
    return get_app_env("LOG_LEVEL", "info")
