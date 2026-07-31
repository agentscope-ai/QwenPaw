# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
# pylint: disable=wrong-import-order
# pylint: disable=raise-missing-from
"""External-root model configuration and explicit provider connection probes."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Body, Header, Request, Response, status

from domain.errors import ConflictError, StorageIntegrityError, ValidationError
from models import config as model_config
from schemas.models import (
    AsrConfig,
    ExecutionAuthorizationConfig,
    GroundingConfig,
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
from services.file_agent_runtime import get_creator_agent_runtime
from services.storage_root import require_creator_data_root

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


_SECTIONS = ("llm", "vlm", "grounding", "asr", "image", "video", "oss")
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
        image=ModelConfigItem(
            enabled=False,
            protocol="OpenAI 协议",
        ),
        video=ModelConfigItem(
            enabled=False,
            protocol="Volcano Engine（火山引擎）",
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
            base[section].update(config_section)
            explicit.update(
                key
                for key, value in config_section.items()
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
    authorization = configs.get("execution_authorization")
    if isinstance(authorization, dict):
        base["execution_authorization"].update(authorization)
    checkpoints = configs.get("creation_checkpoints")
    if isinstance(checkpoints, dict):
        base["creation_checkpoints"].update(checkpoints)
    if base["vlm"].get("use_llm"):
        for field in ("base_url", "api_key", "model_name"):
            if not base["vlm"].get(field):
                base["vlm"][field] = base["llm"].get(field, "")

    # Decrypt secret fields when the QwenPaw secret store is available.
    _decrypt_secret_fields(base)

    return ModelConfigData.model_validate(base)


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
_SECRET_FIELDS = ("api_key", "access_key_secret", "policy_api_key")


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
    """Apply one read-modify-write transaction under the config lock."""

    config_path = _config_paths()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with CrossProcessFileLock(config_path.parent / ".model-config.lock"):
        persisted = _assemble_model_config(
            _load_json(config_path),
            include_environment=False,
        )
        updated = mutator(persisted)

        # Encrypt secret fields when the QwenPaw secret store is available.
        updated_dict = updated.model_dump()
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


def _ensure_grounding_model_configured(data: ModelConfigData) -> None:
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
    if grounding.tavily_api_key:
        return
    search_model = _grounding_search_model(data)
    if not grounding.native_search_enabled:
        raise ValidationError(
            "Grounding 搜索未配置；请配置 Tavily，或启用 Qwen/DashScope 原生搜索",
        )
    if not _model_config_complete(search_model):
        raise ValidationError(
            "Grounding 搜索未配置；请配置 Tavily，或完整配置 Qwen/DashScope 搜索模型",
        )
    if not _supports_dashscope_native_search(search_model):
        raise ValidationError(
            "当前搜索模型不支持 Qwen/DashScope 原生 web_search；请配置 Tavily，或选择 DashScope（百炼）搜索模型",
        )


def request_tool_configs() -> dict[str, dict[str, Any]]:
    data = load_model_config()
    configs: dict[str, dict[str, Any]] = {}
    mapping = {
        "llm": model_config.CREATOR_TEXT_CONFIG_TOOL,
        "vlm": model_config.CREATOR_VLM_CONFIG_TOOL,
        "asr": model_config.CREATOR_ASR_CONFIG_TOOL,
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
        if section == "image" and "dashscope" in item.protocol.casefold():
            tool_config["_image_backend"] = "DASHSCOPE"
        if section == "video":
            tool_config["_video_backend"] = (
                "seedance2"
                if "volcano" in item.protocol.casefold()
                or "火山" in item.protocol
                else "wan"
            )
        configs[tool_name] = tool_config
    grounding = data.grounding
    configs[model_config.CREATOR_GROUNDING_CONFIG_TOOL] = {
        "enabled": grounding.enabled,
        "tavily_api_key": grounding.tavily_api_key,
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


def _notify_agent_model_config_changed() -> None:
    runtime = get_creator_agent_runtime()
    if runtime is None:
        return
    for project in runtime.services.projects.list():
        runtime.notify(project.project_id)


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
                raise ValidationError("OSS: Access Key 无效或权限不足，请检查配置")
            if "NoSuchBucket" in exc_str:
                raise ValidationError("OSS: Bucket 不存在，请检查 Bucket 名称")
            if "connect" in exc_str.lower() or "timeout" in exc_str.lower():
                raise ValidationError("OSS: 无法连接到 OSS 服务，请检查 Endpoint 和网络")
            raise ValidationError(f"OSS: {exc_str}")
        return

    item = config.get(section, {})
    if not item.get("enabled") or not item.get("model_name"):
        return

    api_key = item.get("api_key", "")
    if section == "asr" and item.get("reuse_llm_key") and not api_key:
        api_key = config.get("llm", {}).get("api_key", "")
    if not item.get("base_url") or not api_key:
        raise ValidationError(f"{section}: 缺少 Base URL 或 API Key，请检查配置")

    probe = ModelConnectionTestRequest(
        type=section,
        base_url=item["base_url"],
        api_key=api_key,
        model_name=item["model_name"],
        protocol=item.get("protocol", ""),
        provider=item.get("provider"),
    )

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            url, headers, payload = _probe_payload(probe)
            if payload.pop("_get_probe", False):
                headers.pop("Content-Type", None)
                resp = await client.get(url, headers=headers, params=payload)
            else:
                resp = await client.post(url, headers=headers, json=payload)
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
            raise ValidationError(f"{section}: 无法连接到服务，请检查 Base URL 是否正确")
        except httpx.TimeoutException:
            raise ValidationError(f"{section}: 连接超时，请检查网络或 Base URL")
        except httpx.HTTPError as exc:
            raise ValidationError(f"{section}: {exc}")


@router.get("/config", response_model=ModelConfigData)
async def get_model_config() -> ModelConfigData:
    loaded = await asyncio.to_thread(
        load_model_config,
        include_environment=False,
    )
    return _mask_secrets(loaded)


# Semantic diagnostic read: this performs no Creator/runtime/config mutation,
# so it is intentionally outside the mutating-route idempotency registry.
@router.get("/resolved")
async def get_resolved_models() -> dict[str, Any]:
    """Return the runtime-resolved model identity execution actually uses.

    Unlike ``/models/config`` (persisted-only), this reflects request-scoped
    host tool config, environment overrides and defaults — i.e. the value
    ``get_video_model_name()`` returns at submission time.  Read-only.
    """
    return {
        "video": {
            "provider": model_config.get_video_backend(),
            "model": model_config.get_video_model_name(),
        },
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
                _notify_agent_model_config_changed()
                return True
            if reservation.record.status is IdempotencyStatus.FAILED:
                raise StorageIntegrityError(
                    "上一次模型配置写入失败，请使用新的 Idempotency-Key 重试",
                )
            data.llm.enabled = True
            _ensure_grounding_model_configured(data)
            save_model_config(data)
            _notify_agent_model_config_changed()
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

    def mutate(current: ModelConfigData) -> ModelConfigData:
        merged = current.model_dump()
        merged["creation_checkpoints"] = {"mode": mode}
        return ModelConfigData.model_validate(merged)

    def transaction() -> None:
        mutate_model_config(mutate)
        _notify_agent_model_config_changed()

    await asyncio.to_thread(transaction)
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
        return ModelConfigData.model_validate(merged)

    def transaction() -> None:
        mutate_model_config(mutate)
        _notify_agent_model_config_changed()

    await asyncio.to_thread(transaction)
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
        resolved = _resolve_secret_masks(
            ModelConfigData.model_validate(merged),
            current,
        )
        _ensure_grounding_model_configured(resolved)
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
                _notify_agent_model_config_changed()
                return
            if reservation.record.status is IdempotencyStatus.FAILED:
                raise StorageIntegrityError(
                    "上一次模型配置写入失败，请使用新的 Idempotency-Key 重试",
                )
            mutate_model_config(mutate)
            _notify_agent_model_config_changed()
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


def _probe_payload(
    body: ModelConnectionTestRequest,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    base = body.base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {body.api_key}",
        "Content-Type": "application/json",
    }
    if body.type == "asr":
        provider = body.provider or (
            "whisper" if "whisper" in body.protocol.casefold() else "fun-asr"
        )
        if provider == "whisper":
            return _openai_model_probe(body, headers)
        return _dashscope_policy_probe(body, headers)
    if body.type in {"llm", "vlm"}:
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
                "model": body.model_name,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 8,
            },
        )
    if body.type == "image":
        if "dashscope" in body.protocol.casefold() or "百炼" in body.protocol:
            return _dashscope_policy_probe(body, headers)
        return _openai_model_probe(body, headers)
    if "volcano" in body.protocol.casefold() or "火山" in body.protocol:
        # Zero-cost Ark probe: the task-list API is read-only and free,
        # unlike posting a real generation task.
        return (
            f"{base}/api/v3/contents/generations/tasks",
            headers,
            {"_get_probe": True, "page_size": 1},
        )
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
    if body.type == "asr" and item.reuse_llm_key and not fallback_api_key:
        fallback_api_key = loaded.llm.api_key
    request_api_key = "" if body.api_key == SECRET_MASK else body.api_key
    selected = body.model_copy(
        update={
            "base_url": body.base_url or item.base_url,
            "api_key": request_api_key or fallback_api_key,
            "model_name": body.model_name or item.model_name,
            "protocol": body.protocol or item.protocol,
            "provider": body.provider or getattr(item, "provider", None),
        },
    )
    if (
        not selected.base_url
        or not selected.api_key
        or not selected.model_name
    ):
        return ConnectionTestResponse(
            ok=False,
            ms=0,
            error="配置不完整，请检查 Base URL、API Key 和模型名称",
        )
    start = time.monotonic()
    try:
        url, headers, payload = _probe_payload(selected)
        async with httpx.AsyncClient(timeout=30) as client:
            if payload.pop("_get_probe", False):
                headers.pop("Content-Type", None)
                response = await client.get(
                    url,
                    headers=headers,
                    params=payload,
                )
            else:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
        elapsed = round((time.monotonic() - start) * 1000)
        if response.is_success:
            return ConnectionTestResponse(
                ok=True,
                ms=elapsed,
                detail="provider accepted the probe",
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
            provider_error = response.text[:300]
        return ConnectionTestResponse(
            ok=False,
            ms=elapsed,
            error=f"HTTP {response.status_code}: {provider_error or '请求失败'}",
        )
    except httpx.ConnectError:
        return ConnectionTestResponse(
            ok=False,
            ms=round((time.monotonic() - start) * 1000),
            error="无法连接到服务，请检查 Base URL 是否正确",
        )
    except httpx.TimeoutException:
        return ConnectionTestResponse(
            ok=False,
            ms=round((time.monotonic() - start) * 1000),
            error="连接超时，请检查网络或 Base URL",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return ConnectionTestResponse(
            ok=False,
            ms=round((time.monotonic() - start) * 1000),
            error=str(exc),
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
    valid_sections = {"llm", "vlm", "asr", "image", "video", "grounding"}
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
