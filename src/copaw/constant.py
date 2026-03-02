# -*- coding: utf-8 -*-
import os
from pathlib import Path

WORKING_DIR = (
    Path(os.environ.get("COPAW_WORKING_DIR", "~/.copaw"))
    .expanduser()
    .resolve()
)

JOBS_FILE = os.environ.get("COPAW_JOBS_FILE", "jobs.json")

CHATS_FILE = os.environ.get("COPAW_CHATS_FILE", "chats.json")

CONFIG_FILE = os.environ.get("COPAW_CONFIG_FILE", "config.json")

HEARTBEAT_FILE = os.environ.get("COPAW_HEARTBEAT_FILE", "HEARTBEAT.md")
HEARTBEAT_DEFAULT_EVERY = "30m"
HEARTBEAT_DEFAULT_TARGET = "main"
HEARTBEAT_TARGET_LAST = "last"

# Env key for app log level (used by CLI and app load for reload child).
LOG_LEVEL_ENV = "COPAW_LOG_LEVEL"

# Env to indicate running inside a container (e.g. Docker). Set to 1/true/yes.
RUNNING_IN_CONTAINER = os.environ.get("COPAW_RUNNING_IN_CONTAINER", "false")

# Playwright: use system Chromium when set (e.g. in Docker).
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"

# When True, expose /docs, /redoc, /openapi.json
# (dev only; keep False in prod).
DOCS_ENABLED = os.environ.get("COPAW_OPENAPI_DOCS", "false").lower() in (
    "true",
    "1",
    "yes",
)

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
MEMORY_COMPACT_KEEP_RECENT = int(
    os.environ.get("COPAW_MEMORY_COMPACT_KEEP_RECENT", "3"),
)

MEMORY_COMPACT_RATIO = float(
    os.environ.get("COPAW_MEMORY_COMPACT_RATIO", "0.7"),
)

DASHSCOPE_BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# CORS configuration — comma-separated list of allowed origins for dev mode.
# Example: COPAW_CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
# When unset, CORS middleware is not applied.
CORS_ORIGINS = os.environ.get("COPAW_CORS_ORIGINS", "").strip()
