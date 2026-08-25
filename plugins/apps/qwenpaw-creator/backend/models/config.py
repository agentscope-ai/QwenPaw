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
CREATOR_TTS_CONFIG_TOOL = "creator_tts_model"
CREATOR_S2V_CONFIG_TOOL = "creator_s2v_model"
CREATOR_EMBEDDING_CONFIG_TOOL = "creator_embedding_model"
CREATOR_OSS_CONFIG_TOOL = "creator_media_oss"
EXECUTION_AUTHORIZATION_REQUIRED = "required"
EXECUTION_AUTHORIZATION_ALLOW_ALL = "allow_all"
CREATION_CHECKPOINT_REQUIRED = "required"
CREATION_CHECKPOINT_SKIP = "skip"

# Upstream video-edit governance modes ("how much to ask mid-flight").
EXECUTION_MODE_DELEGATED = "delegated"
EXECUTION_MODE_CO_CREATION = "co_creation"
EXECUTION_MODE_FINE_TUNING = "fine_tuning"
_EXECUTION_MODES = (
    EXECUTION_MODE_DELEGATED,
    EXECUTION_MODE_CO_CREATION,
    EXECUTION_MODE_FINE_TUNING,
)
MEDIA_REVIEW_REQUIRED = "required"
MEDIA_REVIEW_AUTO_APPROVE = "auto_approve"
CREATOR_CONFIG_TOOLS = (
    CREATOR_TEXT_CONFIG_TOOL,
    CREATOR_IMAGE_CONFIG_TOOL,
    CREATOR_VIDEO_CONFIG_TOOL,
    CREATOR_VLM_CONFIG_TOOL,
    CREATOR_GROUNDING_CONFIG_TOOL,
    CREATOR_ASR_CONFIG_TOOL,
    CREATOR_TTS_CONFIG_TOOL,
    CREATOR_S2V_CONFIG_TOOL,
    CREATOR_EMBEDDING_CONFIG_TOOL,
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


# Mirrors api.model_routes._SECRET_FIELDS so runtime reads of
# model_config.json can decrypt every field the API layer encrypts.
_SECRET_FIELDS = (
    "api_key",
    "access_key_secret",
    "policy_api_key",
    "tavily_api_key",
    "serper_api_key",
)


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


def get_execution_mode() -> str:
    """Return the mid-flight governance mode (upstream three modes).

    Ladder consistency: ``creation_checkpoints.mode=skip`` (the YOLO
    ladder stop) already means "no mid-flight gates", so it forces
    ``delegated`` regardless of the stored ``execution_mode`` — the two
    knobs can never contradict each other.
    """

    if get_creation_checkpoint_mode() == CREATION_CHECKPOINT_SKIP:
        return EXECUTION_MODE_DELEGATED
    section = _get_user_config().get("creation_checkpoints")
    value = (
        section.get("execution_mode") if isinstance(section, dict) else None
    )
    if value in _EXECUTION_MODES:
        return value
    return EXECUTION_MODE_CO_CREATION


def get_media_review_mode() -> str:
    """Return the persisted mode for generated-media reviews.

    ``auto_approve`` is the last gate of the fully unattended (YOLO)
    ladder: generated media is accepted straight into the Project without
    a pending Review. Until VLM quality checks land, this trades quality
    control for wall time, so the safe default stays ``required``.
    """

    section = _get_user_config().get("media_review")
    value = section.get("mode") if isinstance(section, dict) else None
    if value == MEDIA_REVIEW_AUTO_APPROVE:
        return MEDIA_REVIEW_AUTO_APPROVE
    return MEDIA_REVIEW_REQUIRED


DEFAULT_MAINLINE_MAX_MODEL_TURNS = 24
DEFAULT_SPECIALIST_MAX_MODEL_TURNS = 16
DEFAULT_MEDIA_PARALLELISM = 5
DEFAULT_MEDIA_CALL_BUDGET = 200


def get_media_call_budget() -> int:
    """Per-project cap on billable media generation calls.

    The wallet fuse for unattended operation: call counts are the honest
    spend metric (local price tables were removed — they go stale and
    mislead). The default is deliberately loose; it exists to stop a
    runaway project, not to police normal use.
    """

    section = _get_user_config().get("agent_runtime")
    value = (
        section.get("media_call_budget")
        if isinstance(
            section,
            dict,
        )
        else None
    )
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_MEDIA_CALL_BUDGET


def get_media_parallelism() -> int:
    """Per-project cap on concurrently dispatched media tasks.

    The work-graph scheduler fans out READY media nodes up to this many
    at once; the global model_slot semaphores still bound each provider
    kind underneath, so this is the coarse project-level knob.
    """

    section = _get_user_config().get("agent_runtime")
    value = (
        section.get("media_parallelism")
        if isinstance(
            section,
            dict,
        )
        else None
    )
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_MEDIA_PARALLELISM


def _turn_limit(section: dict | None, key: str, default: int) -> int:
    value = section.get(key) if isinstance(section, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def get_mainline_max_model_turns() -> int:
    """Per-run model turn budget for the mainline Creator Agent loop.

    A runaway guard, not a latency control: pathological loops are stopped
    earlier by the repeated-deterministic-failure guard, so this cap only
    decides whether long-but-healthy runs (one timeline element per
    jq_project call) can finish. Override via the ``agent_runtime`` config
    section; YOLO-style modes are expected to raise it.
    """

    return _turn_limit(
        _get_user_config().get("agent_runtime"),
        "mainline_max_model_turns",
        DEFAULT_MAINLINE_MAX_MODEL_TURNS,
    )


def get_specialist_max_model_turns() -> int:
    """Per-run model turn budget for one specialist (subagent) loop."""

    return _turn_limit(
        _get_user_config().get("agent_runtime"),
        "specialist_max_model_turns",
        DEFAULT_SPECIALIST_MAX_MODEL_TURNS,
    )


# One element consumes several mainline turns (create, delegate, resume),
# so a fixed cap misfires on large projects: the scaled floor keeps the
# runaway guard while letting long-but-healthy runs finish. Baseline covers
# read/ground/strategy/entities; the per-element share covers structure
# authoring plus delegation.
TURN_SCALING_BASELINE = 8
TURN_SCALING_PER_ELEMENT = 3


def scale_mainline_max_model_turns(base: int, element_count: int) -> int:
    """Raise the mainline budget for element-heavy projects, never lower it."""

    if element_count <= 0:
        return base
    return max(
        base,
        TURN_SCALING_BASELINE + TURN_SCALING_PER_ELEMENT * element_count,
    )


def _map_tool_to_section(tool_name: str) -> str:
    return {
        CREATOR_TEXT_CONFIG_TOOL: "llm",
        CREATOR_VLM_CONFIG_TOOL: "vlm",
        CREATOR_GROUNDING_CONFIG_TOOL: "grounding",
        CREATOR_ASR_CONFIG_TOOL: "asr",
        CREATOR_TTS_CONFIG_TOOL: "tts",
        CREATOR_S2V_CONFIG_TOOL: "s2v",
        CREATOR_EMBEDDING_CONFIG_TOOL: "embedding",
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


# ── TTS Model (DashScope Qwen3-TTS) ─────────────────────────────────────────
TTS_BASE_URL = os.environ.get(
    "TTS_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1",
)
TTS_API_KEY = os.environ.get("TTS_API_KEY", "")
TTS_MODEL_NAME = os.environ.get("TTS_MODEL_NAME", "qwen3-tts-flash")
TTS_VOICE = os.environ.get("TTS_VOICE", "Cherry")
# Voice-cloned synthesis requires a dedicated VC model; enrollment binds the
# custom voice to this model and synthesis with a voice_id must reuse it.
TTS_VC_MODEL_NAME = os.environ.get(
    "TTS_VC_MODEL_NAME",
    "qwen3-tts-vc-2026-01-22",
)
TTS_TIMEOUT_SECONDS = _positive_int_env("TTS_TIMEOUT_SECONDS", 300)


# ── S2V Digital-Human Model (DashScope Wan2.2-S2V) ─────────────────────────
S2V_BASE_URL = os.environ.get(
    "S2V_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1",
)
S2V_API_KEY = os.environ.get("S2V_API_KEY", "")
S2V_MODEL_NAME = os.environ.get("S2V_MODEL_NAME", "wan2.2-s2v")
# The face-detect companion is free and always runs before submission.
S2V_DETECT_MODEL_NAME = os.environ.get(
    "S2V_DETECT_MODEL_NAME",
    "wan2.2-s2v-detect",
)
S2V_TIMEOUT_SECONDS = _positive_int_env("S2V_TIMEOUT_SECONDS", 120)
# ── Embedding Model (DashScope native multimodal-embedding) ─────────────────
EMBEDDING_BASE_URL = os.environ.get(
    "EMBEDDING_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1",
)
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL_NAME",
    "qwen3-vl-embedding",
)


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


def get_text_protocol() -> str:
    tool_config = get_request_tool_config(CREATOR_TEXT_CONFIG_TOOL)
    if tool_config:
        return str(tool_config.get("protocol") or "").strip()
    section = _get_user_config().get("llm")
    if isinstance(section, dict) and section.get("protocol"):
        return str(section["protocol"]).strip()
    return os.environ.get("TEXT_PROTOCOL", "").strip()


def get_text_chat_url() -> str:
    """Return the chat-completion endpoint URL for the configured text model.

    Protocol-aware: Anthropic/MiniMax use ``/v1/messages``, everything
    else falls back to the OpenAI-compatible ``/chat/completions``.
    """
    return chat_url_for(
        get_text_base_url(),
        get_text_protocol(),
        get_text_model_name(),
    )


def _vlm_use_llm() -> bool:
    """Return True when the persisted VLM section reuses the text model.

    ``use_llm`` means full reuse (key, endpoint, model). Any explicit values
    left over in the VLM section are stale configuration and must not win,
    otherwise requests go to a mismatched endpoint/key pair.
    """
    section = _get_user_config().get("vlm")
    return bool(isinstance(section, dict) and section.get("use_llm"))


def get_vlm_api_key() -> str:
    if _vlm_use_llm():
        return get_text_api_key()
    return (
        _explicit_configured_value(
            CREATOR_VLM_CONFIG_TOOL,
            "api_key",
            ("VLM_API_KEY", "DASHSCOPE_API_KEY"),
        )
        or get_text_api_key()
    )


def get_vlm_base_url() -> str:
    if _vlm_use_llm():
        return get_text_base_url()
    return (
        _explicit_configured_value(
            CREATOR_VLM_CONFIG_TOOL,
            ("base_url", "endpoint"),
            ("VLM_BASE_URL", "DASHSCOPE_BASE_URL"),
        )
        or get_text_base_url()
    )


def get_vlm_model_name() -> str:
    if _vlm_use_llm():
        return get_text_model_name()
    return (
        _explicit_configured_value(
            CREATOR_VLM_CONFIG_TOOL,
            "model",
            ("VLM_MODEL_NAME",),
        )
        or get_text_model_name()
    )


def get_vlm_protocol() -> str:
    if _vlm_use_llm():
        return get_text_protocol()
    tool_config = get_request_tool_config(CREATOR_VLM_CONFIG_TOOL)
    if tool_config:
        return str(tool_config.get("protocol") or "").strip()
    section = _get_user_config().get("vlm")
    if isinstance(section, dict) and section.get("protocol"):
        return str(section["protocol"]).strip()
    return os.environ.get("VLM_PROTOCOL", "").strip() or get_text_protocol()


# ── Protocol classification helpers ──────────────────────────────────────────
# Shared by text_model, vlm_model, model_client, and model_routes to decide
# URL path, headers, body format, and response parsing per API protocol.
# Keep the classification logic here; every other module must import these
# helpers instead of re-implementing them.


def is_anthropic_protocol(protocol: str) -> bool:
    """True when *protocol* uses the Anthropic Messages API format."""
    lower = protocol.casefold()
    return "anthropic" in lower or "minimax" in lower


def is_gemini_protocol(protocol: str) -> bool:
    """True when *protocol* uses the Google Gemini Generative AI format."""
    lower = protocol.casefold()
    return "gemini" in lower or "google" in lower


def protocol_requires_api_key(protocol: str) -> bool:
    """True when the protocol has no keyless tier and needs a credential.

    Anthropic and Gemini gateways always authenticate; OpenAI-compatible
    gateways may expose free keyless models (e.g. OpenCode Zen ``*-free``).
    """
    return is_anthropic_protocol(protocol) or is_gemini_protocol(protocol)


def get_vlm_chat_url() -> str:
    """Return the chat-completion endpoint URL for the configured VLM.

    Protocol-aware via ``chat_url_for``: Anthropic/MiniMax use
    ``/v1/messages``, Gemini uses ``/v1beta/models/{model}:generateContent``,
    everything else falls back to the OpenAI-compatible
    ``/chat/completions``.
    """
    return chat_url_for(
        get_vlm_base_url(),
        get_vlm_protocol(),
        get_vlm_model_name(),
    )


def chat_url_for(base_url: str, protocol: str, model_name: str = "") -> str:
    """Return the correct chat-completion URL for *base_url* + *protocol*."""
    base = base_url.rstrip("/")
    if is_anthropic_protocol(protocol):
        return f"{base}/v1/messages"
    if is_gemini_protocol(protocol):
        return f"{base}/v1beta/models/{model_name}:generateContent"
    return (
        base
        if base.endswith("/chat/completions")
        else f"{base}/chat/completions"
    )


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


def get_web_grounding_serper_api_key() -> str:
    return _grounding_explicit(
        "serper_api_key",
        ("SERPER_API_KEY", "WEB_GROUNDING_SERPER_API_KEY"),
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


def get_embedding_api_key() -> str:
    """Embedding key: explicit value first, else optionally reuse VLM."""

    configured = _explicit_configured_value(
        CREATOR_EMBEDDING_CONFIG_TOOL,
        "api_key",
        ("EMBEDDING_API_KEY",),
    )
    if configured:
        return configured
    section = _get_user_config().get("embedding", {})
    reuse = not isinstance(section, dict) or section.get(
        "reuse_vlm_key",
        True,
    )
    return get_vlm_api_key() if reuse else ""


def get_embedding_base_url() -> str:
    return _configured_value(
        CREATOR_EMBEDDING_CONFIG_TOOL,
        ("base_url", "endpoint"),
        "EMBEDDING_BASE_URL",
        EMBEDDING_BASE_URL,
    )


def get_embedding_model_name() -> str:
    return _configured_value(
        CREATOR_EMBEDDING_CONFIG_TOOL,
        "model",
        "EMBEDDING_MODEL_NAME",
        EMBEDDING_MODEL_NAME,
    )


def is_embedding_enabled() -> bool:
    if get_request_tool_config(CREATOR_EMBEDDING_CONFIG_TOOL):
        return True
    section = _get_user_config().get("embedding")
    if isinstance(section, dict) and section.get("enabled") is True:
        return True
    return os.environ.get("EMBEDDING_ENABLED", "").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_embedding_configured() -> bool:
    """Memory builds require an enabled section with a resolvable key."""

    return is_embedding_enabled() and bool(get_embedding_api_key())


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


def get_tts_api_key() -> str:
    configured = _explicit_configured_value(
        CREATOR_TTS_CONFIG_TOOL,
        "api_key",
        ("TTS_API_KEY",),
    )
    if configured:
        return configured
    # Speech synthesis runs on the same DashScope credential as the text
    # model, so reuse it by default instead of asking for the key twice.
    section = _get_user_config().get("tts", {})
    reuse = not isinstance(section, dict) or section.get(
        "reuse_llm_key",
        True,
    )
    return get_text_api_key() if reuse else ""


def get_tts_base_url() -> str:
    return _configured_value(
        CREATOR_TTS_CONFIG_TOOL,
        ("base_url", "endpoint"),
        "TTS_BASE_URL",
        TTS_BASE_URL,
    )


def get_tts_model_name() -> str:
    return _configured_value(
        CREATOR_TTS_CONFIG_TOOL,
        "model",
        "TTS_MODEL_NAME",
        TTS_MODEL_NAME,
    )


def get_tts_voice() -> str:
    return _configured_value(
        CREATOR_TTS_CONFIG_TOOL,
        "voice",
        "TTS_VOICE",
        TTS_VOICE,
    )


def get_tts_vc_model_name() -> str:
    """Model that cloned voices bind to, derived from the synthesis model.

    Voice cloning/design run on companion models the user should never have to
    name: the capability table maps each synthesis model to its own, so the
    configuration surface stays "key + model".
    """

    from models.tts_capabilities import require_capability

    override = _configured_value(
        CREATOR_TTS_CONFIG_TOOL,
        "vc_model",
        "TTS_VC_MODEL_NAME",
        "",
    )
    if override:
        return override
    return require_capability(get_tts_model_name()).clone_model()


def get_tts_vd_model_name() -> str:
    """Model that designed voices bind to, derived the same way."""

    from models.tts_capabilities import require_capability

    return require_capability(get_tts_model_name()).design_model()


def tts_has_system_voices() -> bool:
    """False when the configured model can only speak with created voices."""

    from models.tts_capabilities import require_capability

    return require_capability(get_tts_model_name()).has_system_voices


def get_tts_timeout_seconds() -> int:
    return _configured_int(
        CREATOR_TTS_CONFIG_TOOL,
        "timeout_seconds",
        "TTS_TIMEOUT_SECONDS",
        TTS_TIMEOUT_SECONDS,
    )


def is_tts_configured() -> bool:
    """True when TTS synthesis can run: an API key is resolvable.

    Gates the TTS specialist tools and the TTS prompt sections, so an
    unconfigured deployment exposes neither.
    """

    return bool(get_tts_api_key())


def get_s2v_api_key() -> str:
    configured = _explicit_configured_value(
        CREATOR_S2V_CONFIG_TOOL,
        "api_key",
        ("S2V_API_KEY",),
    )
    if configured:
        return configured
    # wan2.2-s2v runs on the same DashScope credential as the text model,
    # so reuse it by default instead of asking for the key twice.
    section = _get_user_config().get("s2v", {})
    reuse = not isinstance(section, dict) or section.get(
        "reuse_llm_key",
        True,
    )
    return get_text_api_key() if reuse else ""


def get_s2v_base_url() -> str:
    return _configured_value(
        CREATOR_S2V_CONFIG_TOOL,
        ("base_url", "endpoint"),
        "S2V_BASE_URL",
        S2V_BASE_URL,
    )


def get_s2v_model_name() -> str:
    return _configured_value(
        CREATOR_S2V_CONFIG_TOOL,
        "model",
        "S2V_MODEL_NAME",
        S2V_MODEL_NAME,
    )


def get_s2v_detect_model_name() -> str:
    """Free face-detect companion model.

    Both spellings are accepted: the plugin-host tool config uses
    ``detect_model`` (plugin.json field name) while the persisted Creator
    config and the frontend contract use ``detect_model_name``
    (``S2vConfig`` field name).
    """

    return _configured_value(
        CREATOR_S2V_CONFIG_TOOL,
        ("detect_model", "detect_model_name"),
        "S2V_DETECT_MODEL_NAME",
        S2V_DETECT_MODEL_NAME,
    )


def get_s2v_timeout_seconds() -> int:
    return _configured_int(
        CREATOR_S2V_CONFIG_TOOL,
        "timeout_seconds",
        "S2V_TIMEOUT_SECONDS",
        S2V_TIMEOUT_SECONDS,
    )


def is_s2v_configured() -> bool:
    """True when the digital-human provider can run: a key is resolvable.

    Gates the s2v specialist tool the same way ``is_tts_configured`` gates
    the TTS tools, so an unconfigured deployment never exposes it.
    """

    return bool(get_s2v_api_key())


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.casefold() in {"1", "true", "yes", "on"}


# Review tiers resolve at decision time through the ``is_*_review_enabled()``
# functions below: an explicitly set environment variable wins (CI and
# emergency override), otherwise the persisted ``self_review`` section of
# model_config.json (settings center) decides. The former module-level
# startup snapshots were removed: nothing imported them, and a stale
# snapshot diverging from the runtime getters was a latent trap.


def _review_tier_enabled(env_name: str, config_key: str) -> bool:
    """Resolve one review tier: explicit env wins, else persisted config.

    An explicitly set environment variable (even ``0``/``false``) keeps
    full control so existing deployments behave exactly as before; only
    when it is absent does the ``self_review`` section of the user's
    model_config.json decide, defaulting to off.
    """
    raw = os.environ.get(env_name, "").strip()
    if raw:
        return raw.casefold() in {"1", "true", "yes", "on"}
    section = _get_user_config().get("self_review")
    if isinstance(section, dict):
        return bool(section.get(config_key, False))
    return False


def is_self_review_enabled() -> bool:
    """Final-cut render review (tier 3): env override, else user config."""
    return _review_tier_enabled(
        "CREATOR_SELF_REVIEW_ENABLED",
        "render_enabled",
    )


_REVIEW_TIER_ENV_VARS = (
    "CREATOR_SYNC_REVIEW_ENABLED",
    "CREATOR_MEDIA_REVIEW_ENABLED",
    "CREATOR_SELF_REVIEW_ENABLED",
)


def forced_review_env_overrides() -> dict[str, str]:
    """Review tier env vars that are explicitly set and shadow the UI.

    The settings center owns these switches when the environment stays
    silent; an explicitly set variable takes full control, which is easy
    to forget (field incident: review ran with the UI toggled off).
    Startup logs this map so the override is loud instead of a ghost.
    """

    return {
        name: os.environ[name].strip()
        for name in _REVIEW_TIER_ENV_VARS
        if os.environ.get(name, "").strip()
    }


def is_sync_review_enabled() -> bool:
    """In-run synchronous review of low-cost text/motion artifacts."""
    return _review_tier_enabled("CREATOR_SYNC_REVIEW_ENABLED", "sync_enabled")


def is_media_review_enabled() -> bool:
    """Async bypass review of generated image/video artifacts."""
    return _review_tier_enabled(
        "CREATOR_MEDIA_REVIEW_ENABLED",
        "media_enabled",
    )


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


def get_image_translate_model_name() -> str:
    """Model used by image_generation mode=translate (Bailian qwen-mt-image).

    Optional field on the image config tree; no dedicated tree is needed
    because translation always rides the DashScope image credential.
    """

    return _configured_value(
        CREATOR_IMAGE_CONFIG_TOOL,
        "translate_model",
        "IMAGE_TRANSLATE_MODEL_NAME",
        "qwen-mt-image",
    )


def get_video_api_key() -> str:
    """Video credential: explicit value first, else optionally reuse LLM.

    Bailian video generation runs on the same DashScope credential as the
    text model, so when no video-specific key is configured and the
    persisted ``video.reuse_llm_key`` flag (default on) allows it, the text
    key is reused — mirroring the tts/s2v sections.
    """

    configured = _configured_value(
        CREATOR_VIDEO_CONFIG_TOOL,
        "api_key",
        "VIDEO_API_KEY",
        VIDEO_API_KEY,
    )
    if configured:
        return configured
    # Reuse only applies to the DashScope (wan/happyhorse) backend: a
    # Volcano Engine deployment has its own credential namespace.
    if get_video_backend() != "wan":
        return ""
    section = _get_user_config().get("video", {})
    reuse = not isinstance(section, dict) or section.get(
        "reuse_llm_key",
        True,
    )
    return get_text_api_key() if reuse else ""


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


def get_video_concurrency() -> int:
    """Semaphore cap for model_slot("video").

    Defaults to the scheduler's dispatch cap so the provider semaphore
    never silently serializes renders behind a parallel-looking work
    graph (same coupling as the image providers); explicit env/config
    still wins.
    """

    return _configured_int(
        CREATOR_VIDEO_CONFIG_TOOL,
        "concurrency",
        "VIDEO_CONCURRENCY",
        get_media_parallelism(),
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


def video_backend_for_protocol(protocol: str) -> str | None:
    """Map a saved protocol label onto a video transport backend.

    Single source of truth for the channel choice: the UI protocol
    selection decides the transport (notably Kling/Vidu, which exist both
    as Bailian-hosted models on the DashScope protocol and as official
    channels), so it is shared by the request-scoped mapping in
    ``api.model_routes`` and the persisted-config fallback below.
    Returns ``None`` when the label names no known protocol.
    """
    # pylint: disable=too-many-return-statements
    if not protocol:
        return None
    lowered = protocol.casefold()
    if "token plan" in lowered or "tokenplan" in lowered:
        return "wan"
    if "dashscope" in lowered or "百炼" in protocol:
        return "wan"
    if "volcano" in lowered or "火山" in protocol:
        return "seedance2"
    if "gemini" in lowered or "veo" in lowered:
        return "veo"
    if "minimax" in lowered or "海螺" in protocol:
        return "minimax"
    if "kling" in lowered or "可灵" in protocol:
        return "kling"
    if "vidu" in lowered:
        return "vidu"
    return None


def get_video_backend() -> (
    str
):  # pylint: disable=too-many-return-statements,too-many-branches
    """Return the configured video backend protocol name.

    Priority: request-scoped ``_video_backend`` (set from the saved
    protocol) > the saved protocol label itself (request-scoped, then the
    persisted config so background workers resolve identically) >
    base_url / model-name heuristics for standalone env-var deployments.

    The Kling/Vidu channel (Bailian hosting vs official API) is a user
    configuration decision, so it is resolved from the protocol or the
    endpoint host — never inferred from the model name.
    """
    tool_cfg = get_request_tool_config(CREATOR_VIDEO_CONFIG_TOOL)
    backend = tool_cfg.get("_video_backend")
    if backend:
        return backend.strip().lower()
    protocol_backend = video_backend_for_protocol(
        str(tool_cfg.get("protocol") or ""),
    )
    if protocol_backend is not None:
        return protocol_backend
    # Persisted UI config: background workers run outside any HTTP request
    # and have no request-scoped Tool Config bound; the saved protocol
    # must select the same transport an in-request call would.
    section = _get_user_config().get("video", {})
    if isinstance(section, dict) and section.get("enabled"):
        protocol_backend = video_backend_for_protocol(
            str(section.get("protocol") or ""),
        )
        if protocol_backend is not None:
            return protocol_backend
    # Standalone/env fallbacks: the configured endpoint host decides the
    # channel (still a user configuration choice, unlike the model name).
    base_url = get_video_base_url().lower()
    if "volcengine" in base_url:
        return "seedance2"
    if "generativelanguage" in base_url:
        return "veo"
    if "klingai" in base_url:
        return "kling"
    if "vidu.com" in base_url or "vidu.cn" in base_url:
        return "vidu"
    if "minimax" in base_url:
        return "minimax"
    # Last resort: model-name hints, only for families without any channel
    # ambiguity. Kling/Vidu names never select a channel here — without a
    # protocol or endpoint hint they stay on the DashScope default.
    model_name = get_video_model_name().lower()
    if "seedance" in model_name:
        return "seedance2"
    if model_name.startswith("veo"):
        return "veo"
    if "hailuo" in model_name or model_name.startswith(
        ("minimax", "t2v-01", "i2v-01", "s2v-01"),
    ):
        return "minimax"
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
    if backend == "veo" and "generativelanguage" not in base_lower:
        raise ValueError(
            "VIDEO_MODEL_NAME selects Veo (Gemini API), but VIDEO_BASE_URL "
            "is not a generativelanguage.googleapis.com endpoint",
        )
    if backend == "minimax" and "minimax" not in base_lower:
        raise ValueError(
            "VIDEO_MODEL_NAME selects MiniMax, but VIDEO_BASE_URL is not a "
            "MiniMax endpoint (api.minimax.io / api.minimaxi.com)",
        )
    if backend == "kling" and "klingai" not in base_lower:
        raise ValueError(
            "VIDEO_MODEL_NAME selects the official Kling channel, but "
            "VIDEO_BASE_URL is not a klingai.com endpoint",
        )
    if backend == "vidu" and "vidu" not in base_lower:
        raise ValueError(
            "VIDEO_MODEL_NAME selects the official Vidu channel, but "
            "VIDEO_BASE_URL is not a vidu.com endpoint",
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


# ── External skills config (from skills_config.json) ────────────────────────────


def _get_skills_config_path() -> Path:
    configured = os.environ.get("CREATOR_SKILLS_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    data_root = os.environ.get("CREATOR_DATA_ROOT", "").strip()
    if data_root:
        return (
            Path(data_root).expanduser().resolve(strict=False)
            / "config"
            / "skills_config.json"
        )
    # Read-only sentinel: skill configuration has no source-tree fallback.
    return Path("/__qwenpaw_creator_unconfigured__/skills_config.json")


_SKILLS_CONFIG_CACHE: tuple[list, list] | None = None
_SKILLS_CONFIG_CACHE_PATH: Path | None = None
_SKILLS_CONFIG_CACHE_FINGERPRINT: tuple[int, int, int] | None = None


def _issue_entry_name(raw: object, index: int) -> str:
    if isinstance(raw, Mapping):
        name = str(raw.get("name") or "").strip()
        if name:
            return name
    return f"entry-{index}"


def _load_skills_config_document() -> tuple[list, list]:
    """Return ``(valid SkillEntry items, diagnostics)`` from disk/cache.

    Mirrors the ``_get_user_config`` fingerprint cache. The file holds no
    secrets (key-like values are referenced indirectly via env variable
    names), so nothing is decrypted. Any read/parse/validation failure is
    isolated — never raised — but stays observable: broken documents and
    rejected entries are reported as diagnostics
    ``{"name", "path", "reason"}`` so callers can surface an unavailable
    skill with a readable reason.
    """

    global _SKILLS_CONFIG_CACHE
    global _SKILLS_CONFIG_CACHE_PATH, _SKILLS_CONFIG_CACHE_FINGERPRINT
    from schemas.skills import SkillEntry

    path = _get_skills_config_path()
    fingerprint = _user_config_fingerprint(path)
    if (
        _SKILLS_CONFIG_CACHE is not None
        and _SKILLS_CONFIG_CACHE_PATH == path
        and _SKILLS_CONFIG_CACHE_FINGERPRINT == fingerprint
    ):
        entries, issues = _SKILLS_CONFIG_CACHE
        return list(entries), list(issues)
    if fingerprint is None:
        return [], []
    entries: list[SkillEntry] = []
    issues: list[dict] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        raw_items = (
            document.get("skills") if isinstance(document, dict) else None
        )
        if not isinstance(raw_items, list):
            issues.append(
                {
                    "name": "skills-config",
                    "path": str(path),
                    "reason": 'document must be {"skills": [...]}',
                },
            )
            raw_items = []
        seen_names: set[str] = set()
        for index, raw in enumerate(raw_items):
            try:
                entry = SkillEntry.model_validate(raw)
            except Exception as exc:
                issues.append(
                    {
                        "name": _issue_entry_name(raw, index),
                        "path": str(
                            raw.get("path", "")
                            if isinstance(raw, Mapping)
                            else "",
                        ),
                        "reason": f"schema validation failed: {exc}"[:400],
                    },
                )
                continue
            if entry.name in seen_names:
                issues.append(
                    {
                        "name": entry.name,
                        "path": entry.path,
                        "reason": "duplicate skill name; first entry wins",
                    },
                )
                continue
            seen_names.add(entry.name)
            entries.append(entry)
    except Exception as exc:
        return [], [
            {
                "name": "skills-config",
                "path": str(path),
                "reason": f"document parse failed: {exc}"[:400],
            },
        ]
    _SKILLS_CONFIG_CACHE = (entries, issues)
    _SKILLS_CONFIG_CACHE_PATH = path
    _SKILLS_CONFIG_CACHE_FINGERPRINT = fingerprint
    return list(entries), list(issues)


def load_skills_config() -> list:
    """Return the validated ``SkillEntry`` items from skills_config.json."""

    entries, _issues = _load_skills_config_document()
    return entries


def load_skills_config_issues() -> list:
    """Return diagnostics for configuration entries that were rejected."""

    _entries, issues = _load_skills_config_document()
    return issues


def _clear_skills_config_cache():
    global _SKILLS_CONFIG_CACHE
    global _SKILLS_CONFIG_CACHE_PATH, _SKILLS_CONFIG_CACHE_FINGERPRINT
    _SKILLS_CONFIG_CACHE = None
    _SKILLS_CONFIG_CACHE_PATH = None
    _SKILLS_CONFIG_CACHE_FINGERPRINT = None
