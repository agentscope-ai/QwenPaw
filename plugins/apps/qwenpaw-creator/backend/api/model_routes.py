# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
# pylint: disable=wrong-import-order
# pylint: disable=raise-missing-from
"""External-root model configuration and explicit provider connection probes."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import os
import re
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse, urlsplit

import httpx
from fastapi import APIRouter, Body, Header, Query, Request, Response, status
from pydantic import ValidationError as PydanticValidationError

from domain.errors import ConflictError, StorageIntegrityError, ValidationError
from models import config as model_config
from models.minimax_errors import minimax_probe_base_resp_error
from schemas.models import (
    AsrConfig,
    EmbeddingConfig,
    ExecutionAuthorizationConfig,
    GroundingConfig,
    ImageConfig,
    VideoConfig,
    LlmConfig,
    ModelConfigData,
    ModelConfigItem,
    ModelConnectionTestRequest,
    ConnectionTestResponse,
    OssConfig,
    VlmConfig,
    reuse_llm_from_validation_source,
    validation_source_from_reuse_llm,
)
from services.runtime_files.atomic_store import (
    atomic_replace_bytes,
    canonical_json_bytes,
)
from services.runtime_files.errors import (
    IdempotencyConflictError,
    IdempotencyStateConflictError,
)
from services.runtime_files.idempotency_store import IdempotencyRecordStore
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.models import IdempotencyStatus
from services.storage_root import (
    CreatorDataRootError,
    require_creator_data_root,
)

# QwenPaw secret store for reading encrypted provider API keys
try:
    from qwenpaw.security.secret_store import (
        decrypt as qwenpaw_decrypt,
        encrypt as qwenpaw_encrypt,
        is_encrypted as qwenpaw_is_encrypted,
    )
    from qwenpaw.constant import SECRET_DIR as QWENPAW_SECRET_DIR

    QWENPAW_SECRET_AVAILABLE = True
except ImportError:
    QWENPAW_SECRET_AVAILABLE = False
    qwenpaw_decrypt = None
    qwenpaw_encrypt = None
    qwenpaw_is_encrypted = None
    QWENPAW_SECRET_DIR = None

from .dependencies import (
    CreatorErrorRoute,
    resolve_idempotency_key,
)

from utils.exceptions import redact_url, upstream_status_hint
from utils.logger import setup_logger

logger = setup_logger("model_routes")


def _log_safe(value: object) -> str:
    """Neutralize CR/LF in user-provided values before logging."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


router = APIRouter(
    prefix="/models",
    tags=["models"],
    route_class=CreatorErrorRoute,
)


_SECTIONS = (
    "llm",
    "vlm",
    "grounding",
    "asr",
    "tts",
    "s2v",
    "embedding",
    "image",
    "video",
    "oss",
)
_ENV_MAPPING: dict[str, dict[str, tuple[str, ...]]] = {
    "llm": {
        "base_url": ("TEXT_BASE_URL",),
        "api_key": ("TEXT_API_KEY",),
        "model_name": ("TEXT_MODEL_NAME",),
    },
    "vlm": {
        "base_url": ("VLM_BASE_URL", "TEXT_BASE_URL"),
        "api_key": ("VLM_API_KEY", "TEXT_API_KEY"),
        "model_name": ("VLM_MODEL_NAME", "TEXT_MODEL_NAME"),
    },
    "grounding": {
        "enabled": ("WEB_GROUNDING_ENABLED",),
        "tavily_api_key": (
            "TAVILY_API_KEY",
            "WEB_GROUNDING_TAVILY_API_KEY",
        ),
        "serper_api_key": (
            "SERPER_API_KEY",
            "WEB_GROUNDING_SERPER_API_KEY",
        ),
        "reuse_llm": (
            "WEB_GROUNDING_REUSE_LLM",
            "WEB_GROUNDING_REUSE_VLM",
        ),
        "validation_source": ("WEB_GROUNDING_VALIDATION_SOURCE",),
        "base_url": (
            "WEB_GROUNDING_LLM_BASE_URL",
            "WEB_GROUNDING_VLM_BASE_URL",
        ),
        "api_key": (
            "WEB_GROUNDING_LLM_API_KEY",
            "WEB_GROUNDING_VLM_API_KEY",
        ),
        "model_name": (
            "WEB_GROUNDING_LLM_MODEL_NAME",
            "WEB_GROUNDING_VLM_MODEL_NAME",
        ),
        "native_search_enabled": ("WEB_GROUNDING_NATIVE_SEARCH_ENABLED",),
        "search_provider": ("WEB_GROUNDING_SEARCH_PROVIDER",),
        "search_reuse_llm": ("WEB_GROUNDING_SEARCH_REUSE_LLM",),
        "search_base_url": ("WEB_GROUNDING_SEARCH_BASE_URL",),
        "search_api_key": ("WEB_GROUNDING_SEARCH_API_KEY",),
        "search_model_name": ("WEB_GROUNDING_SEARCH_MODEL_NAME",),
        "search_protocol": ("WEB_GROUNDING_SEARCH_PROTOCOL",),
    },
    "asr": {
        "base_url": ("ASR_BASE_URL",),
        "api_key": ("ASR_API_KEY",),
        "model_name": ("ASR_MODEL_NAME",),
    },
    "tts": {
        "base_url": ("TTS_BASE_URL",),
        "api_key": ("TTS_API_KEY",),
        "model_name": ("TTS_MODEL_NAME",),
        "voice": ("TTS_VOICE",),
        "vc_model_name": ("TTS_VC_MODEL_NAME",),
    },
    "s2v": {
        "base_url": ("S2V_BASE_URL",),
        "api_key": ("S2V_API_KEY",),
        "model_name": ("S2V_MODEL_NAME",),
        "detect_model_name": ("S2V_DETECT_MODEL_NAME",),
    },
    "embedding": {
        "base_url": ("EMBEDDING_BASE_URL",),
        "api_key": ("EMBEDDING_API_KEY",),
        "model_name": ("EMBEDDING_MODEL_NAME",),
    },
    "image": {
        "base_url": (
            "DASHSCOPE_IMAGE_BASE_URL",
            "OPENAI_IMAGE_BASE_URL",
            "IMAGE_BASE_URL",
        ),
        "api_key": (
            "DASHSCOPE_IMAGE_API_KEY",
            "OPENAI_IMAGE_API_KEY",
            "IMAGE_API_KEY",
        ),
        "model_name": (
            "DASHSCOPE_IMAGE_MODEL_NAME",
            "OPENAI_IMAGE_MODEL_NAME",
            "IMAGE_MODEL_NAME",
        ),
        "translate_model": ("IMAGE_TRANSLATE_MODEL_NAME",),
    },
    "video": {
        "base_url": ("VIDEO_BASE_URL",),
        "api_key": ("VIDEO_API_KEY",),
        "model_name": ("VIDEO_MODEL_NAME",),
    },
}


def _config_paths() -> Path:
    configured = os.environ.get("CREATOR_MODEL_CONFIG_PATH", "").strip()
    config_path = (
        Path(configured).expanduser().resolve(strict=False)
        if configured
        else require_creator_data_root() / "config" / "model_config.json"
    )
    root = require_creator_data_root().resolve()
    if not config_path.is_absolute() or not config_path.resolve(
        strict=False,
    ).is_relative_to(root):
        raise ValidationError(
            "CREATOR_MODEL_CONFIG_PATH 必须位于 CREATOR_DATA_ROOT 内",
        )
    return config_path


def _defaults() -> ModelConfigData:
    """Return an unconfigured form instead of pretending providers are loaded."""

    return ModelConfigData(
        llm=LlmConfig(
            enabled=True,
            protocol="OpenAI 协议",
            multimodal=False,
        ),
        vlm=VlmConfig(
            enabled=False,
            protocol="OpenAI 协议",
            use_llm=False,
            multimodal=False,
        ),
        grounding=GroundingConfig(
            enabled=True,
            reuse_llm=True,
            validation_source="llm",
            protocol="OpenAI 协议",
            native_search_enabled=True,
            search_provider="dashscope_qwen",
            search_reuse_llm=True,
            search_protocol="DashScope（百炼）",
        ),
        asr=AsrConfig(
            enabled=False,
            provider="fun-asr",
            model_name="fun-asr",
            base_url="https://dashscope.aliyuncs.com/api/v1",
            protocol="DashScope Fun-ASR",
            reuse_llm_key=True,
        ),
        image=ImageConfig(
            enabled=False,
            protocol="DashScope（百炼）",
        ),
        embedding=EmbeddingConfig(
            enabled=False,
            model_name="qwen3-vl-embedding",
            base_url="https://dashscope.aliyuncs.com/api/v1",
            protocol="DashScope（百炼）",
            reuse_vlm_key=True,
        ),
        video=VideoConfig(
            enabled=False,
            protocol="DashScope（百炼）",
        ),
        oss=OssConfig(),
        execution_authorization=ExecutionAuthorizationConfig(mode="required"),
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"模型配置文件不可解析: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"模型配置文件必须是 JSON object: {path.name}")
    return value


# Fingerprint-keyed snapshot of the raw persisted config.  Cache hits avoid
# the cross-process lock and disk read on every request dependency.
_RAW_CONFIG_CACHE: dict[str, Any] | None = None
_RAW_CONFIG_CACHE_PATH: Path | None = None
_RAW_CONFIG_CACHE_FINGERPRINT: tuple[int, int, int] | None = None


def _config_fingerprint(path: Path) -> tuple[int, int, int] | None:
    try:
        metadata = path.stat()
    except OSError:
        return None
    return metadata.st_ino, metadata.st_mtime_ns, metadata.st_size


def _invalidate_raw_config_cache() -> None:
    global _RAW_CONFIG_CACHE, _RAW_CONFIG_CACHE_PATH
    global _RAW_CONFIG_CACHE_FINGERPRINT
    _RAW_CONFIG_CACHE = None
    _RAW_CONFIG_CACHE_PATH = None
    _RAW_CONFIG_CACHE_FINGERPRINT = None


def _read_raw_config(config_path: Path) -> dict[str, Any]:
    global _RAW_CONFIG_CACHE, _RAW_CONFIG_CACHE_PATH
    global _RAW_CONFIG_CACHE_FINGERPRINT
    fingerprint = _config_fingerprint(config_path)
    if (
        _RAW_CONFIG_CACHE is not None
        and _RAW_CONFIG_CACHE_PATH == config_path
        and _RAW_CONFIG_CACHE_FINGERPRINT == fingerprint
    ):
        return _RAW_CONFIG_CACHE
    if fingerprint is None:
        return {}
    with CrossProcessFileLock(config_path.parent / ".model-config.lock"):
        configs = _load_json(config_path)
        fingerprint = _config_fingerprint(config_path)
    _RAW_CONFIG_CACHE = configs
    _RAW_CONFIG_CACHE_PATH = config_path
    _RAW_CONFIG_CACHE_FINGERPRINT = fingerprint
    return configs


def _merge_known_fields(
    base_section: dict[str, Any],
    incoming: dict[str, Any],
    section: str,
) -> dict[str, Any]:
    """Merge only fields the current schema knows into ``base_section``.

    ``model_config.json`` outlives plugin upgrades and downgrades, so it can
    carry fields this build has never heard of. The schema forbids extras,
    and letting them through turns every model-config route into an
    unhandled 500. Drop them (with a log) instead of failing the request.
    """

    recognized = {
        key: value for key, value in incoming.items() if key in base_section
    }
    dropped = set(incoming) - set(recognized)
    if dropped:
        logger.warning(
            f"Ignoring unknown fields in model config section "
            f"'{_log_safe(section)}': {_log_safe(sorted(dropped))}",
        )
    base_section.update(recognized)
    return recognized


def _assemble_model_config(
    configs: dict[str, Any],
    *,
    include_environment: bool,
) -> ModelConfigData:
    base = _defaults().model_dump()
    for section in _SECTIONS:
        config_section = configs.get(section)
        explicit: set[str] = set()
        if isinstance(config_section, dict):
            recognized = _merge_known_fields(
                base[section],
                config_section,
                section,
            )
            explicit.update(
                key
                for key, value in recognized.items()
                if value not in {None, ""}
            )
        if include_environment and section in _ENV_MAPPING:
            for field, env_names in _ENV_MAPPING[section].items():
                if field in explicit:
                    continue
                for name in env_names:
                    if os.environ.get(name):
                        base[section][field] = os.environ[name]
                        break
            if not isinstance(config_section, dict) and base[section].get(
                "model_name",
            ):
                base[section]["enabled"] = True
    grounding_section = configs.get("grounding")
    grounding_explicit = (
        grounding_section if isinstance(grounding_section, dict) else {}
    )
    if "validation_source" not in grounding_explicit and not (
        include_environment
        and os.environ.get("WEB_GROUNDING_VALIDATION_SOURCE")
    ):
        base["grounding"][
            "validation_source"
        ] = validation_source_from_reuse_llm(
            base["grounding"].get("reuse_llm", True),
        )
    base["grounding"]["reuse_llm"] = reuse_llm_from_validation_source(
        base["grounding"].get("validation_source") or "",
    )
    if "search_reuse_llm" not in grounding_explicit and not (
        include_environment
        and os.environ.get("WEB_GROUNDING_SEARCH_REUSE_LLM")
    ):
        # Before retrieval and verification were split, both reused the same
        # model selection. Preserve that behavior when loading an old file.
        base["grounding"]["search_reuse_llm"] = (
            grounding_explicit.get(
                "reuse_llm",
                base["grounding"].get("reuse_llm", True),
            )
            if "validation_source" not in grounding_explicit
            else True
        )
    if not base["grounding"].get("search_reuse_llm", True):
        legacy_search_fields = {
            "search_base_url": "base_url",
            "search_api_key": "api_key",
            "search_model_name": "model_name",
            "search_protocol": "protocol",
        }
        for search_field, legacy_field in legacy_search_fields.items():
            if search_field not in grounding_explicit:
                base["grounding"][search_field] = base["grounding"].get(
                    legacy_field,
                    "",
                )
    for extra_section in (
        "execution_authorization",
        "creation_checkpoints",
        "media_review",
        "self_review",
    ):
        incoming = configs.get(extra_section)
        if isinstance(incoming, dict):
            _merge_known_fields(base[extra_section], incoming, extra_section)
    if base["vlm"].get("use_llm"):
        # Full reuse: stale explicit VLM values (left over from a previous
        # standalone configuration) must be overridden, not just filled when
        # empty, or requests hit a mismatched endpoint/key pair. Keep the
        # stored value only when the text section has none (env-backed LLM).
        for field in ("base_url", "api_key", "model_name"):
            base["vlm"][field] = base["llm"].get(field, "") or base["vlm"].get(
                field,
                "",
            )

    # Decrypt secret fields when the QwenPaw secret store is available.
    _decrypt_secret_fields(base)

    try:
        return ModelConfigData.model_validate(base)
    except PydanticValidationError as exc:
        # A raw pydantic error would escape as an opaque 500 on every
        # model-config route; surface the offending field as a structured
        # 422 the UI can actually display.
        first_error = exc.errors()[0] if exc.errors() else {}
        loc = first_error.get("loc")
        field = ".".join(str(part) for part in loc) if loc else "unknown field"
        message = first_error.get("msg", str(exc))
        raise ValidationError(
            f"模型配置文件不可用: {field} {message}；"
            "请先备份并修正 model_config.json，再重新加载配置",
        ) from exc


def load_model_config(*, include_environment: bool = True) -> ModelConfigData:
    """Load persisted configuration, optionally adding legacy environment fallback.

    Runtime callers keep supporting deployments configured through ``.env``.  The
    settings API passes ``include_environment=False`` so the UI reports only what
    the user has actually saved to ``model_config.json``.
    """

    configs = _read_raw_config(_config_paths())
    return _assemble_model_config(
        configs,
        include_environment=include_environment,
    )


# ---------------------------------------------------------------------------
# Host Provider API Key Sync
# ---------------------------------------------------------------------------


def get_host_provider_api_key(provider_id: str) -> str | None:
    """Read a provider's API key from the QwenPaw encrypted store.

    Lookup order:
    1. builtin providers: ~/.qwenpaw.secret/providers/builtin/{provider_id}.json
    2. custom providers: ~/.qwenpaw.secret/providers/custom/{provider_id}.json

    Returns:
        str: the decrypted API key, or None when missing or undecryptable
    """
    if not QWENPAW_SECRET_AVAILABLE or QWENPAW_SECRET_DIR is None:
        logger.debug("QwenPaw secret store not available")
        return None

    # provider_id lands in a filesystem path; reject anything that could
    # escape the providers directory.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", provider_id):
        logger.warning(
            f"Rejected invalid provider id {_log_safe(provider_id)}",
        )
        return None

    for subdir in ["builtin", "custom"]:
        provider_file = (
            QWENPAW_SECRET_DIR / "providers" / subdir / f"{provider_id}.json"
        )
        if provider_file.exists():
            try:
                with open(provider_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    encrypted_key = data.get("api_key", "")
                    if not encrypted_key:
                        continue
                    # Decrypt values in the ENC: format.
                    if encrypted_key.startswith("ENC:"):
                        decrypted = qwenpaw_decrypt(encrypted_key)
                        # On failure decrypt returns the original value
                        # (still carrying the ENC: prefix).
                        if decrypted.startswith("ENC:"):
                            logger.warning(
                                "Failed to decrypt API key for provider "
                                f"{_log_safe(provider_id)}",
                            )
                            continue
                        return decrypted
                    # Plaintext value (legacy versions or test environments).
                    return encrypted_key
            except Exception as e:
                logger.warning(
                    f"Failed to read provider {_log_safe(provider_id)} "
                    f"from {_log_safe(provider_file)}: {e}",
                )
                continue

    return None


# Placeholder returned instead of persisted secrets; a submitted placeholder
# means "keep the stored value".
SECRET_MASK = "__CREATOR_SECRET__"
_SECRET_FIELDS = (
    "api_key",
    "access_key_secret",
    "policy_api_key",
    "tavily_api_key",
    "serper_api_key",
)


def _decrypt_secret_fields(data: dict) -> dict:
    """Decrypt the secret fields inside the config data."""
    if not (QWENPAW_SECRET_AVAILABLE and qwenpaw_decrypt is not None):
        return data

    for section_data in data.values():
        if not isinstance(section_data, dict):
            continue
        for field in _SECRET_FIELDS:
            value = section_data.get(field)
            if not (
                value
                and isinstance(value, str)
                and qwenpaw_is_encrypted(value)
            ):
                continue
            section_data[field] = qwenpaw_decrypt(value)
    return data


def _encrypt_secret_fields(data: dict) -> dict:
    """Encrypt the secret fields inside the config data."""
    if not (QWENPAW_SECRET_AVAILABLE and qwenpaw_encrypt is not None):
        return data

    for section_data in data.values():
        if not isinstance(section_data, dict):
            continue
        for field in _SECRET_FIELDS:
            value = section_data.get(field)
            if not (
                value
                and isinstance(value, str)
                and not qwenpaw_is_encrypted(value)
            ):
                continue
            section_data[field] = qwenpaw_encrypt(value)
    return data


def _mask_secrets(data: ModelConfigData) -> ModelConfigData:
    payload = data.model_dump()
    for section in payload.values():
        if not isinstance(section, dict):
            continue
        for field in _SECRET_FIELDS:
            if section.get(field):
                section[field] = SECRET_MASK
    return ModelConfigData.model_validate(payload)


def _resolve_secret_masks(
    data: ModelConfigData,
    persisted: ModelConfigData,
) -> ModelConfigData:
    payload = data.model_dump()
    stored = persisted.model_dump()
    for name, section in payload.items():
        if not isinstance(section, dict):
            continue
        for field in _SECRET_FIELDS:
            if section.get(field) == SECRET_MASK:
                section[field] = stored.get(name, {}).get(field, "")
    return ModelConfigData.model_validate(payload)


def save_model_config(data: ModelConfigData) -> None:
    mutate_model_config(lambda current: _resolve_secret_masks(data, current))


def mutate_model_config(
    mutator: Callable[[ModelConfigData], ModelConfigData],
) -> ModelConfigData:
    """Update global defaults without admitting or resuming Project work.

    Cache invalidation makes subsequent operations observe the new settings.
    Project wakes belong to explicit message/commit boundaries, never a
    settings save or an idempotent replay of that save.
    """

    config_path = _config_paths()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with CrossProcessFileLock(config_path.parent / ".model-config.lock"):
        persisted = _assemble_model_config(
            _load_json(config_path),
            include_environment=False,
        )
        updated = mutator(persisted)

        # Encrypt secret fields when the QwenPaw secret store is available.
        # The self-review env-override report is response-only state and
        # must never land in the persisted file.
        updated_dict = updated.model_dump(
            exclude={"self_review": {"env_overrides", "operator_status"}},
        )
        _encrypt_secret_fields(updated_dict)

        atomic_replace_bytes(
            config_path,
            canonical_json_bytes(updated_dict) + b"\n",
        )
        os.chmod(config_path, 0o600)
    _invalidate_raw_config_cache()
    model_config._clear_user_config_cache()
    return updated


def _model_config_complete(item: ModelConfigItem) -> bool:
    return bool(item.model_name and item.base_url and item.api_key)


def _grounding_validation_model(data: ModelConfigData) -> ModelConfigItem:
    source = data.grounding.validation_source
    if source == "llm":
        return data.llm
    if source == "vlm":
        return data.llm if data.vlm.use_llm else data.vlm
    return data.grounding


def _grounding_search_model(data: ModelConfigData) -> ModelConfigItem:
    grounding = data.grounding
    if grounding.search_reuse_llm:
        return data.llm
    return ModelConfigItem(
        enabled=grounding.native_search_enabled,
        model_name=grounding.search_model_name,
        api_key=grounding.search_api_key,
        base_url=grounding.search_base_url,
        protocol=grounding.search_protocol,
    )


def _supports_dashscope_native_search(item: ModelConfigItem) -> bool:
    protocol = item.protocol.casefold()
    host = urlparse(item.base_url).hostname or ""
    return (
        "dashscope" in protocol or "百炼" in item.protocol or "dashscope" in host
    )


def _grounding_config_inputs(data: ModelConfigData) -> tuple[dict, ...]:
    connection_fields = {
        "model_name",
        "api_key",
        "base_url",
        "protocol",
        "custom_protocol",
    }
    return (
        data.grounding.model_dump(),
        _grounding_validation_model(data).model_dump(
            include=connection_fields,
        ),
        _grounding_search_model(data).model_dump(include=connection_fields),
    )


def _ensure_grounding_model_configured(
    data: ModelConfigData,
    *,
    previous: ModelConfigData | None = None,
) -> None:
    # Legacy search settings must not prevent unrelated media-model repairs.
    # Compare resolved secrets and dependencies under the config write lock;
    # first-time setup and actual grounding edits still require validation.
    if previous is not None and (
        _grounding_config_inputs(data) == _grounding_config_inputs(previous)
    ):
        return
    grounding = data.grounding
    if not grounding.enabled:
        return
    verifier = _grounding_validation_model(data)
    if not _model_config_complete(verifier):
        source = {
            "llm": "LLM",
            "vlm": "VLM",
            "custom": "Grounding 验证模型",
        }[grounding.validation_source]
        # When VLM reuses the LLM config, the missing piece is actually the
        # LLM, not the VLM — say so to avoid confusing the user.
        if grounding.validation_source == "vlm" and data.vlm.use_llm:
            raise ValidationError(
                "Grounding 验证模型复用了 LLM 配置，但 LLM 尚未完整配置；"
                "请完整配置 LLM 的 Base URL、API Key 和模型名称，或关闭 Grounding",
            )
        raise ValidationError(
            f"Grounding 默认启用；请完整配置 {source} 的 Base URL、API Key 和模型名称，或关闭 Grounding",
        )
    if grounding.tavily_api_key or grounding.serper_api_key:
        return
    search_model = _grounding_search_model(data)
    if not grounding.native_search_enabled:
        raise ValidationError(
            "Grounding 搜索未配置；请配置 Tavily/Serper，或启用 Qwen/DashScope 原生搜索",
        )
    if not _model_config_complete(search_model):
        raise ValidationError(
            "Grounding 搜索未配置；请配置 Tavily/Serper，或完整配置 Qwen/DashScope 搜索模型",
        )
    if not _supports_dashscope_native_search(search_model):
        raise ValidationError(
            "当前搜索模型不支持 Qwen/DashScope 原生 web_search；请配置 Tavily/Serper，或选择 DashScope（百炼）搜索模型",
        )


def _image_backend_for_protocol(protocol: str) -> str:
    """Map the persisted image protocol label onto a provider switch.

    Delegates to :func:`models.image.image_backend_for_protocol`, the
    same single source the persisted fallback uses, mirroring how
    ``_video_backend_for_protocol`` defers to ``models.config``. The
    inline copy kept here is what let MiniMax ship mapped in the
    connection probe and in the lowest-priority fallback while this --
    the writer behind the highest-priority input -- still returned
    nothing, so an ``IMAGE_MODEL`` env var sent a MiniMax key and model
    to OpenAI's ``/v1/images/generations`` and generation failed even
    though the connection test had passed.
    """

    from models.image import image_backend_for_protocol

    return image_backend_for_protocol(protocol) or ""


def _video_backend_for_protocol(protocol: str) -> str:
    """Map the persisted video protocol label onto a transport backend.

    Delegates to the shared mapping in ``models.config`` so the
    request-scoped value and every fallback resolve the channel from the
    same user configuration rule (Bailian hosting vs official Kling/Vidu
    channels, Volcano Engine, Google Gemini, MiniMax).
    """

    return model_config.video_backend_for_protocol(protocol) or "wan"


def request_tool_configs() -> dict[str, dict[str, Any]]:
    data = load_model_config()
    configs: dict[str, dict[str, Any]] = {}
    mapping = {
        "llm": model_config.CREATOR_TEXT_CONFIG_TOOL,
        "vlm": model_config.CREATOR_VLM_CONFIG_TOOL,
        "asr": model_config.CREATOR_ASR_CONFIG_TOOL,
        "embedding": model_config.CREATOR_EMBEDDING_CONFIG_TOOL,
        "image": model_config.CREATOR_IMAGE_CONFIG_TOOL,
        "video": model_config.CREATOR_VIDEO_CONFIG_TOOL,
    }
    for section, tool_name in mapping.items():
        item = getattr(data, section)
        if not item.enabled or not item.model_name:
            continue
        tool_config: dict[str, Any] = {
            "api_key": item.api_key,
            "model": item.model_name,
            "base_url": item.base_url,
            "protocol": item.protocol,
        }
        if section == "asr":
            tool_config.update(
                {
                    "provider": item.provider,
                    "language": item.language,
                    "reuse_llm_key": item.reuse_llm_key,
                },
            )
        if section == "tts":
            tool_config.update(
                {
                    "voice": item.voice,
                    "vc_model_name": item.vc_model_name,
                    "reuse_llm_key": item.reuse_llm_key,
                },
            )
        if section == "image":
            image_backend = _image_backend_for_protocol(item.protocol)
            if image_backend:
                tool_config["_image_backend"] = image_backend
        if section == "image" and item.translate_model:
            tool_config["translate_model"] = item.translate_model
        if section == "video":
            tool_config["_video_backend"] = _video_backend_for_protocol(
                item.protocol,
            )
        configs[tool_name] = tool_config
    grounding = data.grounding
    configs[model_config.CREATOR_GROUNDING_CONFIG_TOOL] = {
        "enabled": grounding.enabled,
        "tavily_api_key": grounding.tavily_api_key,
        "serper_api_key": grounding.serper_api_key,
        "reuse_llm": grounding.reuse_llm,
        "validation_source": grounding.validation_source,
        "api_key": grounding.api_key,
        "model": grounding.model_name,
        "base_url": grounding.base_url,
        "protocol": grounding.protocol,
        "native_search_enabled": grounding.native_search_enabled,
        "search_provider": grounding.search_provider,
        "search_reuse_llm": grounding.search_reuse_llm,
        "search_api_key": grounding.search_api_key,
        "search_model": grounding.search_model_name,
        "search_base_url": grounding.search_base_url,
        "search_protocol": (
            data.llm.protocol
            if grounding.search_reuse_llm
            else grounding.search_protocol
        ),
    }
    return configs


def _qwenpaw_tool_configs(request: Request) -> dict[str, dict[str, Any]]:
    agent_id = request.headers.get("X-Agent-Id") or getattr(
        request.state,
        "agent_id",
        None,
    )
    if not agent_id:
        try:
            from qwenpaw.app.agent_context import get_current_agent_id

            agent_id = get_current_agent_id()
        except (ImportError, RuntimeError):
            return {}
    try:
        from qwenpaw.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        return {
            name: value
            for name in model_config.CREATOR_CONFIG_TOOLS
            if (value := registry.get_tool_config(name, agent_id))
        }
    except (ImportError, AttributeError, RuntimeError):
        return {}


async def bind_creator_tool_config(request: Request):
    """Bind host config first, then fill only absent fields from external local config.

    ``request_tool_configs()`` stats and, on cache miss, lock-reads the config
    file, so the complete resolution runs off the event loop.
    """

    configs = _qwenpaw_tool_configs(request)
    grounding_host = configs.get(model_config.CREATOR_GROUNDING_CONFIG_TOOL)
    if (
        isinstance(grounding_host, dict)
        and "reuse_llm" in grounding_host
        and not grounding_host.get("validation_source")
    ):
        # Older host portals only expose the legacy reuse_llm switch. The
        # local config always carries validation_source, which the runtime
        # getters prefer — without this migration the merge would silently
        # override the portal's "don't reuse the LLM" choice.
        grounding_host["validation_source"] = validation_source_from_reuse_llm(
            str(grounding_host["reuse_llm"]).strip().casefold()
            not in {"0", "false", "no", "off"},
        )
    local_configs = await asyncio.to_thread(request_tool_configs)
    for tool_name, local in local_configs.items():
        merged = dict(local)
        merged.update(configs.get(tool_name) or {})
        configs[tool_name] = merged
    token = model_config.set_request_tool_configs(configs)
    try:
        yield
    finally:
        model_config.reset_request_tool_configs(token)


async def _validate_section_connectivity(
    section: str,
    config: dict[str, Any],
) -> None:
    """Run connectivity probe for a single section. Raises ValidationError on failure."""

    if section in ("execution_authorization", "executionAuthorization"):
        return
    if section == "grounding":
        return

    if section == "oss":
        oss = config.get("oss", {})
        if (
            not oss.get("enabled")
            or not oss.get("endpoint")
            or not oss.get("access_key_id")
            or not oss.get("access_key_secret")
            or not oss.get("bucket")
        ):
            return
        try:
            import oss2

            def probe() -> None:
                auth = oss2.Auth(
                    oss["access_key_id"],
                    oss["access_key_secret"],
                )
                bucket = oss2.Bucket(auth, oss["endpoint"], oss["bucket"])
                bucket.get_bucket_info()

            await asyncio.to_thread(probe)
        except Exception as exc:
            exc_str = str(exc)
            if "InvalidAccessKeyId" in exc_str or "AccessDenied" in exc_str:
                raise ValidationError(
                    "OSS: Access Key 无效或权限不足，请检查配置",
                )
            if "NoSuchBucket" in exc_str:
                raise ValidationError("OSS: Bucket 不存在，请检查 Bucket 名称")
            if "connect" in exc_str.lower() or "timeout" in exc_str.lower():
                raise ValidationError(
                    "OSS: 无法连接到 OSS 服务，请检查 Endpoint 和网络",
                )
            raise ValidationError(f"OSS: {exc_str}")
        return

    item = config.get(section, {})
    if not item.get("enabled") or not item.get("model_name"):
        return

    api_key = item.get("api_key", "")
    if (
        section in ("asr", "tts", "s2v", "image", "video")
        and item.get("reuse_llm_key")
        and not api_key
    ):
        api_key = config.get("llm", {}).get("api_key", "")
    if section == "embedding" and item.get("reuse_vlm_key") and not api_key:
        api_key = config.get("vlm", {}).get("api_key", "") or config.get(
            "llm",
            {},
        ).get("api_key", "")
    # Self-hosted SGLang video serves without authentication unless
    # started with --api-key, so an empty key is a valid configuration.
    key_optional = (
        section == "video"
        and model_config.video_backend_for_protocol(
            str(item.get("protocol") or ""),
        )
        == "minimax_sglang"
    )
    if not item.get("base_url") or (not api_key and not key_optional):
        raise ValidationError(
            f"{section}: 缺少 Base URL 或 API Key，请检查配置",
        )

    probe = ModelConnectionTestRequest(
        type=section,
        base_url=item["base_url"],
        api_key=api_key,
        model_name=item["model_name"],
        protocol=item.get("protocol", ""),
        provider=item.get("provider"),
    )

    async with httpx.AsyncClient(
        timeout=30,
        # A probe must reach the configured endpoint, not wherever it is
        # waved on to: following a redirect would let a public host bounce
        # the bearer credential into the internal network.
        follow_redirects=False,
    ) as client:
        try:
            probe_request = await _prepare_probe_payload(probe)
            resp = await _send_probe(client, *probe_request)
            if not resp.is_success:
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        err_obj = body.get("error")
                        msg = (
                            err_obj.get("message")
                            if isinstance(err_obj, dict)
                            else body.get("message")
                            or body.get("error")
                            or str(body)
                        )
                    else:
                        msg = str(body)
                except ValueError:
                    msg = resp.text[:200]
                raise ValidationError(
                    f"{section}: HTTP {resp.status_code}: {msg or '请求失败'}",
                )
        except httpx.ConnectError:
            raise ValidationError(
                f"{section}: 无法连接到服务，请检查 Base URL 是否正确",
            )
        except httpx.TimeoutException:
            raise ValidationError(
                f"{section}: 连接超时，请检查网络或 Base URL",
            )
        except httpx.HTTPError as exc:
            raise ValidationError(f"{section}: {exc}")
        except RuntimeError as exc:
            # The ASR probe uploads its silent sample before it can ask
            # anything, and the uploader reports a refused credential or a
            # malformed policy as a RuntimeError. That is a connection
            # finding about this section, not a fault of the config route.
            raise ValidationError(f"{section}: {exc}")


@router.get("/config", response_model=ModelConfigData)
async def get_model_config() -> ModelConfigData:
    loaded = await asyncio.to_thread(
        load_model_config,
        include_environment=False,
    )
    # Read-only override report: tiers whose settings-center toggles are
    # currently shadowed by explicit CREATOR_*_REVIEW_ENABLED env vars.
    # The UI badges them so the precedence is visible instead of a ghost
    # (field incident: review ran with the UI toggled off).
    from models.config import forced_review_env_overrides

    env_to_tier = {
        "CREATOR_SYNC_REVIEW_ENABLED": "sync_enabled",
        "CREATOR_MEDIA_REVIEW_ENABLED": "media_enabled",
        "CREATOR_SELF_REVIEW_ENABLED": "render_enabled",
    }
    loaded.self_review.env_overrides = {
        env_to_tier[name]: value
        for name, value in forced_review_env_overrides().items()
        if name in env_to_tier
    }
    # Advanced per-operator resolution (user/auto + dependency probe);
    # response-only, mirrors the env-override report above.
    from services.run_review.operator_registry import operator_status_report

    loaded.self_review.operator_status = operator_status_report()
    return _mask_secrets(loaded)


# Semantic diagnostic read: this performs no Creator/runtime/config mutation,
# so it is intentionally outside the mutating-route idempotency registry.
@router.get("/resolved")
async def get_resolved_models() -> dict[str, Any]:
    """Return the runtime-resolved model identity execution actually uses.

    Unlike ``/models/config`` (persisted-only), this reflects request-scoped
    host tool config, environment overrides and defaults — i.e. the value
    ``get_video_model_name()`` returns at submission time.  ``byMode``
    carries the per-mode derived names (a configured ``wan2.7-r2v`` submits
    as ``wan2.7-t2v`` for a t2v element), and ``s2v`` names the digital-human
    model, so mode workbenches can show the model their element will bill
    against.  Read-only.
    """
    from models.video_capabilities import video_model_capability_payload

    video_model = model_config.get_video_model_name()
    protocol_backend = model_config.get_video_backend()
    capability = video_model_capability_payload(
        video_model,
        protocol_backend,
    )
    return {
        "video": {
            "provider": capability["provider"],
            "model": video_model,
            "known": capability["known"],
            "supportedModes": capability["supportedModes"],
            "byMode": capability["effectiveModels"],
        },
        "s2v": {
            "model": model_config.get_s2v_model_name(),
        },
    }


@router.get("/video-capabilities")
async def get_video_capabilities(
    model_name: str = Query(default="", alias="modelName"),
    protocol: str = Query(default=""),
) -> dict[str, object]:
    """Exact, documented generation modes for one video selection.

    The settings UI calls this before saving, so query values take priority;
    omitted values resolve to the active runtime configuration.  This route is
    read-only and never probes or bills an upstream provider.
    """

    from models.video_capabilities import video_model_capability_payload

    selected_model = model_name.strip() or model_config.get_video_model_name()
    selected_backend = (
        model_config.video_backend_for_protocol(protocol)
        if protocol.strip()
        else model_config.get_video_backend()
    )
    return video_model_capability_payload(
        selected_model,
        selected_backend or "",
    )


@router.get("/tts-capabilities")
async def get_tts_capabilities() -> dict[str, Any]:
    """Speech models this build supports, and what each of them can do.

    The UI renders its model choices from this list so the two never disagree
    about which models exist, which have system voices, and which companion
    models a created voice binds to (users never name those).
    """

    from models.tts_capabilities import DEFAULT_TTS_MODEL, supported_models

    return {
        "default": DEFAULT_TTS_MODEL,
        "models": [
            {
                "model": item.model,
                "label": item.label,
                "family": item.family,
                "transport": item.transport,
                "systemVoices": list(item.system_voices),
                "supportsDesign": item.supports_design,
            }
            for item in supported_models()
        ],
    }


@router.post("/config")
async def update_model_config(
    data: ModelConfigData,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, bool]:
    key = resolve_idempotency_key(idempotency_key)
    root = require_creator_data_root() / "config" / "runtime" / "idempotency"
    records = IdempotencyRecordStore(root)
    payload = data.model_dump(mode="json", by_alias=True)
    request_hash = records.request_hash(payload)

    def mutate(current: ModelConfigData) -> ModelConfigData:
        resolved = _resolve_secret_masks(data, current)
        resolved.llm.enabled = True
        _ensure_grounding_model_configured(
            resolved,
            previous=current if _config_paths().is_file() else None,
        )
        return resolved

    def transaction() -> bool:
        with records.operation_lock(
            owner_id="creator-model-config",
            scope="HTTP:model-config-update",
            idempotency_key=key,
        ):
            reservation = records.reserve(
                owner_id="creator-model-config",
                scope="HTTP:model-config-update",
                idempotency_key=key,
                request_hash=request_hash,
            )
            if reservation.record.status is IdempotencyStatus.COMPLETED:
                return True
            if reservation.record.status is IdempotencyStatus.FAILED:
                raise StorageIntegrityError(
                    "上一次模型配置写入失败，请使用新的 Idempotency-Key 重试",
                )
            mutate_model_config(mutate)
            records.complete(
                owner_id="creator-model-config",
                scope="HTTP:model-config-update",
                idempotency_key=key,
                request_hash=request_hash,
                response={"ok": True},
                response_status=status.HTTP_200_OK,
            )
            return False

    try:
        replayed = await asyncio.to_thread(transaction)
    except IdempotencyConflictError as error:
        raise ConflictError("Idempotency-Key 已用于不同的模型配置") from error
    except IdempotencyStateConflictError as error:
        raise ConflictError("模型配置写入状态冲突") from error
    response.headers["X-Idempotent-Replay"] = "true" if replayed else "false"
    return {"ok": True}


@router.patch("/config/creation-checkpoints")
async def patch_creation_checkpoints(
    data: dict[str, Any] = Body(...),
) -> dict[str, bool]:
    mode = data.get("mode")
    if mode not in ("required", "skip"):
        raise ValidationError("mode 必须是 'required' 或 'skip'")
    execution_mode = data.get("execution_mode", "co_creation")
    if execution_mode not in ("delegated", "co_creation", "fine_tuning"):
        raise ValidationError(
            "execution_mode 必须是 'delegated'、'co_creation' 或 'fine_tuning'",
        )

    def mutate(current: ModelConfigData) -> ModelConfigData:
        merged = current.model_dump()
        merged["creation_checkpoints"] = {
            "mode": mode,
            "execution_mode": execution_mode,
        }
        try:
            return ModelConfigData.model_validate(merged)
        except PydanticValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            message = first_error.get("msg", str(exc))
            raise ValidationError(
                f"模型配置校验失败: {field} {message}",
            ) from exc

    await asyncio.to_thread(mutate_model_config, mutate)
    return {"ok": True}


@router.patch("/config/permission-mode")
async def patch_permission_mode(
    data: dict[str, Any] = Body(...),
) -> dict[str, bool]:
    """Atomically persist one stop of the permission ladder.

    The slider writes three coupled fields; saving them through separate
    PATCH calls can strand the server in a mixed state when one call
    fails (worst case: a stale media_review=auto_approve hiding behind a
    conservative-looking UI). One mutate transaction removes the class.
    """

    execution = data.get("execution_authorization")
    checkpoints = data.get("creation_checkpoints")
    media_review = data.get("media_review")
    if execution not in ("required", "allow_all"):
        raise ValidationError(
            "execution_authorization 必须是 'required' 或 'allow_all'",
        )
    if checkpoints not in ("required", "skip"):
        raise ValidationError(
            "creation_checkpoints 必须是 'required' 或 'skip'",
        )
    if media_review not in ("required", "auto_approve"):
        raise ValidationError(
            "media_review 必须是 'required' 或 'auto_approve'",
        )

    def mutate(current: ModelConfigData) -> ModelConfigData:
        merged = current.model_dump()
        merged["execution_authorization"] = {"mode": execution}
        # The permission ladder owns only the gate on/off; the governance
        # execution_mode survives the write (skip already forces
        # delegated at read time).
        merged["creation_checkpoints"] = {
            "mode": checkpoints,
            "execution_mode": merged.get("creation_checkpoints", {}).get(
                "execution_mode",
                "co_creation",
            ),
        }
        merged["media_review"] = {"mode": media_review}
        try:
            return ModelConfigData.model_validate(merged)
        except PydanticValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            message = first_error.get("msg", str(exc))
            raise ValidationError(
                f"模型配置校验失败: {field} {message}",
            ) from exc

    await asyncio.to_thread(mutate_model_config, mutate)
    return {"ok": True}


@router.patch("/config/media-review")
async def patch_media_review(
    data: dict[str, Any] = Body(...),
) -> dict[str, bool]:
    mode = data.get("mode")
    if mode not in ("required", "auto_approve"):
        raise ValidationError("mode 必须是 'required' 或 'auto_approve'")

    def mutate(current: ModelConfigData) -> ModelConfigData:
        merged = current.model_dump()
        merged["media_review"] = {"mode": mode}
        try:
            return ModelConfigData.model_validate(merged)
        except PydanticValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            message = first_error.get("msg", str(exc))
            raise ValidationError(
                f"模型配置校验失败: {field} {message}",
            ) from exc

    await asyncio.to_thread(mutate_model_config, mutate)
    return {"ok": True}


@router.patch("/config/execution-authorization")
async def patch_execution_authorization(
    data: dict[str, Any] = Body(...),
) -> dict[str, bool]:
    mode = data.get("mode")
    if mode not in ("required", "allow_all"):
        raise ValidationError("mode 必须是 'required' 或 'allow_all'")

    def mutate(current: ModelConfigData) -> ModelConfigData:
        merged = current.model_dump()
        merged["execution_authorization"] = {"mode": mode}
        try:
            return ModelConfigData.model_validate(merged)
        except PydanticValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            message = first_error.get("msg", str(exc))
            raise ValidationError(
                f"模型配置校验失败: {field} {message}",
            ) from exc

    await asyncio.to_thread(mutate_model_config, mutate)
    return {"ok": True}


@router.patch("/config/self-review")
async def patch_self_review(
    data: dict[str, Any] = Body(...),
) -> dict[str, bool]:
    """Persist the advisory self-review tiers in one write.

    Accepts any subset of ``sync_enabled`` / ``media_enabled`` /
    ``render_enabled`` booleans and merges them into the ``self_review``
    section, so toggling one tier never clobbers the others. Explicitly
    set ``CREATOR_*_REVIEW_ENABLED`` environment switches still override
    the persisted values at runtime (see ``models.config``).
    """

    tier_keys = ("sync_enabled", "media_enabled", "render_enabled")
    updates: dict[str, bool] = {}
    for tier in tier_keys:
        if tier not in data:
            continue
        value = data[tier]
        if not isinstance(value, bool):
            raise ValidationError(f"{tier} 必须是布尔值")
        updates[tier] = value
    operator_updates: dict[str, bool | None] | None = None
    if "operators" in data:
        raw_operators = data["operators"]
        if not isinstance(raw_operators, dict):
            raise ValidationError("operators 必须是对象")
        from services.run_review.operator_registry import operator_keys

        known = set(operator_keys())
        unknown_ops = set(raw_operators) - known
        if unknown_ops:
            raise ValidationError(
                f"不支持的算子: {', '.join(sorted(unknown_ops))}",
            )
        operator_updates = {}
        for key, value in raw_operators.items():
            # ``null`` restores the auto (能开尽开) resolution for one
            # operator; booleans persist an explicit user choice.
            if value is not None and not isinstance(value, bool):
                raise ValidationError(f"operators.{key} 必须是布尔值或 null")
            operator_updates[key] = value
    unknown = set(data) - set(tier_keys) - {"operators"}
    if unknown:
        raise ValidationError(f"不支持的字段: {', '.join(sorted(unknown))}")
    if not updates and operator_updates is None:
        raise ValidationError(
            "至少提供 sync_enabled / media_enabled / render_enabled / "
            "operators 之一",
        )

    def mutate(current: ModelConfigData) -> ModelConfigData:
        merged = current.model_dump()
        section = dict(merged.get("self_review") or {})
        section.update(updates)
        if operator_updates is not None:
            operators = dict(section.get("operators") or {})
            for key, value in operator_updates.items():
                if value is None:
                    operators.pop(key, None)
                else:
                    operators[key] = value
            section["operators"] = operators
        # Response-only state: the env-override / operator-status reports
        # must never land in the persisted config file.
        section.pop("env_overrides", None)
        section.pop("operator_status", None)
        merged["self_review"] = section
        try:
            return ModelConfigData.model_validate(merged)
        except PydanticValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            message = first_error.get("msg", str(exc))
            raise ValidationError(
                f"模型配置校验失败: {field} {message}",
            ) from exc

    await asyncio.to_thread(mutate_model_config, mutate)
    return {"ok": True}


@router.patch("/config/{section}")
async def patch_model_config_section(
    section: str,
    data: dict[str, Any] = Body(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, bool]:
    valid_sections = {
        "llm",
        "vlm",
        "grounding",
        "asr",
        "embedding",
        "image",
        "video",
        "oss",
    }
    if section not in valid_sections:
        raise ValidationError(f"不支持的配置项: {section}")

    key = resolve_idempotency_key(idempotency_key)
    root = require_creator_data_root() / "config" / "runtime" / "idempotency"
    records = IdempotencyRecordStore(root)
    request_hash = records.request_hash({"section": section, **data})

    def mutate(current: ModelConfigData) -> ModelConfigData:
        merged = current.model_dump()
        merged[section] = {**merged.get(section, {}), **data}
        if section == "llm":
            merged["llm"]["enabled"] = True
        try:
            resolved = _resolve_secret_masks(
                ModelConfigData.model_validate(merged),
                current,
            )
        except PydanticValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            message = first_error.get("msg", str(exc))
            raise ValidationError(
                f"模型配置校验失败: {field} {message}",
            ) from exc
        _ensure_grounding_model_configured(
            resolved,
            previous=current if _config_paths().is_file() else None,
        )
        return resolved

    def transaction() -> None:
        with records.operation_lock(
            owner_id="creator-model-config",
            scope="HTTP:model-config-patch",
            idempotency_key=key,
        ):
            reservation = records.reserve(
                owner_id="creator-model-config",
                scope="HTTP:model-config-patch",
                idempotency_key=key,
                request_hash=request_hash,
            )
            if reservation.record.status is IdempotencyStatus.COMPLETED:
                return
            if reservation.record.status is IdempotencyStatus.FAILED:
                raise StorageIntegrityError(
                    "上一次模型配置写入失败，请使用新的 Idempotency-Key 重试",
                )
            mutate_model_config(mutate)
            records.complete(
                owner_id="creator-model-config",
                scope="HTTP:model-config-patch",
                idempotency_key=key,
                request_hash=request_hash,
                response={"ok": True},
                response_status=status.HTTP_200_OK,
            )

    try:
        await asyncio.to_thread(transaction)
    except IdempotencyConflictError as error:
        raise ConflictError("Idempotency-Key 已用于不同的模型配置") from error
    except IdempotencyStateConflictError as error:
        raise ConflictError("模型配置写入状态冲突") from error
    return {"ok": True}


def _dashscope_policy_probe(
    body: ModelConnectionTestRequest,
    headers: dict[str, str],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Zero-cost DashScope probe via the model-bound upload-policy API.

    ``GET /api/v1/uploads?action=getPolicy&model=...`` verifies the
    endpoint, the API key and the model binding without submitting a
    billable task (task-submission pings are rejected with HTTP 403
    "current user api does not support asynchronous calls").
    """
    parsed = urlparse(body.base_url)
    return (
        f"{parsed.scheme}://{parsed.netloc}/api/v1/uploads",
        headers,
        {"_get_probe": True, "action": "getPolicy", "model": body.model_name},
    )


def _dashscope_video_task_probe(
    body: ModelConnectionTestRequest,
    headers: dict[str, str],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Validate a DashScope video endpoint with a zero-cost task lookup.

    The task endpoint is shared by Bailian's video models on both legacy and
    Workspace API roots.  Unlike the temporary-upload policy endpoint, this
    checks the configured host itself without creating a billable task.
    """

    base = body.base_url.rstrip("/")
    submit_suffix = "/services/aigc/video-generation/video-synthesis"
    api_root = (
        base[: -len(submit_suffix)] if base.endswith(submit_suffix) else base
    )
    # A syntactically valid but nonexistent task ID produces the documented
    # UNKNOWN status without creating or billing a generation task.
    task_id = "11111111-1111-4111-8111-111111111111"
    return f"{api_root}/tasks/{task_id}", headers, {"_get_probe": True}


def _openai_model_probe(
    body: ModelConnectionTestRequest,
    headers: dict[str, str],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Zero-cost OpenAI-compatible probe via the model-retrieve API."""
    base = body.base_url.rstrip("/")
    return (
        f"{base}/models/{body.model_name}",
        headers,
        {"_get_probe": True},
    )


def _minimax_image_probe(
    body: ModelConnectionTestRequest,
    headers: dict[str, str],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Zero-cost MiniMax image probe.

    MiniMax has no model-retrieve ``GET /models/{id}``; the OpenAI-style
    fall-through would hit a non-existent path and surface an nginx HTML 404.
    The task-query endpoint is free, reachable with the same Bearer key on the
    same host, and answers with a MiniMax JSON envelope instead of raw HTML.
    """
    base = body.base_url.rstrip("/")
    return (
        f"{base}/v1/query/video_generation",
        headers,
        {
            "_get_probe": True,
            "task_id": "creator-connection-probe",
        },
    )


def _minimax_base_resp_error(response: httpx.Response) -> str | None:
    """Message when a MiniMax 2xx probe body carries a non-zero ``base_resp``.

    The code table and formatting live in :mod:`models.minimax_errors` so the
    probe and the real image/video generation paths share one definition.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    return minimax_probe_base_resp_error(body)


def _token_plan_models_probe(
    body: ModelConnectionTestRequest,
    headers: dict[str, str],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Token Plan probe: list models endpoint (zero-cost, validates API key).

    Token Plan uses /api/v1 as base_url but the models endpoint is at
    /compatible-mode/v1/models. This probe verifies the API key and base
    URL without submitting any billable generation task.
    """
    parsed = urlparse(body.base_url)
    url = f"{parsed.scheme}://{parsed.netloc}/compatible-mode/v1/models"
    return url, headers, {"_get_probe": True}


def _anthropic_llm_probe(
    body: ModelConnectionTestRequest,
    base: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Anthropic Messages API probe for llm/vlm connectivity tests."""
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    # Free-tier providers probe with require_api_key=False and an empty
    # key; sending an empty x-api-key would fail with 401 instead of
    # letting the unauthenticated probe proceed.
    if body.api_key:
        headers["x-api-key"] = body.api_key
    if body.type == "vlm":
        content: list[dict[str, Any]] = [
            {"type": "text", "text": "Reply with red only."},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGO4I2JDEmIY1TCqYfhqAAAeBCwQ8YdREQAAAABJRU5ErkJggg==",
                },
            },
        ]
    else:
        content = "Reply with pong only."
    return (
        f"{base}/v1/messages",
        headers,
        {
            "_attests": _ATTEST_HANDLED,
            "model": body.model_name,
            "messages": [{"role": "user", "content": content}],
        },
    )


def _gemini_llm_probe(
    body: ModelConnectionTestRequest,
    base: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Google Gemini Generative AI probe for llm/vlm connectivity tests.

    Gemini authenticates through the ``key=`` query parameter (the same
    transport used by ``text_model._call_gemini``); without it the probe
    always fails with 400/401/403.
    """
    url = f"{base}/v1beta/models/{body.model_name}:generateContent"
    if body.api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={body.api_key}"
    headers = {
        "Content-Type": "application/json",
    }
    if body.type == "vlm":
        parts: list[dict[str, Any]] = [
            {"text": "Reply with red only."},
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGO4I2JDEmIY1TCqYfhqAAAeBCwQ8YdREQAAAABJRU5ErkJggg==",
                },
            },
        ]
    else:
        parts = [{"text": "Reply with pong only."}]
    payload: dict[str, Any] = {
        "_attests": _ATTEST_HANDLED,
        "contents": [{"parts": parts}],
    }
    return url, headers, payload


# One second of silence exercises a transcription route for a fraction of a
# cent. It is built in-process rather than shelled out to ffmpeg so the probe
# also works in a container that has no ffmpeg installed.
_ASR_PROBE_SAMPLE_SECONDS = 1.0
_ASR_PROBE_SAMPLE_RATE = 16_000


def _silent_wav_bytes() -> bytes:
    """A silent mono 16 kHz WAV payload for the ASR capability probe.

    Silence transcribes to an empty string, so this asserts that the route
    accepts and processes real audio, not that any words came back.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_ASR_PROBE_SAMPLE_RATE)
        frames = int(_ASR_PROBE_SAMPLE_RATE * _ASR_PROBE_SAMPLE_SECONDS)
        handle.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def _asr_provider(body: ModelConnectionTestRequest) -> str:
    """Which route ``asr_model.transcribe`` will actually take.

    Mirrors that dispatch exactly: the stored provider decides whisper,
    then a ``qwen3-asr*`` model name, then Fun-ASR. ``protocol`` is
    deliberately not consulted, because ``get_asr_provider()`` does not
    read it either: a config whose protocol says Whisper while its
    provider says Fun-ASR runs the Fun-ASR route, and probing the whisper
    one would green-light an endpoint production never calls. Probing a
    different route than the one production runs is how a dead endpoint
    stayed green, and the previous probe never produced ``qwen3-asr`` at
    all — a qwen3-asr config was validated against the Fun-ASR
    upload-policy call.
    """
    if (body.provider or "").casefold() == "whisper":
        return "whisper"
    if (body.model_name or "").casefold().startswith("qwen3-asr"):
        return "qwen3-asr"
    return "fun-asr"


async def _upload_asr_probe_sample(
    body: ModelConnectionTestRequest,
) -> str:
    """Upload the silent sample; return the URL the ASR route will fetch.

    Uses the same model-bound temporary OSS upload production uses, so a
    probe that passes has exercised the upload half of the real chain too,
    and one that fails has failed for a reason production would also hit.
    """
    from models.media_transport import upload_local_file_to_dashscope_temp

    with tempfile.TemporaryDirectory(prefix="creator-asr-probe-") as raw:
        sample = Path(raw) / "creator-probe.wav"
        await asyncio.to_thread(sample.write_bytes, _silent_wav_bytes())
        return await upload_local_file_to_dashscope_temp(
            sample,
            api_key=body.api_key,
            model_name=body.model_name,
            media_type="audio/wav",
        )


async def _asr_probe(
    body: ModelConnectionTestRequest,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Transcribe one second of silence through the production ASR route.

    ASR was the only tier whose connection test measured something other
    than what it green-lit: ``GET /models/{id}`` proves the key and the
    registry entry, and the DashScope upload-policy call proves neither, so a
    platform answering 500 on ``audio/transcriptions``, 404 on
    ``asr/transcription`` and 502 on ``multimodal-generation`` still showed a
    green test while every real transcription failed. llm/vlm, tts and
    embedding already pay for a real request; this brings ASR in line.
    """
    # Route derivation is imported rather than restated so the probe cannot
    # drift from the endpoints production actually calls.
    from models.asr_model import (
        _FUN_ASR_TRANSCRIPTION_SUFFIX,
        _fun_asr_base,
        _qwen3_endpoint,
    )

    headers = _probe_headers(body)
    provider = _asr_provider(body)
    if provider == "whisper":
        # Same multipart shape as asr_model._whisper. Content-Type stays in
        # the returned headers for _send_probe to drop, as with _get_probe.
        base = body.base_url.rstrip("/")
        return (
            f"{base}/audio/transcriptions",
            headers,
            {
                "_attests": _ATTEST_ASR_WHISPER,
                "_multipart_probe": {
                    "data": {
                        "model": body.model_name,
                        "response_format": "verbose_json",
                    },
                    "files": {
                        "file": (
                            "creator-probe.wav",
                            _silent_wav_bytes(),
                            "audio/wav",
                        ),
                    },
                },
            },
        )
    # Staging the sample is a network side effect of its own: it posts the
    # configured bearer to the provider's upload API. So the destination
    # policy runs on the endpoint this probe is about to test BEFORE the
    # first packet leaves, not only inside ``_send_probe`` — a Base URL that
    # points at the metadata service has to fail without uploading anything.
    if provider == "qwen3-asr":
        url = _qwen3_endpoint(body.base_url)
    else:
        url = (
            f"{_fun_asr_base(body.base_url)}"
            f"/{_FUN_ASR_TRANSCRIPTION_SUFFIX}"
        )
    _assert_probe_destination(url)
    file_url = await _upload_asr_probe_sample(body)
    if provider == "qwen3-asr":
        return (
            url,
            {**headers, "X-DashScope-OssResourceResolve": "enable"},
            {
                "_attests": _ATTEST_ASR_QWEN3,
                "model": body.model_name,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"audio": file_url}],
                        },
                    ],
                },
                "parameters": {"result_format": "message"},
            },
        )
    # Fun-ASR: the real async submit, with the headers production sends —
    # omitting X-DashScope-Async is what made an earlier attempt at this
    # probe come back 403 "does not support asynchronous calls". The probe
    # deliberately does not poll the task, because a UI button needs bounded
    # latency, so what it can assert is that the transcription route exists,
    # accepts the key and took the work — not that a transcript will appear.
    return (
        url,
        {
            **headers,
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        },
        {
            "_attests": _ATTEST_ASR_FUN,
            "model": body.model_name,
            "input": {"file_urls": [file_url]},
            "parameters": {},
        },
    )


def _operator_written_base_url(section: str) -> str:
    """Return a section's Base URL only when the operator actually wrote one.

    ``load_model_config()`` starts from ``_defaults()``, which pre-fills the
    DashScope address for ASR and Embedding and turns their key-reuse switches
    on. A non-empty ``base_url`` on a section nobody configured is therefore a
    product default, not proof that the operator authorised a stored credential
    for that host. Reading defaults as authorization would let any client of
    ``/models/test`` make the server send a key saved for another provider to
    the built-in endpoint, so only values written to ``model_config.json`` or
    the environment are treated as explicit.
    """
    try:
        raw = _read_raw_config(_config_paths()).get(section)
    except (CreatorDataRootError, ValidationError, OSError, TimeoutError):
        # A config we cannot read proves no authorization: refuse through the
        # empty-home path rather than inventing a trusted host or turning the
        # connection test into an unhandled error.
        return ""
    value = (
        str(raw.get("base_url") or "").strip() if isinstance(raw, dict) else ""
    )
    if not value:
        for name in _ENV_MAPPING.get(section, {}).get("base_url", ()):
            if os.environ.get(name):
                value = os.environ[name].strip()
                break
    return value


def _credential_owner_section(loaded: ModelConfigData, section: str) -> str:
    """Return the section that really owns the credential ``section`` sends.

    ``_assemble_model_config`` copies values, not provenance: a VLM saved with
    ``use_llm`` holds the LLM credential in its own fields, and an embedding
    reusing the VLM key inherits that same credential one step further.
    Asking whether the borrowing field is non-empty would attribute the key to
    the borrower - whose Base URL the operator never wrote for it - and refuse
    the one origin the key genuinely belongs to.
    """
    if section == "vlm":
        return "llm" if loaded.vlm.use_llm else "vlm"
    if section == "embedding":
        if loaded.vlm.use_llm or not loaded.vlm.api_key:
            # A keyless VLM, or one that borrows the LLM itself, never owns
            # the credential this switch asks to reuse.
            return "llm"
        return "vlm"
    return section


def _normalized_origin(base_url: str) -> str:
    """Return the ``scheme://host:port`` HTTPX itself would connect to.

    The guard only has to agree with the client that actually sends the
    credential, so the origin is taken from HTTPX's own parser rather than a
    hand-rolled one. That choice is what makes the comparison safe in both
    directions: HTTPX normalizes case, treats an explicit default port as the
    scheme default, decodes punycode (``xn--aistant-0va`` and ``aßistant`` are
    one host), and *rejects* what a looser mapping would fold together - a
    fullwidth ``ｍ`` maps onto ``example.com`` under UTS-46 while HTTPX raises
    InvalidURL for it, and casefolding turns ``ß`` into ``ss``.

    Two spellings HTTPX renders to the same host are the same endpoint; a host
    HTTPX refuses returns ``""``, so the guard answers with a config error
    instead of letting InvalidURL escape as HTTP 500. Path differences stay
    allowed - DashScope's ``api`` and ``compatible-mode`` roots share a key.
    """
    try:
        url = httpx.URL(base_url)
    except (httpx.InvalidURL, ValueError, UnicodeError):
        return ""
    scheme = url.scheme.casefold()
    # No casefold() here: it folds "ß" into "ss", which is the exact collision
    # this guard exists to catch. HTTPX has already normalized ASCII case.
    host = url.host
    if scheme not in {"http", "https"} or not host:
        return ""
    port = url.port or (443 if scheme == "https" else 80)
    if ":" in host:  # IPv6 literal keeps its brackets in the comparison key
        return f"{scheme}://[{host}]:{port}"
    return f"{scheme}://{host}:{port}"


def _origin_scheme_text(base_url: str) -> str:
    """Best-effort scheme used only to word a refusal, never to decide one."""
    try:
        return urlparse(base_url).scheme.casefold()
    except ValueError:
        return ""


def _probe_target_refusal(
    probed_base_url: str,
    model_type: str,
    *,
    supplied_key: str,
    stored_key: str,
    trusted_base_urls: Sequence[str],
    unconfigured_target: bool = False,
) -> str:
    """Return a user-facing refusal when the probe target must not be used.

    ``/models/test`` deliberately accepts an unsaved ``base_url`` so an
    operator can check an edited config before persisting it.  That is safe
    while the credential also comes from the request - the caller already
    holds it - and unsafe the moment the route reaches into its own stored
    configuration: the caller would then be steering a *saved* secret to any
    host it picked (CWE-522).  Three separate cases follow from that:

    * a request that carries its own key may test any http(s) address;
    * a probe that will send **no** credential is a plain URL check, so
      binding its origin would only break keyless local endpoints;
    * once a non-empty stored credential is in play, it may only travel to an
      origin the operator explicitly saved it for, and when no such origin is
      recorded the target must not be completed from the request itself.
    """
    target_origin = _normalized_origin(probed_base_url)
    if not target_origin:
        scheme = _origin_scheme_text(probed_base_url)
        if scheme in {"http", "https"}:
            # The scheme is fine but HTTPX will not build a request for this
            # host at all (homograph, stray control character, half-written
            # IPv6 literal). Report the address instead of a protocol hint.
            return (
                f"配置不完整：{model_type} 的 Base URL 无法解析"
                f"（当前: {probed_base_url}）。请在配置弹窗中核对协议、主机与端口。"
            )
        return (
            f"配置不完整：{model_type} 的 Base URL 必须使用 http 或 https 协议"
            f"（当前: {scheme or '未指定'}）。"
        )
    if supplied_key:
        return ""
    if not stored_key:
        return ""
    homes = {
        origin
        for origin in (_normalized_origin(url) for url in trusted_base_urls)
        if origin
    }
    if not homes:
        return (
            "安全限制：本次探测会使用已保存的 API Key，但该 Key 没有记录归属地址，"
            f"无法确认它属于本次请求的目标（本次请求: {target_origin}）。"
            "请先在配置弹窗中保存该地址的 Base URL，或为新地址直接填写 API Key。"
        )
    if target_origin not in homes:
        default_note = (
            "本次目标来自内置默认地址，该分项尚未保存 Base URL。" if unconfigured_target else ""
        )
        return (
            "安全限制：本次探测会使用已保存的 API Key，但目标地址与该 Key 保存时的"
            f"归属地址不一致（已保存: {'、'.join(sorted(homes))}，本次请求: "
            f"{target_origin}）。{default_note}"
            "请先保存该分项的 Base URL 后再测试，或在配置弹窗中为新地址填写 API Key。"
        )
    return ""


def _non_secret_probe_params(
    payload: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    """Keep the credential out of query strings.

    A GET probe sends its payload as URL parameters, and query strings end up
    in provider access logs, intermediaries and browser history.  No builder
    puts the key in the parameters today; this drops any value that *carries*
    the key - bare or wrapped in a scheme such as ``Bearer`` - so a future
    builder cannot regress it.
    """
    if not api_key:
        return payload
    return {
        key: value
        for key, value in payload.items()
        if api_key not in str(value)
    }


async def _prepare_probe_payload(
    body: ModelConnectionTestRequest,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    if body.type == "asr":
        return await _asr_probe(body)
    url, headers, payload = _probe_payload(body)
    if body.type in {"llm", "vlm"} and model_config.is_anthropic_protocol(
        body.protocol,
    ):
        from models.output_budget import anthropic_output_limit

        payload["max_tokens"] = await anthropic_output_limit(
            body.model_name,
            base_url=body.base_url,
            api_key=body.api_key,
        )
    return url, headers, payload


class ProbeDestinationError(ValueError):
    """A probe target violated the destination policy.

    Subclasses ``ValueError`` on purpose: ``test_model_connection`` catches
    ``(httpx.HTTPError, ValueError, RuntimeError)`` and renders the message
    as an ``ok=False`` diagnostic. ``domain.errors.ValidationError`` is not
    a ``ValueError``, so raising that instead would make the endpoint whose
    job is explaining a broken configuration answer with a 500.
    """


# Cloud metadata services hand instance credentials to anything that asks.
# Most answer from the link-local range (169.254.169.254, fe80::/10), but
# two sit outside it: AWS answers IPv6 on the ULA fd00:ec2::254, and
# Alibaba Cloud on 100.100.100.200 in the shared-address space. Neither
# ``is_link_local`` nor ``is_private`` covers all of them, so they are
# listed. No model endpoint is ever served from any of these, so a probe
# refuses them. Loopback and RFC1918 stay allowed on purpose: a
# self-hosted gateway on localhost or on the operator's LAN is a
# first-class Creator setup. That makes this policy narrower than
# safe_remote_download.require_public_ip, which rejects every non-global
# address because it guards URLs a provider handed us, while these are
# URLs the operator typed into the model form.
_PROBE_ALLOWED_SCHEMES = frozenset({"http", "https"})
_PROBE_METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(address)
    for address in (
        "169.254.169.254",
        "fd00:ec2::254",
        "100.100.100.200",
    )
)


def _reject_metadata_address(address: Any) -> None:
    """Refuse an address that can only be a cloud metadata service.

    The IPv4-mapped IPv6 spelling names the same host, so it is judged as
    that address: a policy comparing parsed values would otherwise read
    ``::ffff:100.100.100.200`` as an ordinary IPv6 and hand the bearer key
    to the Alibaba metadata endpoint written a second way. The link-local
    range already came through this notation, which is why only the
    explicitly listed endpoints were reachable by the alternate spelling.
    """
    spellings = [address]
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        spellings.append(mapped)
    for spelling in spellings:
        if spelling.is_link_local or spelling in _PROBE_METADATA_ADDRESSES:
            raise ProbeDestinationError(
                "模型 Base URL 不允许指向云元数据服务地址",
            )


def _reject_metadata_host(host: str) -> None:
    """Refuse a literal metadata target before a request is built.

    Only literal addresses are checked here. A hostname is judged by the
    address its socket actually connected to (``_assert_probe_peer``),
    which cannot be beaten by answering a pre-flight lookup with a public
    address and the real one with a metadata address.
    """
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return
    _reject_metadata_address(address)


def _assert_probe_destination(url: str) -> None:
    """Constrain where a probe may go, before it leaves the process.

    A probe sends the configured API key as a bearer credential and
    reports the response to whoever called it, so an unconstrained
    ``base_url`` is a credential leak and an internal-network oracle at
    the same time. An invalid port is left to httpx: it cannot turn a
    probe inwards, and how an unusable Base URL fails is not this
    policy's concern.
    """
    parsed = urlsplit(str(url or "").strip())
    scheme = parsed.scheme.casefold()
    if scheme not in _PROBE_ALLOWED_SCHEMES:
        raise ProbeDestinationError(
            f"模型 Base URL 必须是 http(s)，当前为 {scheme or '空'}",
        )
    host = parsed.hostname
    if not host:
        raise ProbeDestinationError("模型 Base URL 缺少主机名")
    if parsed.username is not None or parsed.password is not None:
        # Embedded credentials duplicate the bearer header, and a URL
        # like "https://dashscope.aliyuncs.com@evil.example" reads as a
        # trusted host to anyone skimming the probe log.
        raise ProbeDestinationError("模型 Base URL 不允许携带用户名或密码")
    _reject_metadata_host(host)


def _assert_probe_peer(response: Any) -> None:
    """Refuse a probe whose socket actually reached a metadata service.

    The pre-flight check sees the URL, not the address DNS returned for
    it, so a hostname can point at a public address while the connection
    lands on the metadata service. The connected peer cannot lie about
    that. A transport with no network stream (a test double, in-process
    ASGI) exposes no peer and is skipped, as there is nothing to verify.

    Known limit: when httpx reaches the endpoint through an HTTP proxy the
    peer is the proxy, so this attests to the proxy's address rather than
    the final host's. Switching the client to ``trust_env=False`` is not
    the remedy, because a deployment that only reaches its gateway through
    a configured proxy would then fail its connection test outright, and
    the probed Base URL is operator-entered configuration rather than
    user input.
    """
    extensions = getattr(response, "extensions", None)
    if not isinstance(extensions, dict):
        return
    stream = extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if get_extra_info is None:
        return
    peer = get_extra_info("server_addr")
    if not isinstance(peer, tuple) or not peer:
        return
    try:
        address = ipaddress.ip_address(str(peer[0]).split("%", 1)[0])
    except ValueError:
        return
    _reject_metadata_address(address)


# What a probe's 2xx answer is allowed to prove, declared by the probe that
# builds it and graded by ``_grade_attestation`` before the route reports a
# verdict.  Absent means the probe never asked the model to do its work: a
# GET against a registry, a credit balance, or the read-only voice listing —
# which posts to a management surface without synthesizing a single sample —
# all prove the credential and nothing more.  Inferring the level from the
# verb is what let that listing claim a verified voice.
_ATTEST_HANDLED = "handled"
_ATTEST_ASR_WHISPER = "asr-whisper"
_ATTEST_ASR_QWEN3 = "asr-qwen3"
_ATTEST_ASR_FUN = "asr-fun"

# A 2xx on an ASR probe is graded by walking the body the way the production
# reader does, not by whether some field name appears.  ``asr_model`` calls
# ``response.json()`` and then indexes ``segments``, ``output.choices`` or
# ``output.task_id``, so a body it cannot walk is not an unfamiliar answer —
# it is the exception the next real request would raise.  These graders mirror
# those readers rather than what a mock finds convenient.

# Fun-ASR is the one async route and gets its own grading below: a 2xx submit
# only says a task was taken, while ``asr_model._fun_asr`` polls until
# ``task_status`` is ``SUCCEEDED`` and refuses anything else.  A task id on
# its own cannot be promoted to "transcription works".
_ASR_TASK_SUCCEEDED = "SUCCEEDED"
# Only a state known to be terminal-and-negative is a refusal. Anything else
# the provider invented stays a credential-only verdict: guessing at an
# unlisted status would report a working route as broken.
_ASR_TASK_FAILED = ("FAILED", "CANCEL", "CANCELED", "CANCELLED")


def _grade_fun_asr_submit(document: Mapping[str, Any]) -> tuple[bool, str]:
    """Grade an asynchronous submit, which cannot have proved a transcript.

    The probe posts and deliberately does not poll, so the only positive
    claim available is that the route accepted the work.  A submit that came
    back with a terminal failure is refused outright, and one that is still
    queued leaves ``capability_verified`` false: the test button reports a
    credential and an accepted task, not a transcription.
    """
    output = document.get("output")
    if not isinstance(output, Mapping):
        # ``_fun_asr`` reads ``output.task_id`` before it polls, so an
        # ``output`` holding a string — or no ``output`` at all — is the
        # exception the real request would raise, not an unfamiliar shape.
        return False, (
            "转写提交响应的 output 不是对象"
            + (f"（{type(output).__name__}）" if output is not None else "")
            + "，生产读取 output.task_id 会失败"
        )
    if not output.get("task_id"):
        return False, "转写任务未被受理（异步提交未返回 task_id）"
    # Imported where production decides, so the probe cannot drift from it.
    from models.asr_model import _no_speech_output

    no_speech = bool(_no_speech_output(output))
    outcome = str(output.get("task_status") or "").strip().upper()
    if outcome == _ASR_TASK_SUCCEEDED:
        return _grade_fun_asr_terminal(output, no_speech)
    if outcome in _ASR_TASK_FAILED:
        if no_speech:
            # ``_fun_asr`` answers an empty transcript for a no-speech verdict
            # even when the task itself ended FAILED, so the silence this
            # probe deliberately asked for is not a breakage.
            return True, ""
        detail = str(output.get("message") or output.get("code") or "")
        return (
            False,
            f"转写任务以 {outcome} 结束" + (f"：{detail}" if detail else ""),
        )
    return False, ""


def _grade_fun_asr_terminal(
    output: Mapping[str, Any],
    no_speech: bool,
) -> tuple[bool, str]:
    """Walk a finished Fun-ASR task the way the poll handler does.

    ``asr_model._fun_asr`` takes the first ``results`` entry whose
    ``subtask_status`` is SUCCEEDED and indexes its ``transcription_url``, so a
    document that claims the task finished without such an entry is the
    ``RuntimeError`` (or ``KeyError``) the next real request would raise, not an
    unfamiliar answer to be believed. A submit that says nothing at all about
    the subtasks stays unproven rather than failing: this probe deliberately
    does not poll, so it must not invent a verdict the poll has not confirmed.
    """
    if no_speech:
        return True, ""
    results = output.get("results")
    if results is None:
        return False, ""
    if not _walkable_entries(results):
        return False, (
            f"转写任务的 results 不是列表（{type(results).__name__}），" "生产遍历子任务会失败"
        )
    succeeded = next(
        (
            item
            for item in results
            if isinstance(item, Mapping)
            and str(item.get("subtask_status") or "").upper()
            == _ASR_TASK_SUCCEEDED
        ),
        None,
    )
    if succeeded is None:
        failures = "; ".join(
            str(item.get("message") or item.get("code") or "").strip()
            for item in results
            if isinstance(item, Mapping)
        ).strip("; ")
        return False, (
            "转写任务没有成功的子任务，生产会抛 Fun-ASR failed"
            + (f"：{failures[:160]}" if failures else "")
        )
    if not str(succeeded.get("transcription_url") or ""):
        return False, "转写子任务已成功但未返回 transcription_url，生产下载转写结果时会失败"
    return True, ""


def _error_wrapped_in_2xx(document: Mapping[str, Any]) -> str:
    """Return the provider's own wording when a 2xx body is an error.

    Some gateways answer 200 and put the refusal in the body, which is why a
    status code alone cannot attest to a capability.  DashScope nests the same
    pair inside ``output`` on its asynchronous routes, so one level down is
    read as well — an accepted submit carrying a failed task is a refusal, not
    an unfamiliar shape.
    """
    nodes: list[Mapping[str, Any]] = [document]
    nested = document.get("output")
    if isinstance(nested, Mapping):
        nodes.append(nested)
    for node in nodes:
        error = node.get("error")
        if isinstance(error, Mapping):
            return str(error.get("message") or error.get("type") or error)
        if error:
            return str(error)
        if node.get("code") and node.get("message"):
            return f"{node['code']}: {node['message']}"
    return ""


def _body_sample(body: str) -> str:
    """Return the leading slice of *body* an operator has to recognise."""
    return " ".join((body or "").strip()[:120].split())


def _non_json_transcript_refusal(body: str, content_type: str) -> str:
    """Word a 2xx production cannot parse as the failure it is.

    Every ASR reader starts with ``response.json()``, so a streaming frame or
    a login interstitial is a ``JSONDecodeError`` on the next real request.
    The content type is quoted rather than trusted: gateways serve HTML under
    ``text/plain`` often enough that the bytes, not the label, decide what the
    caller was handed.
    """
    sample = _body_sample(body)
    lowered = sample.casefold()
    if lowered.startswith("<"):
        return f"转写探测收到 HTML 页面（可能是登录拦截），不是转写结果：{sample}"
    if lowered.startswith("event:") or lowered.startswith("data:"):
        return (
            f"转写探测收到流式响应（{content_type or '未知类型'}），"
            f"生产按 JSON 解析该响应会失败：{sample}"
        )
    return (
        f"转写探测的 2xx 响应不是 JSON（{content_type or '未知类型'}），"
        f"生产按 JSON 解析该响应会失败：{sample}"
    )


def _walkable_entries(value: object) -> bool:
    """True when production's ``for … in`` / ``[0]`` / ``.get`` walk survives.

    ``json.loads`` only yields dict/list/str/number/bool/None, so a list is the
    sole shape those readers tolerate: a string iterates into single characters
    whose ``.get`` raises, and a mapping indexed at ``[0]`` raises ``KeyError``.
    """
    return value is None or isinstance(value, (list, tuple))


def _grade_whisper_document(document: Mapping[str, Any]) -> tuple[bool, str]:
    """Grade the answer ``asr_model._whisper`` iterates.

    The reader walks ``segments`` — the field check keyed on ``text`` instead,
    so a real segment document stayed uncredited — and does ``raw.get`` plus
    ``float(raw.get("start"))`` on every entry.  A silent clip legitimately
    yields no segments, which does certify the route; an unreadable
    ``segments`` is the crash production would hit.
    """
    if "segments" in document:
        segments = document["segments"]
        if not isinstance(segments, (list, tuple)):
            return False, (
                "转写结果的 segments 不是列表" f"（{type(segments).__name__}），生产逐项读取会失败"
            )
        for raw in segments:
            if not isinstance(raw, Mapping):
                return (
                    False,
                    "转写结果的 segments 条目不是对象，生产逐项读取会失败",
                )
            for key in ("start", "end"):
                value = raw.get(key)
                if value is None:
                    continue
                try:
                    float(value)
                except (TypeError, ValueError):
                    return False, ("转写结果的 segments 时间戳不是数值，生产转换会失败")
        return True, ""
    if "text" in document:
        # Without ``verbose_json`` the answer is a bare ``text``; the reader
        # parses it and walks no segments at all, which is a working route.
        return True, ""
    return False, ""


def _grade_qwen3_document(document: Mapping[str, Any]) -> tuple[bool, str]:
    """Grade the answer ``asr_model._qwen3_sentences`` walks.

    The reader opens with ``body["output"].get("choices")``, so an ``output``
    holding a string — what a gateway writes there when it pastes its own
    failure into the field — used to certify a capability production would
    meet with ``AttributeError``.  A readable ``output`` carrying no transcript
    still proves nothing beyond the credential.
    """
    output = document.get("output")
    if output is not None and not isinstance(output, Mapping):
        return False, (
            f"转写结果的 output 不是对象（{type(output).__name__}），"
            "生产读取 output.choices 会失败"
        )
    readable = output if isinstance(output, Mapping) else {}
    choices = readable.get("choices")
    if choices:
        if not _walkable_entries(choices):
            return False, "转写结果的 choices 不是列表，生产取值会失败"
        first = choices[0]
        if not isinstance(first, Mapping):
            return False, "转写结果的 choices 条目不是对象，生产取值会失败"
        message = first.get("message")
        if message is not None and not isinstance(message, Mapping):
            return False, "转写结果的 message 不是对象，生产取值会失败"
        content = (message or {}).get("content")
        if content and not isinstance(
            content,
            (list, tuple, Mapping, str),
        ):
            return False, "转写结果的 content 无法逐项读取，生产会失败"
        return True, ""
    sentence = readable.get("sentence")
    if isinstance(sentence, Mapping) or (
        _walkable_entries(sentence) and sentence
    ):
        # ``qwen-audio-*-asr-*`` answers through ``output.sentence`` rather
        # than ``choices``; either shape the reader walks is the working route.
        return True, ""
    if "text" in document:
        return True, ""
    return False, ""


_ASR_DOCUMENT_GRADERS: dict[
    str,
    Callable[[Mapping[str, Any]], tuple[bool, str]],
] = {
    _ATTEST_ASR_WHISPER: _grade_whisper_document,
    _ATTEST_ASR_QWEN3: _grade_qwen3_document,
    _ATTEST_ASR_FUN: _grade_fun_asr_submit,
}


def _grade_attestation(
    attests: str,
    response: httpx.Response,
) -> tuple[bool, str]:
    """Split a 2xx probe into a verification level, or a refusal.

    Returns ``(capability_verified, refusal_reason)``.  A non-empty reason
    means the answer is positive evidence that the endpoint did not do the
    work — an HTML interstitial, an empty body, a body production cannot
    parse, or an error wrapped in a 200 — so the test reports a failure.  A
    body that is merely unfamiliar leaves ``ok`` true with a credential-only
    verdict: being unable to prove a capability is not the same as proving a
    breakage.  Each transcription answer is graded by the reader production
    actually uses, and the asynchronous submit on its task state, because a
    queued task is by definition not yet a result.
    """
    if not attests:
        return False, ""
    grader = _ASR_DOCUMENT_GRADERS.get(attests)
    if grader is None:
        return True, ""
    body = response.text or ""
    if not body.strip():
        return False, "转写探测收到空响应，无法确认转写路由可用"
    content_type = (response.headers.get("content-type") or "").casefold()
    try:
        document = json.loads(body)
    except ValueError:
        return False, _non_json_transcript_refusal(body, content_type)
    if not isinstance(document, Mapping):
        return False, (
            "转写探测返回的 JSON 顶层不是对象，生产按字段读取会失败：" f"{_body_sample(body)}"
        )
    wrapped = _error_wrapped_in_2xx(document)
    if wrapped:
        return False, f"转写探测在 2xx 响应中返回错误：{wrapped}"
    return grader(document)


_PROBE_CREDENTIAL_HEADERS = (
    "authorization",
    "x-api-key",
    "x-goog-api-key",
)
_PROBE_CREDENTIAL_PREFIXES = ("Bearer ", "Token ")


def _probe_credential(headers: dict[str, str]) -> str:
    """Return the bare secret ``headers`` will carry on the wire.

    By the time a probe is sent the credential only exists inside its auth
    header, and it arrives under several spellings (``Bearer``, ``Token``,
    ``x-api-key``, ``x-goog-api-key``). Reading it back from the request,
    rather than passing it down from each caller, is what keeps the filtering
    with the transport: a caller that forgets to filter can no longer leak.
    Each builder sets exactly one of those headers, so the first match is the
    credential this probe sends.
    """
    for name, value in headers.items():
        if name.lower() not in _PROBE_CREDENTIAL_HEADERS:
            continue
        secret = value.strip()
        for prefix in _PROBE_CREDENTIAL_PREFIXES:
            if secret.startswith(prefix):
                secret = secret[len(prefix) :].strip()
                break
        return secret
    return ""


async def _send_probe(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> httpx.Response:
    """Send one probe in whichever shape the probe asked for.

    ``_get_probe`` selects a GET with query params, ``_multipart_probe``
    selects a multipart/form-data POST (the shape OpenAI-compatible ASR
    transcribes with), and anything else posts JSON. ``Content-Type`` is
    dropped for the first two: a GET carries no body, and httpx has to write
    the multipart boundary itself.  ``_attests`` is the probe's own claim
    about what its 2xx would prove; the caller reads it before sending and it
    is stripped here so it never reaches the wire.

    The destination is validated on the way out and the connected peer on
    the way back, so every probe shape carries the same policy and a new
    shape cannot forget it. A GET also drops any query value that contains
    the credential it is about to send: a query string is echoed into access
    logs, proxy logs and error pages, none of which the operator authorised
    to hold the key. Only the GET shape is filtered - a body is what the
    endpoint was configured to receive, and some policy endpoints need the
    credential in it to answer at all.
    """
    _assert_probe_destination(url)
    # These markers are this function's to consume: copy first so a caller
    # that keeps its payload — a retry, a log line — never finds it stripped.
    payload = dict(payload)
    multipart = payload.pop("_multipart_probe", None)
    payload.pop("_attests", None)
    if payload.pop("_get_probe", False):
        headers.pop("Content-Type", None)
        response = await client.get(
            url,
            headers=headers,
            params=_non_secret_probe_params(
                payload,
                _probe_credential(headers),
            ),
        )
    elif multipart is not None:
        headers.pop("Content-Type", None)
        response = await client.post(
            url,
            headers=headers,
            data=multipart.get("data") or {},
            files=multipart.get("files") or {},
        )
    else:
        response = await client.post(url, headers=headers, json=payload)
    _assert_probe_peer(response)
    return response


def _probe_headers(body: ModelConnectionTestRequest) -> dict[str, str]:
    """Auth headers shared by every probe shape.

    Send the credential whenever one is present so paid models behind a
    free-tier-capable provider still authenticate; ``require_api_key``
    only controls whether an *absent* key is tolerated (validated by the
    route before probing).
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if body.api_key:
        headers["Authorization"] = f"Bearer {body.api_key}"
    return headers


def _probe_payload(
    body: ModelConnectionTestRequest,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    if body.type == "asr":
        # ASR is dispatched to the async _asr_probe, which uploads a sample
        # first. Falling through here would silently return the generic
        # upload-policy default — a route production never calls — and a test
        # asserting on it would pass while measuring nothing.
        raise ValueError("ASR probes must go through _prepare_probe_payload")
    base = body.base_url.rstrip("/")
    headers = _probe_headers(body)
    if body.type == "tts":
        # The upload-policy probe accepts any model string, so it cannot catch a
        # mistyped model name. Synthesizing one character costs a fraction of a
        # cent and actually validates the model/voice pair. Models without
        # system voices cannot synthesize at all until a character voice
        # exists, so for those verify the credential against the voice-listing
        # surface instead.
        from models.tts_capabilities import require_capability

        parsed = urlparse(body.base_url)
        capability = require_capability(body.model_name)
        if not capability.has_system_voices:
            action = (
                "list_voice" if capability.family == "cosyvoice" else "list"
            )
            management = (
                "voice-enrollment"
                if capability.family == "cosyvoice"
                else "qwen-voice-enrollment"
            )
            return (
                f"{parsed.scheme}://{parsed.netloc}"
                "/api/v1/services/audio/tts/customization",
                headers,
                {"model": management, "input": {"action": action}},
            )
        return (
            f"{parsed.scheme}://{parsed.netloc}"
            "/api/v1/services/aigc/multimodal-generation/generation",
            headers,
            {
                "_attests": _ATTEST_HANDLED,
                "model": body.model_name,
                "input": {
                    "text": "嗨",
                    "voice": body.voice or capability.system_voices[0],
                },
                "parameters": {},
            },
        )
    if body.type == "embedding":
        # Minimal real embedding request: the one-token spend is the only
        # reliable probe on the native multimodal-embedding endpoint.
        suffix = (
            "/services/embeddings/multimodal-embedding/multimodal-embedding"
        )
        endpoint = base if base.endswith(suffix) else f"{base}{suffix}"
        return (
            endpoint,
            headers,
            {
                "_attests": _ATTEST_HANDLED,
                "model": body.model_name,
                "input": {"contents": [{"text": "ping"}]},
                "parameters": {"dimension": 2560},
            },
        )
    if body.type in {"llm", "vlm"}:
        if model_config.is_anthropic_protocol(body.protocol):
            return _anthropic_llm_probe(body, base)
        if model_config.is_gemini_protocol(body.protocol):
            return _gemini_llm_probe(body, base)
        content: Any = "Reply with pong only."
        if body.type == "vlm":
            content = [
                {"type": "text", "text": "Reply with red only."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR4nGO4I2JDEmIY1TCqYfhqAAAeBCwQ8YdREQAAAABJRU5ErkJggg==",
                    },
                },
            ]
        return (
            f"{base}/chat/completions",
            headers,
            {
                "_attests": _ATTEST_HANDLED,
                "model": body.model_name,
                "messages": [{"role": "user", "content": content}],
            },
        )
    if body.type == "image":
        if "token plan" in body.protocol.casefold():
            return _token_plan_models_probe(body, headers)
        if "dashscope" in body.protocol.casefold() or "百炼" in body.protocol:
            return _dashscope_policy_probe(body, headers)
        if "minimax" in body.protocol.casefold() or "海螺" in body.protocol:
            return _minimax_image_probe(body, headers)
        return _openai_model_probe(body, headers)
    if body.type == "video":
        from models.video_capabilities import video_model_capability

        video_backend = (
            model_config.video_backend_for_protocol(
                body.protocol,
            )
            or ""
        )
        capability = video_model_capability(
            body.model_name,
            video_backend,
        )
        if not capability.known:
            unknown_capability_error = (
                "VIDEO_MODEL_CAPABILITY_UNKNOWN: 精确模型 ID 与协议组合" + "未收录，已停止连接探测"
            )
            raise ValueError(unknown_capability_error)
        if video_backend == "veo":
            headers.pop("Authorization", None)
            headers["x-goog-api-key"] = body.api_key
            return (
                f"{base}/models/{body.model_name}",
                headers,
                {"_get_probe": True},
            )
        if video_backend == "minimax":
            return (
                f"{base}/v1/query/video_generation",
                headers,
                {
                    "_get_probe": True,
                    "task_id": "creator-connection-probe",
                },
            )
        if video_backend == "minimax_sglang":
            # Zero-cost self-hosted probe: the SGLang multimodal server
            # exposes GET /health (2xx when healthy and warmed up).
            return (f"{base}/health", headers, {"_get_probe": True})
        if video_backend == "kling":
            return (
                f"{base}/tasks",
                headers,
                {
                    "_get_probe": True,
                    "task_ids": "creator-connection-probe",
                },
            )
        if video_backend == "vidu":
            headers["Authorization"] = f"Token {body.api_key}"
            return (
                f"{base}/ent/v2/credits",
                headers,
                {"_get_probe": True, "show_detail": "false"},
            )
    if "volcano" in body.protocol.casefold() or "火山" in body.protocol:
        # Zero-cost Ark probe: the task-list API is read-only and free,
        # unlike posting a real generation task.
        return (
            f"{base}/api/v3/contents/generations/tasks",
            headers,
            {"_get_probe": True, "page_size": 1},
        )
    if "token plan" in body.protocol.casefold():
        return _token_plan_models_probe(body, headers)
    if body.type == "video":
        hostname = (urlparse(body.base_url).hostname or "").casefold()
        is_dashscope_protocol = (
            "dashscope" in body.protocol.casefold() or "百炼" in body.protocol
        )
        if is_dashscope_protocol and (
            hostname
            in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"}
            or hostname.endswith(".maas.aliyuncs.com")
        ):
            return _dashscope_video_task_probe(body, headers)
    return _dashscope_policy_probe(body, headers)


# Semantic diagnostic read: this performs no Creator/runtime/config mutation,
# so it is intentionally outside the mutating-route idempotency registry.
@router.post("/test", response_model=ConnectionTestResponse)
async def test_model_connection(
    body: ModelConnectionTestRequest = Body(...),
) -> ConnectionTestResponse:
    loaded = await asyncio.to_thread(load_model_config)
    item = getattr(loaded, body.type)
    fallback_api_key = item.api_key
    # The addresses this credential may reach: only Base URLs the operator
    # actually wrote (model_config.json or env), never the ones _defaults()
    # pre-fills - see _operator_written_base_url.
    section_home = _operator_written_base_url(body.type)
    trusted_base_urls = [section_home]
    if (
        body.type in ("asr", "tts", "s2v", "image", "video")
        and getattr(item, "reuse_llm_key", False)
        and not fallback_api_key
    ):
        fallback_api_key = loaded.llm.api_key
        # A reused LLM key belongs to the LLM endpoint, and a section host the
        # operator saved next to the reuse switch was authorised by that
        # switch; a default-filled address was not.
        trusted_base_urls.append(_operator_written_base_url("llm"))
    if body.type == "vlm" and getattr(item, "use_llm", False):
        # "Reuse the text model" is an explicit decision to send the LLM
        # credential, and assembly overwrites whatever address the VLM
        # section still holds, so the VLM's own stale host is not an
        # authorization either - only the LLM's written origin is.
        if loaded.llm.api_key:
            fallback_api_key = loaded.llm.api_key
            trusted_base_urls = [_operator_written_base_url("llm")]
    if (
        body.type == "embedding"
        and getattr(item, "reuse_vlm_key", False)
        and not fallback_api_key
    ):
        # Trust the origin of the key that is really selected: a VLM that
        # borrows the LLM credential cannot be named its owner, and the
        # embedding's own saved address stays authorised by its switch.
        key_owner = _credential_owner_section(loaded, "embedding")
        fallback_api_key = getattr(loaded, key_owner).api_key
        trusted_base_urls.append(_operator_written_base_url(key_owner))
    request_api_key = "" if body.api_key == SECRET_MASK else body.api_key
    selected = body.model_copy(
        update={
            "base_url": body.base_url or item.base_url,
            "api_key": request_api_key or fallback_api_key,
            "model_name": body.model_name or item.model_name,
            "protocol": body.protocol or item.protocol,
            "provider": body.provider or getattr(item, "provider", None),
            "voice": body.voice or getattr(item, "voice", ""),
        },
    )
    missing: list[str] = []
    if not selected.base_url:
        missing.append("Base URL")
    if body.require_api_key and not selected.api_key:
        missing.append("API Key")
    if not selected.model_name:
        missing.append("模型名称")
    if missing:
        return ConnectionTestResponse(
            ok=False,
            ms=0,
            error=(
                f"配置不完整：缺少 {'、'.join(missing)}（配置项: "
                f"{body.type}，协议: {selected.protocol or '未指定'}）。"
                "请在模型配置弹窗中补齐后重试。"
            ),
        )
    refusal = _probe_target_refusal(
        selected.base_url,
        body.type,
        supplied_key=request_api_key,
        stored_key=fallback_api_key,
        trusted_base_urls=trusted_base_urls,
        unconfigured_target=bool(
            not section_home and not (body.base_url or "").strip(),
        ),
    )
    if refusal:
        return ConnectionTestResponse(ok=False, ms=0, error=refusal)
    start = time.monotonic()
    try:
        url, headers, payload = await _prepare_probe_payload(selected)
        # Read the claim before sending: ``_send_probe`` strips it, and the
        # probe declares its own verification level rather than the route
        # guessing one from the HTTP verb — a read-only management POST is a
        # POST, and it attests to the credential exactly like a GET does.
        attests = str(payload.get("_attests") or "")
        # Explicit although already httpx's default: a redirect off the
        # configured endpoint would carry the bearer key with it, and the
        # probe would report a host the operator never named.
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
        ) as client:
            response = await _send_probe(client, url, headers, payload)
        elapsed = round((time.monotonic() - start) * 1000)
        if response.is_success and "minimax" in selected.protocol.casefold():
            # MiniMax hides auth/balance failures inside an HTTP 200; without
            # this the connection test green-lights a key the provider rejects.
            base_resp_error = _minimax_base_resp_error(response)
            if base_resp_error is not None:
                return ConnectionTestResponse(
                    ok=False,
                    ms=elapsed,
                    error=(
                        f"{base_resp_error} "
                        f"[探测端点: {redact_url(url)}，协议: {selected.protocol}]"
                    ),
                )
        if response.is_success:
            capability_verified, refusal = _grade_attestation(
                attests,
                response,
            )
            if refusal:
                return ConnectionTestResponse(
                    ok=False,
                    ms=elapsed,
                    error=(
                        f"{refusal} "
                        f"[探测端点: {redact_url(url)}，协议: {selected.protocol}]"
                    ),
                )
            return ConnectionTestResponse(
                ok=True,
                ms=elapsed,
                detail="provider accepted the probe",
                capability_verified=capability_verified,
            )
        try:
            provider_body = response.json()
            if isinstance(provider_body, dict):
                err_obj = provider_body.get("error")
                if isinstance(err_obj, dict):
                    provider_error = (
                        err_obj.get("message")
                        or err_obj.get("type")
                        or str(err_obj)
                    )
                else:
                    provider_error = (
                        provider_body.get("message")
                        or provider_body.get("error")
                        or str(provider_body)
                    )
            else:
                provider_error = str(provider_body)
        except ValueError:
            # A gateway/nginx error page is HTML, not a provider message; echo
            # ing it leaks markup into the UI and hides the real cause. Fall
            # back to the status line only when the body is not JSON.
            raw = response.text.strip()
            if raw[:1] == "<" or "<html" in raw[:200].casefold():
                provider_error = (
                    f"服务返回了非 JSON 错误页（{response.reason_phrase}），"
                    "通常是 Base URL 或路径不受该 provider 支持"
                )
            else:
                provider_error = raw[:300]
        hint = upstream_status_hint(response.status_code)
        return ConnectionTestResponse(
            ok=False,
            ms=elapsed,
            error=(
                f"HTTP {response.status_code}: "
                f"{provider_error or '请求失败'} "
                f"[探测端点: {redact_url(url)}，协议: {selected.protocol}]"
                + (f"。{hint}" if hint else "")
            ),
        )
    except httpx.ConnectError:
        return ConnectionTestResponse(
            ok=False,
            ms=round((time.monotonic() - start) * 1000),
            error=(
                f"无法连接到服务，请检查 Base URL 是否正确"
                f"（当前 Base URL: {selected.base_url}）"
            ),
        )
    except httpx.TimeoutException:
        return ConnectionTestResponse(
            ok=False,
            ms=round((time.monotonic() - start) * 1000),
            error=(
                f"连接超时，请检查网络或 Base URL" f"（当前 Base URL: {selected.base_url}）"
            ),
        )
    except (
        httpx.InvalidURL,
        httpx.HTTPError,
        ValueError,
        RuntimeError,
    ) as exc:
        # RuntimeError covers the ASR probe's sample upload, which refuses an
        # absent credential or a malformed policy before any probe is sent.
        return ConnectionTestResponse(
            ok=False,
            ms=round((time.monotonic() - start) * 1000),
            error=(
                f"{type(exc).__name__}: {exc} "
                f"[配置项: {body.type}，协议: {selected.protocol}]"
            ),
        )


# Test the incoming config only. Not impacting the current backend config.
@router.post("/test-oss", response_model=ConnectionTestResponse)
async def test_oss_connection(
    body: OssConfig = Body(...),
) -> ConnectionTestResponse:
    if body.access_key_secret == SECRET_MASK:
        persisted = await asyncio.to_thread(
            load_model_config,
            include_environment=False,
        )
        body = body.model_copy(
            update={"access_key_secret": persisted.oss.access_key_secret},
        )
    if (
        not body.endpoint
        or not body.access_key_id
        or not body.access_key_secret
        or not body.bucket
    ):
        return ConnectionTestResponse(
            ok=False,
            ms=0,
            error="配置不完整，请检查 Endpoint、Access Key ID、Access Key Secret 和 Bucket",
        )
    try:
        import oss2

        def probe() -> None:
            auth = oss2.Auth(body.access_key_id, body.access_key_secret)
            bucket = oss2.Bucket(auth, body.endpoint, body.bucket)
            bucket.get_bucket_info()

        await asyncio.to_thread(probe)
        return ConnectionTestResponse(
            ok=True,
            detail="OSS bucket is reachable",
        )
    except Exception as exc:
        logger.warning("failed to test oss connection")
        exc_str = str(exc)
        if "InvalidAccessKeyId" in exc_str or "AccessDenied" in exc_str:
            return ConnectionTestResponse(
                ok=False,
                error="Access Key 无效或权限不足，请检查配置",
            )
        if "NoSuchBucket" in exc_str:
            return ConnectionTestResponse(
                ok=False,
                error="Bucket 不存在，请检查 Bucket 名称",
            )
        if "connect" in exc_str.lower() or "timeout" in exc_str.lower():
            return ConnectionTestResponse(
                ok=False,
                error="无法连接到 OSS 服务，请检查 Endpoint 和网络",
            )
        return ConnectionTestResponse(ok=False, error=exc_str)


# ---------------------------------------------------------------------------
# Real API Key Retrieval (for testing)
# ---------------------------------------------------------------------------


@router.get("/real-api-key/{section}")
async def get_real_api_key(section: str) -> dict[str, str]:
    """Return the real API key of the given config section (for testing).

    When VLM/Grounding/ASR reuse the LLM config, the frontend needs the real
    API key to run connection tests, because it only stores the mask
    "__CREATOR_SECRET__".
    """
    valid_sections = {
        "llm",
        "vlm",
        "asr",
        "tts",
        "embedding",
        "image",
        "video",
        "grounding",
    }
    if section not in valid_sections:
        raise ValidationError(
            f"不支持的配置项: {section}，必须是 {', '.join(valid_sections)} 之一",
        )

    config = load_model_config()
    item = getattr(config, section)
    return {"api_key": item.api_key}


# ---------------------------------------------------------------------------
# Host Provider API Key Sync
# ---------------------------------------------------------------------------


@router.get("/host-provider/{provider_id}/api-key")
async def get_host_provider_key(provider_id: str) -> dict[str, str | None]:
    """Fetch the API key of the given provider from the QwenPaw host.

    Used to auto-sync the API key when picking an LLM/VLM provider in Creator.
    """
    api_key = get_host_provider_api_key(provider_id)
    return {"api_key": api_key}
