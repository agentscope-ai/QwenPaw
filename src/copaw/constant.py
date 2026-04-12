# -*- coding: utf-8 -*-
from pathlib import Path

from dotenv import load_dotenv

from copaw.configs import copaw_config

# Load .env file from project root before reading any env vars
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


WORKING_DIR = copaw_config.COPAW_WORKING_DIR
SECRET_DIR = copaw_config.COPAW_SECRET_DIR or WORKING_DIR / ".secret"

# Default media directory for channels (cross-platform)
DEFAULT_MEDIA_DIR = WORKING_DIR / "media"

# Default local provider directory
DEFAULT_LOCAL_PROVIDER_DIR = WORKING_DIR / "local_models"

JOBS_FILE = copaw_config.COPAW_JOBS_FILE

CHATS_FILE = copaw_config.COPAW_CHATS_FILE

# Builtin multi-agent profile: CoPaw Q&A helper.
BUILTIN_QA_AGENT_ID = "CoPaw_QA_Agent_0.1beta1"
BUILTIN_QA_AGENT_NAME = "QA Agent"
# Default skills when the builtin QA workspace is first created only.
BUILTIN_QA_AGENT_SKILL_NAMES: tuple[str, ...] = (
    "guidance",
    "copaw_source_index",
)

TOKEN_USAGE_FILE = copaw_config.COPAW_TOKEN_USAGE_FILE

CONFIG_FILE = copaw_config.COPAW_CONFIG_FILE

HEARTBEAT_FILE = copaw_config.COPAW_HEARTBEAT_FILE
HEARTBEAT_DEFAULT_EVERY = "6h"
HEARTBEAT_DEFAULT_TARGET = "main"
HEARTBEAT_TARGET_LAST = "last"

# Debug history file for /dump_history and /load_history commands
DEBUG_HISTORY_FILE = copaw_config.COPAW_DEBUG_HISTORY_FILE
MAX_LOAD_HISTORY_COUNT = 10000

# Env key for app log level (used by CLI and app load for reload child).
LOG_LEVEL_ENV = "COPAW_LOG_LEVEL"

# Env to indicate running inside a container (e.g. Docker). Set to 1/true/yes.
RUNNING_IN_CONTAINER = copaw_config.COPAW_RUNNING_IN_CONTAINER

# Timeout in seconds for checking if a provider is reachable.
MODEL_PROVIDER_CHECK_TIMEOUT = copaw_config.COPAW_MODEL_PROVIDER_CHECK_TIMEOUT

# Playwright: use system Chromium when set (e.g. in Docker).
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"

# When True, expose /docs, /redoc, /openapi.json
# (dev only; keep False in prod).
DOCS_ENABLED = copaw_config.COPAW_OPENAPI_DOCS

# Memory directory
MEMORY_DIR = WORKING_DIR / "memory"

# Custom channel modules (installed via `copaw channels install`); manager
# loads BaseChannel subclasses from here.
CUSTOM_CHANNELS_DIR = WORKING_DIR / "custom_channels"

# Plugin directory (installed via `copaw plugin install`)
PLUGINS_DIR = WORKING_DIR / "plugins"

# Local models directory
MODELS_DIR = WORKING_DIR / "models"

MEMORY_COMPACT_KEEP_RECENT = copaw_config.COPAW_MEMORY_COMPACT_KEEP_RECENT

# Memory compaction configuration
MEMORY_COMPACT_RATIO = copaw_config.COPAW_MEMORY_COMPACT_RATIO

DASHSCOPE_BASE_URL = copaw_config.DASHSCOPE_BASE_URL

# CORS configuration — comma-separated list of allowed origins for dev mode.
# Example: COPAW_CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
# When unset, CORS middleware is not applied.
CORS_ORIGINS = copaw_config.COPAW_CORS_ORIGINS

# LLM API retry configuration
LLM_MAX_RETRIES = copaw_config.COPAW_LLM_MAX_RETRIES

LLM_BACKOFF_BASE = copaw_config.COPAW_LLM_BACKOFF_BASE

LLM_BACKOFF_CAP = copaw_config.COPAW_LLM_BACKOFF_CAP

# LLM concurrency control
# Maximum number of concurrent in-flight LLM calls; excess requests wait on
# the semaphore.  Tune to your API quota: start conservatively at 3-5 and
# increase (e.g. OpenAI Tier 1 ~500 QPM allows ~25 at 3 s/call average).
LLM_MAX_CONCURRENT = copaw_config.COPAW_LLM_MAX_CONCURRENT

# Maximum queries per minute (QPM), enforced via a 60-second sliding window.
# New requests that would exceed this limit will wait before being dispatched
# to the API — proactively preventing 429s rather than reacting to them.
# 0 = unlimited (disabled).
# Examples: Anthropic Tier-1 ≈ 50 QPM; OpenAI Tier-1 ≈ 500 QPM.
LLM_MAX_QPM = copaw_config.COPAW_LLM_MAX_QPM

# Default global pause duration (seconds) applied to all waiters when a 429
# is received.  Overridden by the API's Retry-After header when present.
LLM_RATE_LIMIT_PAUSE = copaw_config.COPAW_LLM_RATE_LIMIT_PAUSE

# Random jitter range (seconds) added on top of the pause remaining time so
# concurrent waiters stagger their wake-up and avoid a new burst.
LLM_RATE_LIMIT_JITTER = copaw_config.COPAW_LLM_RATE_LIMIT_JITTER

# Maximum time (seconds) a caller will wait for a semaphore slot before
# giving up with a RuntimeError rather than blocking indefinitely.
LLM_ACQUIRE_TIMEOUT = copaw_config.COPAW_LLM_ACQUIRE_TIMEOUT

# Tool guard approval timeout (seconds).
TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = (
    copaw_config.COPAW_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
)

# Marker prepended to every truncation notice.
# Format:
#   <<<TRUNCATED>>>
#   The output above was truncated.
#   The full content is saved to the file and contains Z lines in total.
#   This excerpt starts at line X and covers the next N bytes.
#   If the current content is not enough, call `read_file` with
#   file_path=<path> start_line=Y to read more.
#
# Split output on this marker to recover the original (untruncated) portion:
#   original = output.split(TRUNCATION_NOTICE_MARKER)[0]
TRUNCATION_NOTICE_MARKER = "<<<TRUNCATED>>>"
