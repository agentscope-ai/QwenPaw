# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Centralized model/tool configuration for Creator generation backends.

Environment variables remain the standalone/local fallback, while QwenPaw
loads request-scoped values from the current agent's tool configuration.
"""

from contextvars import ContextVar, Token
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from services.runtime_files.locking import CrossProcessFileLock

try:
    from qwenpaw.security.secret_store import (
        decrypt as _secret_decrypt,
        is_encrypted as _secret_is_encrypted,
    )

    _SECRET_STORE_AVAILABLE = True
except ImportError:
    _SECRET_STORE_AVAILABLE = False
    _secret_decrypt = None
    _secret_is_encrypted = None


CREATOR_TEXT_CONFIG_TOOL = "creator_text_model"
CREATOR_IMAGE_CONFIG_TOOL = "creator_image_model"
CREATOR_VIDEO_CONFIG_TOOL = "creator_video_model"
CREATOR_VLM_CONFIG_TOOL = "creator_vlm_model"
CREATOR_GROUNDING_CONFIG_TOOL = "creator_web_grounding"
CREATOR_ASR_CONFIG_TOOL = "creator_asr_model"
CREATOR_OSS_CONFIG_TOOL = "creator_media_oss"
EXECUTION_AUTHORIZATION_REQUIRED = "required"
EXECUTION_AUTHORIZATION_ALLOW_ALL = "allow_all"
CREATION_CHECKPOINT_REQUIRED = "required"
CREATION_CHECKPOINT_SKIP = "skip"
CREATOR_CONFIG_TOOLS = (
    CREATOR_TEXT_CONFIG_TOOL,
    CREATOR_IMAGE_CONFIG_TOOL,
    CREATOR_VIDEO_CONFIG_TOOL,
    CREATOR_VLM_CONFIG_TOOL,
    CREATOR_GROUNDING_CONFIG_TOOL,
    CREATOR_ASR_CONFIG_TOOL,
    CREATOR_OSS_CONFIG_TOOL,
)

_REQUEST_TOOL_CONFIGS: ContextVar[dict[str, dict[str, Any]]] = ContextVar(
    "qwenpaw_creator_tool_configs",
    default={},
)

# Per-request cache for the active image provider. The provider is fully
# derived from request-scoped config, so it is constant within a single
# request; we construct it once instead of on every _image_provider() call.
# Cleared whenever request tool configs are (re)bound. The active backend is
# process-level (IMAGE_MODEL env, constant), so a single slot suffices.
_IMAGE_PROVIDER_CACHE: ContextVar[Any] = ContextVar(
    "qwenpaw_image_provider_cache",
    default=None,
)


def set_request_tool_configs(
    configs: Mapping[str, Mapping[str, Any]],
) -> Token[dict[str, dict[str, Any]]]:
    normalized = {
        name: dict(value)
        for name, value in configs.items()
        if isinstance(value, Mapping)
    }
    token = _REQUEST_TOOL_CONFIGS.set(normalized)
    # Drop any cached provider so a config change within the same context
    # forces a fresh from_config() on next access.
    _IMAGE_PROVIDER_CACHE.set(None)
    return token


def reset_request_tool_configs(
    token: Token[dict[str, dict[str, Any]]],
) -> None:
    _REQUEST_TOOL_CONFIGS.reset(token)
    _IMAGE_PROVIDER_CACHE.set(None)


def get_request_tool_config(tool_name: str) -> dict[str, Any]:
    return dict(_REQUEST_TOOL_CONFIGS.get({}).get(tool_name) or {})


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return ""


def _configured_value(
    tool_name: str,
    fields: str | tuple[str, ...],
    env_name: str,
    default: str = "",
) -> str:
    field_names = (fields,) if isinstance(fields, str) else fields
    tool_config = get_request_tool_config(tool_name)
    for field in field_names:
        value = tool_config.get(field)
        if value not in (None, ""):
            return str(value)
    section = _map_tool_to_section(tool_name)
    if section:
        user_cfg = _get_user_config().get(section, {})
        if user_cfg.get("enabled", False):
            for field in field_names:
                value = user_cfg.get(_map_user_field(field))
                if value not in (None, ""):
                    return str(value)
    return os.environ.get(env_name, default)


def _explicit_configured_value(
    tool_name: str,
    fields: str | tuple[str, ...],
    env_names: tuple[str, ...],
) -> str:
    """Return only an explicitly supplied value, without a baked-in default."""

    field_names = (fields,) if isinstance(fields, str) else fields
    tool_config = get_request_tool_config(tool_name)
    for field in field_names:
        value = tool_config.get(field)
        if value not in (None, ""):
            return str(value)
    section = _map_tool_to_section(tool_name)
    if section:
        user_cfg = _get_user_config().get(section, {})
        if user_cfg.get("enabled", False):
            for field in field_names:
                value = user_cfg.get(_map_user_field(field))
                if value not in (None, ""):
                    return str(value)
    return _first_env(*env_names)


def _configured_int(
    tool_name: str,
    field: str,
    env_name: str,
    default: int,
) -> int:
    raw = _configured_value(tool_name, field, env_name, str(default))
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _configured_positive_float(
    tool_name: str,
    field: str,
    env_name: str,
    default: float,
) -> float:
    raw = _configured_value(tool_name, field, env_name, str(default))
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default


def _positive_int_env(name: str, default: int) -> int:
    value = os.environ.get(name, str(default))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


# ── User model config (from model_config.json) ────────────────────────────────


def _get_model_config_path() -> Path:
    configured = os.environ.get("CREATOR_MODEL_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    data_root = os.environ.get("CREATOR_DATA_ROOT", "").strip()
    if data_root:
        return (
            Path(data_root).expanduser().resolve(strict=False)
            / "config"
            / "model_config.json"
        )
    # Read-only sentinel: provider configuration has no source-tree fallback.
    return Path("/__qwenpaw_creator_unconfigured__/model_config.json")


_USER_CONFIG_CACHE: dict | None = None
_USER_CONFIG_CACHE_PATH: Path | None = None
_USER_CONFIG_CACHE_FINGERPRINT: tuple[int, int, int] | None = None


def _user_config_fingerprint(
    path: Path,
) -> tuple[int, int, int] | None:
    try:
        metadata = path.stat()
    except OSError:
        return None
    return metadata.st_ino, metadata.st_mtime_ns, metadata.st_size


def _get_user_config() -> dict:
    global _USER_CONFIG_CACHE, _USER_CONFIG_CACHE_FINGERPRINT, _USER_CONFIG_CACHE_PATH
    path = _get_model_config_path()
    fingerprint = _user_config_fingerprint(path)
    if (
        _USER_CONFIG_CACHE is not None
        and _USER_CONFIG_CACHE_PATH == path
        and _USER_CONFIG_CACHE_FINGERPRINT == fingerprint
    ):
        return _USER_CONFIG_CACHE
    if fingerprint is None:
        return {}
    try:
        with CrossProcessFileLock(path.parent / ".model-config.lock"):
            fingerprint = _user_config_fingerprint(path)
            if fingerprint is None:
                return {}
            if (
                _USER_CONFIG_CACHE is not None
                and _USER_CONFIG_CACHE_PATH == path
                and _USER_CONFIG_CACHE_FINGERPRINT == fingerprint
            ):
                return _USER_CONFIG_CACHE
            value = json.loads(path.read_text(encoding="utf-8"))
            _decrypt_config_secrets(value)
            _USER_CONFIG_CACHE = value
            _USER_CONFIG_CACHE_PATH = path
            _USER_CONFIG_CACHE_FINGERPRINT = fingerprint
            return _USER_CONFIG_CACHE
    except Exception:
        pass
    return {}


def _clear_user_config_cache():
    global _USER_CONFIG_CACHE, _USER_CONFIG_CACHE_FINGERPRINT, _USER_CONFIG_CACHE_PATH
    _USER_CONFIG_CACHE = None
    _USER_CONFIG_CACHE_PATH = None
    _USER_CONFIG_CACHE_FINGERPRINT = None


_SECRET_FIELDS = ("api_key", "access_key_secret", "policy_api_key")


def _decrypt_config_secrets(data: dict) -> dict:
    """Decrypt secret fields in config data read from model_config.json.

    Handles both encrypted (ENC:...) and legacy plaintext values transparently.
    """
    if not _SECRET_STORE_AVAILABLE:
        return data
    for section_data in data.values():
        if not isinstance(section_data, dict):
            continue
        for field in _SECRET_FIELDS:
            value = section_data.get(field)
            if (
                value
                and isinstance(value, str)
                and _secret_is_encrypted(value)
            ):
                section_data[field] = _secret_decrypt(value)
    return data


def get_execution_authorization_mode() -> str:
    """Return the persisted global admission mode for costly executions."""

    section = _get_user_config().get("execution_authorization")
    value = section.get("mode") if isinstance(section, dict) else None
    if value == EXECUTION_AUTHORIZATION_ALLOW_ALL:
        return EXECUTION_AUTHORIZATION_ALLOW_ALL
    return EXECUTION_AUTHORIZATION_REQUIRED


def get_creation_checkpoint_mode() -> str:
    """Return the persisted mode for the creation pit-stop checkpoints."""

    section = _get_user_config().get("creation_checkpoints")
    value = section.get("mode") if isinstance(section, dict) else None
    if value == CREATION_CHECKPOINT_SKIP:
        return CREATION_CHECKPOINT_SKIP
    return CREATION_CHECKPOINT_REQUIRED


def _map_tool_to_section(tool_name: str) -> str:
    return {
        CREATOR_TEXT_CONFIG_TOOL: "llm",
        CREATOR_VLM_CONFIG_TOOL: "vlm",
        CREATOR_GROUNDING_CONFIG_TOOL: "grounding",
        CREATOR_ASR_CONFIG_TOOL: "asr",
        CREATOR_IMAGE_CONFIG_TOOL: "image",
        CREATOR_VIDEO_CONFIG_TOOL: "video",
    }.get(tool_name, "")


def _map_user_field(key: str) -> str:
    return {"model": "model_name", "endpoint": "base_url"}.get(key, key)


def _oss_persisted(field: str) -> str:
    """Read a field from the persisted ``oss`` section of model_config.json.

    The OSS tool config has no ``enabled`` gate (unlike the model sections), so
    it cannot ride on ``_configured_value``; this reads the merged public+secret
    dict directly.  Background workers share this disk-backed cache, so they
    pick up UI-saved OSS credentials without a request scope.
    """

    section = _get_user_config().get("oss")
    if isinstance(section, dict):
        value = section.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


# ── Text Model (DashScope / AgentScope 2.0) ──────────────────────────────────
TEXT_BASE_URL = os.environ.get(
    "TEXT_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
TEXT_API_KEY = os.environ.get("TEXT_API_KEY", "")
TEXT_MODEL_NAME = os.environ.get("TEXT_MODEL_NAME", "qwen3.7-plus")
TEXT_CONCURRENCY = _positive_int_env("TEXT_CONCURRENCY", 20)


# ── VLM Understanding Model (DashScope OpenAI-compatible multimodal) ─────────
VLM_BASE_URL = os.environ.get(
    "VLM_BASE_URL",
    os.environ.get(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
)
VLM_API_KEY = os.environ.get("VLM_API_KEY", "")
VLM_MODEL_NAME = os.environ.get("VLM_MODEL_NAME", "qwen3.7-plus")
VLM_CONCURRENCY = _positive_int_env("VLM_CONCURRENCY", 3)
VLM_TIMEOUT_SECONDS = _positive_int_env("VLM_TIMEOUT_SECONDS", 180)
VLM_MAX_INLINE_BYTES = _positive_int_env(
    "VLM_MAX_INLINE_BYTES",
    20 * 1024 * 1024,
)

# ── Web grounding ────────────────────────────────────────────────────────────
# These are Creator product policy, not deployment configuration. Keep them
# fixed until there is a demonstrated need to expose a supported tuning
# surface through model_config.json / the Portal.
WEB_GROUNDING_TIMEOUT_SECONDS = 60
WEB_GROUNDING_MAX_SOURCES = 6
WEB_GROUNDING_MAX_ENTITIES = 3
WEB_GROUNDING_ENTITY_TIMEOUT_SECONDS = 20
WEB_GROUNDING_VISUAL_SEARCH_TIMEOUT_SECONDS = 120
WEB_GROUNDING_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
WEB_GROUNDING_VERIFICATION_TIMEOUT_SECONDS = 120
WEB_GROUNDING_VERIFICATION_MAX_ATTEMPTS = 3
WEB_GROUNDING_VERIFICATION_TOTAL_BUDGET_SECONDS = 300
WEB_GROUNDING_RETRY_BASE_SECONDS = 1
WEB_GROUNDING_RETRY_MAX_SECONDS = 8

# ── ASR Model (OpenAI Whisper / DashScope Fun-ASR) ───────────────────────────
ASR_BASE_URL = os.environ.get(
    "ASR_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1",
)
ASR_API_KEY = os.environ.get("ASR_API_KEY", "")
ASR_MODEL_NAME = os.environ.get("ASR_MODEL_NAME", "fun-asr")
ASR_PROVIDER = os.environ.get("ASR_PROVIDER", "fun-asr")
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "")
ASR_TIMEOUT_SECONDS = _positive_int_env("ASR_TIMEOUT_SECONDS", 1800)


# ── Image Model ──────────────────────────────────────────────────────────────
# Two independent providers, each with its own variable prefix (DASHSCOPE_IMAGE_*
# / OPENAI_IMAGE_*). ``IMAGE_MODEL`` picks the active provider: ``DASHSCOPE``
# (qwen-image-2.0-pro, multimodal-generation protocol) or ``OPENAI`` (gpt-image-2
# via routify, OpenAI Images API). The switch is read and the provider selected
# in models/image/__init__.py; each provider reads its own env vars in
# models/image/<provider>.py::from_config(). This module only owns the request
# cache and thin delegate accessors for external callers.


# ── Video Model (DashScope Bailian Wan / Volcengine Seedance) ────────────────
VIDEO_BASE_URL = os.environ.get(
    "VIDEO_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1",
)
VIDEO_API_KEY = os.environ.get("VIDEO_API_KEY", "")
VIDEO_MODEL_NAME = os.environ.get("VIDEO_MODEL_NAME", "wan2.7-r2v")
VIDEO_CONCURRENCY = _positive_int_env("VIDEO_CONCURRENCY", 1)


# ── Dynamic request-scoped getters ───────────────────────────────────────────
def get_text_api_key() -> str:
    return _configured_value(
        CREATOR_TEXT_CONFIG_TOOL,
        "api_key",
        "TEXT_API_KEY",
        TEXT_API_KEY,
    )


def get_text_base_url() -> str:
    return _configured_value(
        CREATOR_TEXT_CONFIG_TOOL,
        ("base_url", "endpoint"),
        "TEXT_BASE_URL",
        TEXT_BASE_URL,
    )


def get_text_model_name() -> str:
    return _configured_value(
        CREATOR_TEXT_CONFIG_TOOL,
        "model",
        "TEXT_MODEL_NAME",
        TEXT_MODEL_NAME,
    )


def get_vlm_api_key() -> str:
    return (
        _explicit_configured_value(
            CREATOR_VLM_CONFIG_TOOL,
            "api_key",
            ("VLM_API_KEY", "DASHSCOPE_API_KEY"),
        )
        or get_text_api_key()
    )


def get_vlm_base_url() -> str:
    return (
        _explicit_configured_value(
            CREATOR_VLM_CONFIG_TOOL,
            ("base_url", "endpoint"),
            ("VLM_BASE_URL", "DASHSCOPE_BASE_URL"),
        )
        or get_text_base_url()
    )


def get_vlm_model_name() -> str:
    return (
        _explicit_configured_value(
            CREATOR_VLM_CONFIG_TOOL,
            "model",
            ("VLM_MODEL_NAME",),
        )
        or get_text_model_name()
    )


def get_vlm_chat_url() -> str:
    return f"{get_vlm_base_url().rstrip('/')}/chat/completions"


def get_vlm_concurrency() -> int:
    return _configured_int(
        CREATOR_VLM_CONFIG_TOOL,
        "concurrency",
        "VLM_CONCURRENCY",
        VLM_CONCURRENCY,
    )


def get_vlm_timeout_seconds() -> int:
    return _configured_int(
        CREATOR_VLM_CONFIG_TOOL,
        "timeout_seconds",
        "VLM_TIMEOUT_SECONDS",
        VLM_TIMEOUT_SECONDS,
    )


def get_vlm_max_inline_bytes() -> int:
    return _configured_int(
        CREATOR_VLM_CONFIG_TOOL,
        "max_inline_bytes",
        "VLM_MAX_INLINE_BYTES",
        VLM_MAX_INLINE_BYTES,
    )


def _grounding_value(
    fields: str | tuple[str, ...],
    env_name: str,
    default: str = "",
) -> str:
    """Read grounding config while preserving an explicit disabled section."""

    field_names = (fields,) if isinstance(fields, str) else fields
    tool_config = get_request_tool_config(CREATOR_GROUNDING_CONFIG_TOOL)
    for field in field_names:
        value = tool_config.get(field)
        if value not in (None, ""):
            return str(value)
    section = _get_user_config().get("grounding")
    if isinstance(section, dict):
        for field in field_names:
            value = section.get(_map_user_field(field))
            if value not in (None, ""):
                return str(value)
    return os.environ.get(env_name, default)


def _grounding_explicit(
    fields: str | tuple[str, ...],
    env_names: tuple[str, ...],
) -> str:
    for env_name in env_names:
        value = _grounding_value(fields, env_name)
        if value:
            return value
    return ""


def get_web_grounding_enabled() -> bool:
    raw = _grounding_value(
        "enabled",
        "WEB_GROUNDING_ENABLED",
        "1",
    )
    return str(raw).strip().casefold() not in {"0", "false", "no", "off"}


def get_web_grounding_timeout_seconds() -> int:
    return WEB_GROUNDING_TIMEOUT_SECONDS


def get_web_grounding_max_sources() -> int:
    return WEB_GROUNDING_MAX_SOURCES


def get_web_grounding_max_entities() -> int:
    return WEB_GROUNDING_MAX_ENTITIES


def get_web_grounding_entity_timeout_seconds() -> int:
    return WEB_GROUNDING_ENTITY_TIMEOUT_SECONDS


def get_web_grounding_visual_search_timeout_seconds() -> int:
    return WEB_GROUNDING_VISUAL_SEARCH_TIMEOUT_SECONDS


def get_web_grounding_image_download_timeout_seconds() -> int:
    return WEB_GROUNDING_IMAGE_DOWNLOAD_TIMEOUT_SECONDS


def get_web_grounding_verification_timeout_seconds() -> int:
    return WEB_GROUNDING_VERIFICATION_TIMEOUT_SECONDS


def get_web_grounding_verification_max_attempts() -> int:
    return WEB_GROUNDING_VERIFICATION_MAX_ATTEMPTS


def get_web_grounding_verification_total_budget_seconds() -> int:
    return WEB_GROUNDING_VERIFICATION_TOTAL_BUDGET_SECONDS


def get_web_grounding_retry_base_seconds() -> int:
    return WEB_GROUNDING_RETRY_BASE_SECONDS


def get_web_grounding_retry_max_seconds() -> int:
    return WEB_GROUNDING_RETRY_MAX_SECONDS


def get_web_grounding_tavily_api_key() -> str:
    return _grounding_explicit(
        "tavily_api_key",
        ("TAVILY_API_KEY", "WEB_GROUNDING_TAVILY_API_KEY"),
    )


def _grounding_bool(
    field: str,
    env_name: str,
    *,
    default: bool,
) -> bool:
    raw = _grounding_value(field, env_name, "1" if default else "0")
    return str(raw).strip().casefold() not in {"0", "false", "no", "off"}


def get_web_grounding_validation_source() -> str:
    source = (
        _grounding_value(
            "validation_source",
            "WEB_GROUNDING_VALIDATION_SOURCE",
        )
        .strip()
        .casefold()
    )
    if source in {"llm", "vlm", "custom"}:
        return source
    env_name = (
        "WEB_GROUNDING_REUSE_LLM"
        if "WEB_GROUNDING_REUSE_LLM" in os.environ
        else "WEB_GROUNDING_REUSE_VLM"
    )
    return (
        "llm"
        if _grounding_bool("reuse_llm", env_name, default=True)
        else "custom"
    )


def get_web_grounding_reuse_llm() -> bool:
    return get_web_grounding_validation_source() == "llm"


def get_web_grounding_model_api_key() -> str:
    source = get_web_grounding_validation_source()
    if source == "llm":
        return get_text_api_key()
    if source == "vlm":
        return get_vlm_api_key()
    return _grounding_explicit(
        "api_key",
        ("WEB_GROUNDING_LLM_API_KEY", "WEB_GROUNDING_VLM_API_KEY"),
    )


def get_web_grounding_model_base_url() -> str:
    source = get_web_grounding_validation_source()
    if source == "llm":
        return get_text_base_url()
    if source == "vlm":
        return get_vlm_base_url()
    return _grounding_explicit(
        ("base_url", "endpoint"),
        ("WEB_GROUNDING_LLM_BASE_URL", "WEB_GROUNDING_VLM_BASE_URL"),
    )


def get_web_grounding_model_name() -> str:
    source = get_web_grounding_validation_source()
    if source == "llm":
        return get_text_model_name()
    if source == "vlm":
        return get_vlm_model_name()
    return _grounding_explicit(
        "model",
        ("WEB_GROUNDING_LLM_MODEL_NAME", "WEB_GROUNDING_VLM_MODEL_NAME"),
    )


def get_web_grounding_native_search_enabled() -> bool:
    return _grounding_bool(
        "native_search_enabled",
        "WEB_GROUNDING_NATIVE_SEARCH_ENABLED",
        default=True,
    )


def get_web_grounding_search_provider() -> str:
    provider = (
        _grounding_value(
            "search_provider",
            "WEB_GROUNDING_SEARCH_PROVIDER",
            "dashscope_qwen",
        )
        .strip()
        .casefold()
    )
    return provider or "dashscope_qwen"


def get_web_grounding_search_reuse_llm() -> bool:
    raw = _grounding_value(
        "search_reuse_llm",
        "WEB_GROUNDING_SEARCH_REUSE_LLM",
    )
    if raw:
        return str(raw).strip().casefold() not in {"0", "false", "no", "off"}
    # Legacy grounding used one model for both retrieval and verification.
    env_name = (
        "WEB_GROUNDING_REUSE_LLM"
        if "WEB_GROUNDING_REUSE_LLM" in os.environ
        else "WEB_GROUNDING_REUSE_VLM"
    )
    return _grounding_bool("reuse_llm", env_name, default=True)


def get_web_grounding_search_api_key() -> str:
    if get_web_grounding_search_reuse_llm():
        return get_text_api_key()
    return _grounding_explicit(
        "search_api_key",
        ("WEB_GROUNDING_SEARCH_API_KEY",),
    ) or _grounding_explicit(
        "api_key",
        ("WEB_GROUNDING_LLM_API_KEY", "WEB_GROUNDING_VLM_API_KEY"),
    )


def get_web_grounding_search_base_url() -> str:
    if get_web_grounding_search_reuse_llm():
        return get_text_base_url()
    return _grounding_explicit(
        "search_base_url",
        ("WEB_GROUNDING_SEARCH_BASE_URL",),
    ) or _grounding_explicit(
        ("base_url", "endpoint"),
        ("WEB_GROUNDING_LLM_BASE_URL", "WEB_GROUNDING_VLM_BASE_URL"),
    )


def get_web_grounding_search_model_name() -> str:
    if get_web_grounding_search_reuse_llm():
        return get_text_model_name()
    return _grounding_explicit(
        ("search_model", "search_model_name"),
        ("WEB_GROUNDING_SEARCH_MODEL_NAME",),
    ) or _grounding_explicit(
        "model",
        ("WEB_GROUNDING_LLM_MODEL_NAME", "WEB_GROUNDING_VLM_MODEL_NAME"),
    )


def get_web_grounding_search_protocol() -> str:
    if get_web_grounding_search_reuse_llm():
        text_tool_config = get_request_tool_config(CREATOR_TEXT_CONFIG_TOOL)
        if text_tool_config:
            return str(text_tool_config.get("protocol") or "").strip()
        llm_section = _get_user_config().get("llm")
        if isinstance(llm_section, dict) and llm_section.get("protocol"):
            return str(llm_section["protocol"]).strip()
        if os.environ.get("TEXT_PROTOCOL"):
            return os.environ["TEXT_PROTOCOL"].strip()
    return _grounding_value(
        "search_protocol",
        "WEB_GROUNDING_SEARCH_PROTOCOL",
    ).strip()


def get_asr_api_key() -> str:
    configured = _explicit_configured_value(
        CREATOR_ASR_CONFIG_TOOL,
        "api_key",
        ("ASR_API_KEY",),
    )
    if configured:
        return configured
    section = _get_user_config().get("asr", {})
    reuse = not isinstance(section, dict) or section.get("reuse_llm_key", True)
    return get_text_api_key() if reuse else ""


def get_asr_base_url() -> str:
    return _configured_value(
        CREATOR_ASR_CONFIG_TOOL,
        ("base_url", "endpoint"),
        "ASR_BASE_URL",
        ASR_BASE_URL,
    )


def get_asr_model_name() -> str:
    return _configured_value(
        CREATOR_ASR_CONFIG_TOOL,
        "model",
        "ASR_MODEL_NAME",
        ASR_MODEL_NAME,
    )


def get_asr_provider() -> str:
    value = _configured_value(
        CREATOR_ASR_CONFIG_TOOL,
        "provider",
        "ASR_PROVIDER",
        ASR_PROVIDER,
    ).casefold()
    return "whisper" if value == "whisper" else "fun-asr"


def get_asr_language() -> str:
    return _configured_value(
        CREATOR_ASR_CONFIG_TOOL,
        "language",
        "ASR_LANGUAGE",
        ASR_LANGUAGE,
    )


def get_asr_timeout_seconds() -> int:
    return _configured_int(
        CREATOR_ASR_CONFIG_TOOL,
        "timeout_seconds",
        "ASR_TIMEOUT_SECONDS",
        ASR_TIMEOUT_SECONDS,
    )


def is_asr_enabled() -> bool:
    if get_request_tool_config(CREATOR_ASR_CONFIG_TOOL):
        return True
    section = _get_user_config().get("asr")
    if isinstance(section, dict) and section.get("enabled") is True:
        return True
    return os.environ.get("ASR_ENABLED", "").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _image_provider():
    """Return the active image provider instance (lazy import avoids cycles).

    Memoized per request: config is constant within a request, so the same
    instance is reused across _image_provider() calls in that scope.
    """
    provider = _IMAGE_PROVIDER_CACHE.get()
    if provider is not None:
        return provider
    from models.image import get_image_model

    provider = get_image_model()
    _IMAGE_PROVIDER_CACHE.set(provider)
    return provider


def get_image_api_key() -> str:
    return _image_provider().api_key


def get_image_model_name() -> str:
    return _image_provider().model_name


def get_image_concurrency() -> int:
    """Return the image generation concurrency limit for the active provider."""
    return _image_provider().concurrency


def get_video_api_key() -> str:
    return _configured_value(
        CREATOR_VIDEO_CONFIG_TOOL,
        "api_key",
        "VIDEO_API_KEY",
        VIDEO_API_KEY,
    )


def get_video_base_url() -> str:
    return _configured_value(
        CREATOR_VIDEO_CONFIG_TOOL,
        ("base_url", "endpoint"),
        "VIDEO_BASE_URL",
        VIDEO_BASE_URL,
    )


def get_video_model_name() -> str:
    return _configured_value(
        CREATOR_VIDEO_CONFIG_TOOL,
        "model",
        "VIDEO_MODEL_NAME",
        VIDEO_MODEL_NAME,
    )


def get_video_submit_timeout() -> int:
    return _configured_int(
        CREATOR_VIDEO_CONFIG_TOOL,
        "submit_timeout",
        "VIDEO_SUBMIT_TIMEOUT",
        180,
    )


def get_video_status_timeout() -> int:
    return _configured_int(
        CREATOR_VIDEO_CONFIG_TOOL,
        "status_timeout",
        "VIDEO_STATUS_TIMEOUT",
        30,
    )


def get_video_poll_interval_seconds() -> float:
    """Minimum wall-clock interval between provider status requests."""

    return _configured_positive_float(
        CREATOR_VIDEO_CONFIG_TOOL,
        "poll_interval_seconds",
        "VIDEO_POLL_INTERVAL_SECONDS",
        5.0,
    )


def get_oss_policy_api_key() -> str:
    tool_config = get_request_tool_config(CREATOR_OSS_CONFIG_TOOL)
    for field in ("policy_api_key", "api_key"):
        value = tool_config.get(field)
        if value not in (None, ""):
            return str(value)
    persisted = _oss_persisted("policy_api_key")
    if persisted:
        return persisted
    value = os.environ.get("OSS_POLICY_API_KEY", "")
    return value or os.environ.get("OSS_API_KEY", "")


def get_oss_access_key_id() -> str:
    tool_config = get_request_tool_config(CREATOR_OSS_CONFIG_TOOL)
    value = tool_config.get("access_key_id")
    if value not in (None, ""):
        return str(value)
    persisted = _oss_persisted("access_key_id")
    if persisted:
        return persisted
    return _first_env(
        "OSS_ACCESS_KEY_ID",
        "ALIYUN_ACCESS_KEY_ID",
        "ALIBABA_CLOUD_ACCESS_KEY_ID",
    )


def get_oss_access_key_secret() -> str:
    tool_config = get_request_tool_config(CREATOR_OSS_CONFIG_TOOL)
    value = tool_config.get("access_key_secret")
    if value not in (None, ""):
        return str(value)
    persisted = _oss_persisted("access_key_secret")
    if persisted:
        return persisted
    return _first_env(
        "OSS_ACCESS_KEY_SECRET",
        "ALIYUN_ACCESS_KEY_SECRET",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    )


def get_oss_endpoint() -> str:
    tool_config = get_request_tool_config(CREATOR_OSS_CONFIG_TOOL)
    value = tool_config.get("endpoint")
    if value not in (None, ""):
        return str(value)
    persisted = _oss_persisted("endpoint")
    if persisted:
        return persisted
    return _first_env("OSS_ENDPOINT", "ALIYUN_OSS_ENDPOINT")


def get_oss_bucket(default: str) -> str:
    tool_config = get_request_tool_config(CREATOR_OSS_CONFIG_TOOL)
    value = tool_config.get("bucket")
    if value not in (None, ""):
        return str(value)
    persisted = _oss_persisted("bucket")
    if persisted:
        return persisted
    return _first_env("OSS_BUCKET", "ALIYUN_OSS_BUCKET") or default


def get_oss_public_base_url() -> str:
    tool_config = get_request_tool_config(CREATOR_OSS_CONFIG_TOOL)
    value = tool_config.get("public_base_url")
    if value not in (None, ""):
        return str(value)
    persisted = _oss_persisted("public_base_url")
    if persisted:
        return persisted
    return _first_env("OSS_PUBLIC_BASE_URL", "ALIYUN_OSS_PUBLIC_BASE_URL")


def get_video_backend() -> str:
    """Return the configured video backend protocol name.
    Priority: request-scoped _video_backend (set by protocol) > heuristic.
    """
    tool_cfg = get_request_tool_config(CREATOR_VIDEO_CONFIG_TOOL)
    backend = tool_cfg.get("_video_backend")
    if backend:
        return backend.strip().lower()
    model_name = get_video_model_name().lower()
    if "seedance" in model_name:
        return "seedance2"
    # Bailian HappyHorse (e.g. happyhorse-1.1-r2v) shares the Wan DashScope
    # async protocol; keep this explicit instead of relying on the "r2v"
    # substring below.
    if model_name.startswith("happyhorse"):
        return "wan"
    if model_name.startswith("wan") or "r2v" in model_name:
        return "wan"
    if "volcengine" in get_video_base_url().lower():
        return "seedance2"
    return "wan"


def _validate_video_backend_url(backend: str, base: str) -> None:
    base_lower = base.lower()
    if backend == "seedance2" and "volcengine" not in base_lower:
        raise ValueError(
            "VIDEO_MODEL_NAME selects Seedance2, but VIDEO_BASE_URL is not a Volcengine endpoint",
        )
    if backend == "wan" and "volcengine" in base_lower:
        raise ValueError(
            "VIDEO_MODEL_NAME selects Wan, but VIDEO_BASE_URL points to a Volcengine endpoint",
        )


def get_image_generations_url() -> str:
    return _image_provider().generation_url


def get_video_submit_url() -> str:
    base = get_video_base_url().rstrip("/")
    backend = get_video_backend()
    _validate_video_backend_url(backend, base)
    if backend == "seedance2":
        return f"{base}/api/v3/contents/generations/tasks"
    suffix = "/services/aigc/video-generation/video-synthesis"
    return base if base.endswith(suffix) else f"{base}{suffix}"


def get_video_task_url(task_id: str) -> str:
    """Return the full URL for checking the configured video generation task."""
    base = get_video_base_url().rstrip("/")
    backend = get_video_backend()
    _validate_video_backend_url(backend, base)
    if backend == "seedance2":
        return f"{base}/api/v3/contents/generations/tasks/{task_id}"
    suffix = "/services/aigc/video-generation/video-synthesis"
    api_root = base[: -len(suffix)] if base.endswith(suffix) else base
    return f"{api_root}/tasks/{task_id}"
