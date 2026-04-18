# -*- coding: utf-8 -*-
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root before reading any env vars
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def _get_env(key: str, default: str = "") -> str:
    """Look up an env var with automatic COPAW_ legacy fallback.

    Primary key is always used as-is.  When the primary key starts with
    ``QWENPAW_``, the corresponding ``COPAW_`` variant is transparently
    checked as a fallback so that existing deployments keep working.
    """
    if key in os.environ:
        return os.environ[key]
    if key.startswith("QWENPAW_"):
        legacy_key = "COPAW_" + key[len("QWENPAW_") :]
        if legacy_key in os.environ:
            return os.environ[legacy_key]
    return default


class EnvVarLoader:
    """Utility to load and parse environment variables with type safety
    and defaults.  Pass QWENPAW_* keys; COPAW_* legacy variants are
    checked automatically as a fallback inside _get_env.
    """

    @staticmethod
    def get_bool(env_var: str, default: bool = False) -> bool:
        """Get a boolean environment variable,
        interpreting common truthy values."""
        val = _get_env(env_var, str(default)).lower()
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
            value = float(_get_env(env_var, str(default)))
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
            value = int(_get_env(env_var, str(default)))
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
        return _get_env(env_var, default)


# WORKING_DIR priority:
# 1. ~/.copaw exists (legacy installation) → use it as-is
# 2. QWENPAW_WORKING_DIR / COPAW_WORKING_DIR env var is set → use it
# 3. Default → ~/.qwenpaw
_legacy_copaw_dir = Path("~/.copaw").expanduser()
if _legacy_copaw_dir.exists():
    WORKING_DIR = _legacy_copaw_dir.resolve()
else:
    WORKING_DIR = (
        Path(_get_env("QWENPAW_WORKING_DIR", "~/.qwenpaw"))
        .expanduser()
        .resolve()
    )
SECRET_DIR = (
    Path(
        EnvVarLoader.get_str(
            "QWENPAW_SECRET_DIR",
            f"{WORKING_DIR}.secret",
        ),
    )
    .expanduser()
    .resolve()
)

PROJECT_NAME = "QwenPaw"

# Default media directory for channels (cross-platform)
DEFAULT_MEDIA_DIR = WORKING_DIR / "media"

# Default local provider directory
DEFAULT_LOCAL_PROVIDER_DIR = WORKING_DIR / "local_models"

JOBS_FILE = EnvVarLoader.get_str("QWENPAW_JOBS_FILE", "jobs.json")

CHATS_FILE = EnvVarLoader.get_str("QWENPAW_CHATS_FILE", "chats.json")

# Builtin Q&A helper profile.  agent_id keeps "QwenPaw" prefix for existing
# workspaces and agent.json; do not rename.
BUILTIN_QA_AGENT_ID = "QwenPaw_QA_Agent_0.2"
BUILTIN_QA_AGENT_NAME = "QA Agent"
# Default skills when the builtin QA workspace is first created only.
BUILTIN_QA_AGENT_SKILL_NAMES: tuple[str, ...] = (
    "guidance",
    "QA_source_index",
)

# CoPaw-era builtin QA; may remain in config.json — disabled when the current
# ``BUILTIN_QA_AGENT_ID`` profile is first created (see ``migration``), not
# every startup, so users can re-enable this id if they want.
LEGACY_QA_AGENT_ID = "CoPaw_QA_Agent_0.1beta1"

TOKEN_USAGE_FILE = EnvVarLoader.get_str(
    "QWENPAW_TOKEN_USAGE_FILE",
    "token_usage.json",
)

CONFIG_FILE = EnvVarLoader.get_str("QWENPAW_CONFIG_FILE", "config.json")

HEARTBEAT_FILE = EnvVarLoader.get_str("QWENPAW_HEARTBEAT_FILE", "HEARTBEAT.md")
HEARTBEAT_DEFAULT_EVERY = "6h"
HEARTBEAT_DEFAULT_TARGET = "main"
HEARTBEAT_TARGET_LAST = "last"

# Debug history file for /dump_history and /load_history commands
DEBUG_HISTORY_FILE = EnvVarLoader.get_str(
    "QWENPAW_DEBUG_HISTORY_FILE",
    "debug_history.jsonl",
)
MAX_LOAD_HISTORY_COUNT = 10000

# Env key for app log level (used by CLI and app load for reload child).
LOG_LEVEL_ENV = "QWENPAW_LOG_LEVEL"

# Env to indicate running inside a container (e.g. Docker). Set to 1/true/yes.
RUNNING_IN_CONTAINER = EnvVarLoader.get_bool(
    "QWENPAW_RUNNING_IN_CONTAINER",
    False,
)

# Timeout in seconds for checking if a provider is reachable.
MODEL_PROVIDER_CHECK_TIMEOUT = EnvVarLoader.get_float(
    "QWENPAW_MODEL_PROVIDER_CHECK_TIMEOUT",
    5.0,
    min_value=0,
    allow_inf=False,
)

# Playwright: use system Chromium when set (e.g. in Docker).
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"

# When True, expose /docs, /redoc, /openapi.json
# (dev only; keep False in prod).
DOCS_ENABLED = EnvVarLoader.get_bool("QWENPAW_OPENAPI_DOCS", False)

# Memory directory
MEMORY_DIR = WORKING_DIR / "memory"

# Custom channel modules (installed via `qwenpaw channels install`); manager
# loads BaseChannel subclasses from here.
CUSTOM_CHANNELS_DIR = WORKING_DIR / "custom_channels"

# Plugin directory (installed via `qwenpaw plugin install`)
PLUGINS_DIR = WORKING_DIR / "plugins"

# Local models directory
MODELS_DIR = WORKING_DIR / "models"

MEMORY_COMPACT_KEEP_RECENT = EnvVarLoader.get_int(
    "QWENPAW_MEMORY_COMPACT_KEEP_RECENT",
    3,
    min_value=0,
)

# Memory compaction configuration
MEMORY_COMPACT_RATIO = EnvVarLoader.get_float(
    "QWENPAW_MEMORY_COMPACT_RATIO",
    0.7,
    min_value=0,
    allow_inf=False,
)

DASHSCOPE_BASE_URL = EnvVarLoader.get_str(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# CORS configuration — comma-separated list of allowed origins for dev mode.
# Example: QWENPAW_CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
# When unset, CORS middleware is not applied.
CORS_ORIGINS = EnvVarLoader.get_str("QWENPAW_CORS_ORIGINS", "").strip()

# LLM API retry configuration
LLM_MAX_RETRIES = EnvVarLoader.get_int(
    "QWENPAW_LLM_MAX_RETRIES",
    3,
    min_value=0,
)

LLM_BACKOFF_BASE = EnvVarLoader.get_float(
    "QWENPAW_LLM_BACKOFF_BASE",
    1.0,
    min_value=0.1,
)

LLM_BACKOFF_CAP = EnvVarLoader.get_float(
    "QWENPAW_LLM_BACKOFF_CAP",
    10.0,
    min_value=0.5,
)

# LLM concurrency control
# Maximum number of concurrent in-flight LLM calls; excess requests wait on
# the semaphore.  Tune to your API quota: start conservatively at 3-5 and
# increase (e.g. OpenAI Tier 1 ~500 QPM allows ~25 at 3 s/call average).
LLM_MAX_CONCURRENT = EnvVarLoader.get_int(
    "QWENPAW_LLM_MAX_CONCURRENT",
    10,
    min_value=1,
)

# Maximum queries per minute (QPM), enforced via a 60-second sliding window.
# New requests that would exceed this limit will wait before being dispatched
# to the API — proactively preventing 429s rather than reacting to them.
# 0 = unlimited (disabled).
# Examples: Anthropic Tier-1 ≈ 50 QPM; OpenAI Tier-1 ≈ 500 QPM.
LLM_MAX_QPM = EnvVarLoader.get_int(
    "QWENPAW_LLM_MAX_QPM",
    600,
    min_value=0,
)

# Default global pause duration (seconds) applied to all waiters when a 429
# is received.  Overridden by the API's Retry-After header when present.
LLM_RATE_LIMIT_PAUSE = EnvVarLoader.get_float(
    "QWENPAW_LLM_RATE_LIMIT_PAUSE",
    5.0,
    min_value=1.0,
)

# Random jitter range (seconds) added on top of the pause remaining time so
# concurrent waiters stagger their wake-up and avoid a new burst.
LLM_RATE_LIMIT_JITTER = EnvVarLoader.get_float(
    "QWENPAW_LLM_RATE_LIMIT_JITTER",
    1.0,
    min_value=0.0,
)

# Maximum time (seconds) a caller will wait for a semaphore slot before
# giving up with a RuntimeError rather than blocking indefinitely.
LLM_ACQUIRE_TIMEOUT = EnvVarLoader.get_float(
    "QWENPAW_LLM_ACQUIRE_TIMEOUT",
    300.0,
    min_value=10.0,
)

# Tool guard approval timeout (seconds).
try:
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = max(
        float(
            _get_env("QWENPAW_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS", "600"),
        ),
        1.0,
    )
except (TypeError, ValueError):
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS = 600.0

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

# Placeholder text used when media blocks are stripped from messages
# because the model does not support multimodal content.
MEDIA_UNSUPPORTED_PLACEHOLDER = (
    "[Media content removed - model does not support this media type]"
)
