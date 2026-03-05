# -*- coding: utf-8 -*-
"""Reading and writing provider configuration (providers.json)."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from ..constant import SECRET_DIR, WORKING_DIR
from .models import (
    CustomProviderData,
    ModelInfo,
    ModelSlotConfig,
    ProviderSettings,
    ProvidersData,
    ResolvedModelConfig,
)
from .registry import (
    PROVIDERS,
    get_chat_model_class,
    get_provider_chat_model,
    is_builtin,
    register_custom_provider,
    sync_custom_providers,
    sync_local_models,
    sync_ollama_models,
    unregister_custom_provider,
    validate_custom_provider_id,
)

from .ollama_manager import _base_url_to_host as _base_url_to_ollama_host

logger = logging.getLogger(__name__)

_PROVIDERS_JSON = SECRET_DIR / "providers.json"
_LEGACY_PROVIDERS_JSON_CANDIDATES = (
    Path(__file__).resolve().parent / "providers.json",
    WORKING_DIR / "providers.json",
)


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        # Some systems/filesystems may not support chmod semantics.
        pass


def _prepare_secret_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path.parent, 0o700)


def _migrate_legacy_providers_json(path: Path) -> None:
    """Copy old providers.json into secret dir once (best effort)."""
    if path.is_file():
        return
    if path.exists() and not path.is_file():
        logger.error(
            "providers.json path exists but is not a regular file: %s",
            path,
        )
        return

    for legacy in _LEGACY_PROVIDERS_JSON_CANDIDATES:
        if not legacy.is_file() or _same_path(legacy, path):
            continue
        try:
            _prepare_secret_parent(path)
            shutil.copy2(legacy, path)
            _chmod_best_effort(path, 0o600)
            return
        except OSError as exc:
            logger.warning(
                "Failed to migrate legacy providers.json from %s: %s",
                legacy,
                exc,
            )
            continue


_SUPPORTED_CHAT_MODELS: frozenset[str] = frozenset(
    ["OpenAIChatModel", "AnthropicChatModel"],
)


def get_providers_json_path() -> Path:
    """Return providers.json path under SECRET_DIR."""
    return _PROVIDERS_JSON


def get_ollama_host() -> Optional[str]:
    """Return the configured Ollama native host URL, or *None* for default."""
    data = load_providers_json()
    s = data.providers.get("ollama")
    return _base_url_to_ollama_host(s.base_url) if s and s.base_url else None


def _normalize_chat_model_name(chat_model: Optional[str]) -> str:
    """Validate and normalize chat model class name."""
    normalized = (chat_model or "").strip()
    if not normalized:
        return "OpenAIChatModel"
    if normalized not in _SUPPORTED_CHAT_MODELS:
        allowed = ", ".join(sorted(_SUPPORTED_CHAT_MODELS))
        raise ValueError(
            f"Unsupported chat model '{normalized}'. "
            f"Supported values: {allowed}.",
        )
    return normalized


def _resolve_chat_model_name(
    provider_id: str,
    data: ProvidersData,
    chat_model: Optional[str] = None,
) -> str:
    if chat_model is not None:
        return _normalize_chat_model_name(chat_model)
    return _normalize_chat_model_name(
        get_provider_chat_model(provider_id, data),
    )


def _uses_anthropic_protocol(
    provider_id: str,
    data: ProvidersData,
    chat_model: Optional[str] = None,
) -> bool:
    if provider_id == "anthropic":
        return True
    return (
        _resolve_chat_model_name(provider_id, data, chat_model)
        == "AnthropicChatModel"
    )


def _ensure_base_url(settings: ProviderSettings, defn) -> None:
    if not settings.base_url and defn.default_base_url:
        settings.base_url = defn.default_base_url


def _normalize_ollama_base_url(base_url: str) -> str:
    """Normalize Ollama OpenAI-compatible endpoint to include /v1.

    Older configs may use http://localhost:11434 (missing /v1), which leads
    to OpenAI client requests returning 404.
    """
    value = (base_url or "").strip()
    if not value:
        return value

    try:
        parts = urlsplit(value)
    except ValueError:
        return value

    path = parts.path or ""
    if path in ("", "/"):
        path = "/v1"
    elif path == "/v1/":
        path = "/v1"

    return urlunsplit(
        (parts.scheme, parts.netloc, path, parts.query, parts.fragment),
    )


def _normalize_special_provider_settings(
    provider_id: str,
    settings: ProviderSettings,
) -> None:
    """Apply provider-specific settings normalization."""
    if provider_id == "ollama" and settings.base_url:
        settings.base_url = _normalize_ollama_base_url(settings.base_url)


def _build_remote_provider_headers(
    provider_id: str,
    api_key: Optional[str],
    *,
    chat_model_name: Optional[str] = None,
    json_body: bool = False,
) -> dict[str, str]:
    """Build request headers for remote provider APIs."""
    headers: dict[str, str] = {}
    if json_body:
        headers["Content-Type"] = "application/json"

    if provider_id == "anthropic" or chat_model_name == "AnthropicChatModel":
        headers["anthropic-version"] = "2023-06-01"
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _migrate_legacy_custom(
    providers: dict[str, ProviderSettings],
    custom_providers: dict[str, CustomProviderData],
) -> None:
    """Move ``providers["custom"]`` into ``custom_providers``."""
    old = providers.pop("custom", None)
    if old is None:
        return

    if "custom" in custom_providers:
        cpd = custom_providers["custom"]
        if old.api_key and not cpd.api_key:
            cpd.api_key = old.api_key
        if old.base_url and not cpd.base_url:
            cpd.base_url = old.base_url
        return

    if not old.base_url and not old.api_key:
        return

    custom_providers["custom"] = CustomProviderData(
        id="custom",
        name="Custom",
        default_base_url=old.base_url,
        api_key_prefix="",
        models=[],
        base_url=old.base_url,
        api_key=old.api_key,
    )


def _parse_new_format(raw: dict):
    """Returns ``(providers, custom_providers, active_llm)``."""
    providers: dict[str, ProviderSettings] = {}
    for key, value in raw.get("providers", {}).items():
        if isinstance(value, dict):
            providers[key] = ProviderSettings.model_validate(value)

    custom_providers: dict[str, CustomProviderData] = {}
    for key, value in raw.get("custom_providers", {}).items():
        if isinstance(value, dict):
            custom_providers[key] = CustomProviderData.model_validate(value)

    _migrate_legacy_custom(providers, custom_providers)

    llm_raw = raw.get("active_llm")
    active_llm = (
        ModelSlotConfig.model_validate(llm_raw)
        if isinstance(llm_raw, dict)
        else ModelSlotConfig()
    )
    return providers, custom_providers, active_llm


def _parse_legacy_format(raw: dict):
    """Returns ``(providers, custom_providers, active_llm)``."""
    providers: dict[str, ProviderSettings] = {}
    custom_providers: dict[str, CustomProviderData] = {}
    old_active = raw.get("active_provider", "")
    old_model = ""
    for key, value in raw.items():
        if key in ("active_provider", "active_llm"):
            continue
        if not isinstance(value, dict):
            continue
        model_val = value.pop("model", "")
        providers[key] = ProviderSettings.model_validate(value)
        if key == old_active and model_val:
            old_model = model_val
    _migrate_legacy_custom(providers, custom_providers)
    active_llm = (
        ModelSlotConfig(provider_id=old_active, model=old_model)
        if old_active
        else ModelSlotConfig()
    )
    return providers, custom_providers, active_llm


def _validate_active_llm(data: ProvidersData) -> None:
    """Clear active_llm if its provider is not configured or stale.

    For the special built-in provider ``ollama``, we additionally verify that
    the configured model still exists in the running Ollama daemon and clear
    the slot if it does not.
    """
    pid = data.active_llm.provider_id
    if not pid:
        return
    defn = PROVIDERS.get(pid)
    if defn is None or not data.is_configured(defn):
        data.active_llm = ModelSlotConfig()
        return

    # Extra validation for Ollama: ensure the active model still exists.
    if defn.id == "ollama" and data.active_llm.model:
        try:
            from ..providers.ollama_manager import OllamaModelManager

            s = data.providers.get("ollama")
            host = (
                _base_url_to_ollama_host(s.base_url)
                if s and s.base_url
                else None
            )
            names = {m.name for m in OllamaModelManager.list_models(host=host)}
            if data.active_llm.model not in names:
                data.active_llm = ModelSlotConfig()
        except Exception:
            # If Ollama is not reachable, leave the active slot as-is; the
            # runtime will surface any connectivity errors when used.
            pass


def _ensure_all_providers(providers: dict[str, ProviderSettings]) -> None:
    """Ensure every built-in has an entry; remove stale custom/local ones."""
    for pid, defn in PROVIDERS.items():
        if defn.is_custom or defn.is_local:
            # Custom and local providers don't need ProviderSettings entries
            providers.pop(pid, None)
            continue
        if pid not in providers:
            providers[pid] = ProviderSettings(base_url=defn.default_base_url)
        else:
            _ensure_base_url(providers[pid], defn)
        _normalize_special_provider_settings(pid, providers[pid])


# -- Load / Save --


def load_providers_json(path: Optional[Path] = None) -> ProvidersData:
    """Load providers.json, creating/repairing as needed."""
    if path is None:
        path = get_providers_json_path()
        _migrate_legacy_providers_json(path)
    if path.exists() and not path.is_file():
        raise IsADirectoryError(
            f"providers.json path exists but is not a regular file: {path}",
        )

    providers: dict[str, ProviderSettings] = {}
    custom_providers: dict[str, CustomProviderData] = {}
    active_llm = ModelSlotConfig()

    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw: dict = json.load(fh)
            if "providers" in raw and isinstance(raw["providers"], dict):
                providers, custom_providers, active_llm = _parse_new_format(
                    raw,
                )
            else:
                providers, custom_providers, active_llm = _parse_legacy_format(
                    raw,
                )
        except (json.JSONDecodeError, ValueError):
            providers = {}

    sync_custom_providers(custom_providers)
    sync_local_models()

    _ollama_s = providers.get("ollama")
    _ollama_host = (
        _base_url_to_ollama_host(_ollama_s.base_url)
        if _ollama_s and _ollama_s.base_url
        else None
    )
    sync_ollama_models(host=_ollama_host)
    _ensure_all_providers(providers)

    data = ProvidersData(
        providers=providers,
        custom_providers=custom_providers,
        active_llm=active_llm,
    )
    _validate_active_llm(data)
    save_providers_json(data, path)
    return data


def save_providers_json(
    data: ProvidersData,
    path: Optional[Path] = None,
) -> None:
    if path is None:
        path = get_providers_json_path()
        _migrate_legacy_providers_json(path)
    if path.exists() and not path.is_file():
        raise IsADirectoryError(
            f"providers.json path exists but is not a regular file: {path}",
        )
    _prepare_secret_parent(path)

    out: dict = {
        "providers": {
            pid: settings.model_dump(mode="json")
            for pid, settings in data.providers.items()
        },
        "custom_providers": {
            pid: cpd.model_dump(mode="json")
            for pid, cpd in data.custom_providers.items()
        },
        "active_llm": data.active_llm.model_dump(mode="json"),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    _chmod_best_effort(path, 0o600)


# -- Mutators --


def update_provider_settings(
    provider_id: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    chat_model: Optional[str] = None,
) -> ProvidersData:
    """Partially update a provider's settings. Returns updated state."""
    data = load_providers_json()
    cpd = data.custom_providers.get(provider_id)

    if cpd is not None:
        if api_key is not None:
            cpd.api_key = api_key
        if base_url is not None:
            cpd.base_url = base_url
        if chat_model is not None:
            cpd.chat_model = _normalize_chat_model_name(chat_model)
        if not cpd.base_url:
            cpd.base_url = cpd.default_base_url
        register_custom_provider(cpd)
    else:
        settings = data.providers.setdefault(provider_id, ProviderSettings())
        if api_key is not None:
            settings.api_key = api_key
        if base_url is not None:
            settings.base_url = base_url
        if not settings.base_url:
            defn = PROVIDERS.get(provider_id)
            if defn:
                settings.base_url = defn.default_base_url
        _normalize_special_provider_settings(provider_id, settings)

    if api_key == "" and data.active_llm.provider_id == provider_id:
        data.active_llm = ModelSlotConfig()

    save_providers_json(data)
    return data


def set_active_llm(provider_id: str, model: str) -> ProvidersData:
    data = load_providers_json()
    data.active_llm = ModelSlotConfig(provider_id=provider_id, model=model)
    save_providers_json(data)
    return data


# -- Query --


def _resolve_slot(
    slot: ModelSlotConfig,
    data: ProvidersData,
) -> Optional[ResolvedModelConfig]:
    pid = slot.provider_id
    if not pid or not slot.model:
        return None

    # Local providers don't need credentials or a providers.json entry
    defn = PROVIDERS.get(pid)
    if defn is not None and defn.is_local:
        return ResolvedModelConfig(
            model=slot.model,
            is_local=True,
        )

    if pid not in data.custom_providers and pid not in data.providers:
        return None
    base_url, api_key = data.get_credentials(pid)
    return ResolvedModelConfig(
        model=slot.model,
        base_url=base_url,
        api_key=api_key,
    )


def get_active_llm_config() -> Optional[ResolvedModelConfig]:
    data = load_providers_json()
    return _resolve_slot(data.active_llm, data)


# -- Utilities --


def mask_api_key(api_key: str, visible_chars: int = 4) -> str:
    if not api_key:
        return ""
    if len(api_key) <= visible_chars:
        return "*" * len(api_key)
    prefix = api_key[:3] if len(api_key) > 3 else ""
    suffix = api_key[-visible_chars:]
    hidden_len = len(api_key) - len(prefix) - visible_chars
    return f"{prefix}{'*' * max(hidden_len, 4)}{suffix}"


# -- Custom provider CRUD --


def create_custom_provider(
    provider_id: str,
    name: str,
    *,
    default_base_url: str = "",
    api_key_prefix: str = "",
    models: Optional[list[ModelInfo]] = None,
    chat_model: str = "OpenAIChatModel",
) -> ProvidersData:
    err = validate_custom_provider_id(provider_id)
    if err:
        raise ValueError(err)

    data = load_providers_json()
    if provider_id in data.custom_providers:
        raise ValueError(f"Custom provider '{provider_id}' already exists.")

    cpd = CustomProviderData(
        id=provider_id,
        name=name,
        default_base_url=default_base_url,
        api_key_prefix=api_key_prefix,
        models=models or [],
        base_url=default_base_url,
        chat_model=_normalize_chat_model_name(chat_model),
    )
    data.custom_providers[provider_id] = cpd
    register_custom_provider(cpd)
    save_providers_json(data)
    return data


def delete_custom_provider(provider_id: str) -> ProvidersData:
    if is_builtin(provider_id):
        raise ValueError(f"Cannot delete built-in provider '{provider_id}'.")

    data = load_providers_json()
    if provider_id not in data.custom_providers:
        raise ValueError(f"Custom provider '{provider_id}' not found.")

    del data.custom_providers[provider_id]
    unregister_custom_provider(provider_id)

    if data.active_llm.provider_id == provider_id:
        data.active_llm = ModelSlotConfig()

    save_providers_json(data)
    return data


def add_model(provider_id: str, model: ModelInfo) -> ProvidersData:
    data = load_providers_json()
    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    if is_builtin(provider_id):
        if provider_id == "ollama":
            raise ValueError(
                "Cannot add models to built-in provider 'ollama'. "
                "Ollama models are managed by the Ollama daemon itself.",
            )
        settings = data.providers.setdefault(
            provider_id,
            ProviderSettings(base_url=defn.default_base_url),
        )
        all_ids = {m.id for m in defn.models} | {
            m.id for m in settings.extra_models
        }
        if model.id in all_ids:
            raise ValueError(
                f"Model '{model.id}' already exists in provider "
                f"'{provider_id}'.",
            )
        settings.extra_models.append(model)
    else:
        cpd = data.custom_providers.get(provider_id)
        if cpd is None:
            raise ValueError(f"Custom provider '{provider_id}' not found.")
        if any(m.id == model.id for m in cpd.models):
            raise ValueError(
                f"Model '{model.id}' already exists in provider "
                f"'{provider_id}'.",
            )
        cpd.models.append(model)
        register_custom_provider(cpd)

    save_providers_json(data)
    return data


def remove_model(provider_id: str, model_id: str) -> ProvidersData:
    data = load_providers_json()
    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    if is_builtin(provider_id):
        if provider_id == "ollama":
            raise ValueError(
                "Cannot remove models from built-in provider 'ollama'. "
                "Ollama models are managed by the Ollama daemon itself.",
            )
        if any(m.id == model_id for m in defn.models):
            raise ValueError(
                f"Model '{model_id}' is a built-in model of "
                f"'{provider_id}' and cannot be removed.",
            )
        settings = data.providers.get(provider_id)
        if settings is None:
            raise ValueError(
                f"Model '{model_id}' not found in provider '{provider_id}'.",
            )
        original_len = len(settings.extra_models)
        settings.extra_models = [
            m for m in settings.extra_models if m.id != model_id
        ]
        if len(settings.extra_models) == original_len:
            raise ValueError(
                f"Model '{model_id}' not found in provider '{provider_id}'.",
            )
    else:
        cpd = data.custom_providers.get(provider_id)
        if cpd is None:
            raise ValueError(f"Custom provider '{provider_id}' not found.")
        original_len = len(cpd.models)
        cpd.models = [m for m in cpd.models if m.id != model_id]
        if len(cpd.models) == original_len:
            raise ValueError(
                f"Model '{model_id}' not found in provider '{provider_id}'.",
            )
        register_custom_provider(cpd)

    if (
        data.active_llm.provider_id == provider_id
        and data.active_llm.model == model_id
    ):
        data.active_llm = ModelSlotConfig()

    save_providers_json(data)
    return data


def _dedupe_models(models: list[ModelInfo]) -> list[ModelInfo]:
    """Keep insertion order while deduplicating by model id."""
    out: list[ModelInfo] = []
    seen: set[str] = set()
    for model in models:
        model_id = (model.id or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        name = (model.name or "").strip() or model_id
        out.append(ModelInfo(id=model_id, name=name))
    return out


def _merge_discovered_models(
    provider_id: str,
    discovered: list[ModelInfo],
    data: ProvidersData,
) -> int:
    """Merge discovered models into provider config and return added count."""
    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    discovered = _dedupe_models(discovered)
    if not discovered:
        return 0

    added_count = 0

    if is_builtin(provider_id):
        # Ollama models come from daemon sync and should not be persisted here.
        if provider_id == "ollama":
            return 0

        settings = data.providers.setdefault(
            provider_id,
            ProviderSettings(base_url=defn.default_base_url),
        )
        existing_ids = {m.id for m in defn.models} | {
            m.id for m in settings.extra_models
        }
        for model in discovered:
            if model.id in existing_ids:
                continue
            settings.extra_models.append(model)
            existing_ids.add(model.id)
            added_count += 1
        return added_count

    cpd = data.custom_providers.get(provider_id)
    if cpd is None:
        raise ValueError(f"Custom provider '{provider_id}' not found.")

    existing_ids = {m.id for m in cpd.models}
    for model in discovered:
        if model.id in existing_ids:
            continue
        cpd.models.append(model)
        existing_ids.add(model.id)
        added_count += 1

    if added_count > 0:
        register_custom_provider(cpd)

    return added_count


# pylint: disable=R0911,R0912,R0915
async def discover_provider_models(
    provider_id: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    chat_model: Optional[str] = None,
) -> dict[str, Any]:
    """Discover available models from a provider's /models endpoint.

    Returns:
        dict with keys:
        - success: bool
        - message: str
        - models: list[ModelInfo]
        - added_count: int
    """
    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    # Local providers are already represented by local model registry.
    if defn.is_local:
        return {
            "success": True,
            "message": f"{defn.name} uses local models; no remote discovery.",
            "models": list(defn.models),
            "added_count": 0,
        }

    # Ollama model list comes from daemon (possibly remote).
    if provider_id == "ollama":
        try:
            from .ollama_manager import OllamaModelManager

            host = get_ollama_host()
            models = [
                ModelInfo(id=m.name, name=m.name)
                for m in OllamaModelManager.list_models(host=host)
            ]
            return {
                "success": True,
                "message": f"Discovered {len(models)} Ollama model(s).",
                "models": models,
                "added_count": 0,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to query Ollama models: {str(e)}",
                "models": [],
                "added_count": 0,
            }

    try:
        import httpx
    except ImportError:
        return {
            "success": False,
            "message": "httpx library is not installed.",
            "models": [],
            "added_count": 0,
        }

    data = load_providers_json()
    try:
        chat_model_name = _resolve_chat_model_name(
            provider_id,
            data,
            chat_model,
        )
    except ValueError as e:
        return {
            "success": False,
            "message": str(e),
            "models": [],
            "added_count": 0,
        }
    saved_base_url, saved_api_key = data.get_credentials(provider_id)
    resolved_base_url = (
        base_url or saved_base_url or defn.default_base_url
    ).strip()
    resolved_api_key = saved_api_key if api_key is None else api_key

    if not resolved_base_url:
        return {
            "success": False,
            "message": "Base URL is required to discover models.",
            "models": [],
            "added_count": 0,
        }

    endpoint = f"{resolved_base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json"}
    headers.update(
        _build_remote_provider_headers(
            provider_id,
            resolved_api_key,
            chat_model_name=chat_model_name,
        ),
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(endpoint, headers=headers)
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to provider. Please check Base URL.",
            "models": [],
            "added_count": 0,
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Model discovery timed out.",
            "models": [],
            "added_count": 0,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Model discovery failed: {str(e)}",
            "models": [],
            "added_count": 0,
        }

    if response.status_code in (401, 403):
        return {
            "success": False,
            "message": "API key is invalid or has insufficient permission.",
            "models": [],
            "added_count": 0,
        }
    if response.status_code != 200:
        msg = f"Provider returned {response.status_code} when listing models."
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("error") or payload.get("message")
                if detail:
                    msg = f"{msg} {detail}"
        except Exception:
            pass
        return {
            "success": False,
            "message": msg,
            "models": [],
            "added_count": 0,
        }

    try:
        payload = response.json()
    except Exception:
        return {
            "success": False,
            "message": "Provider returned non-JSON response for /models.",
            "models": [],
            "added_count": 0,
        }

    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {
            "success": False,
            "message": "Provider /models response format is unsupported.",
            "models": [],
            "added_count": 0,
        }

    discovered: list[ModelInfo] = []
    for row in rows:
        if isinstance(row, str):
            model_id = row.strip()
            if model_id:
                discovered.append(ModelInfo(id=model_id, name=model_id))
            continue
        if not isinstance(row, dict):
            continue

        model_id = str(row.get("id") or row.get("name") or "").strip()
        if not model_id:
            continue
        model_name = (
            str(
                row.get("name") or row.get("display_name") or model_id,
            ).strip()
            or model_id
        )
        discovered.append(ModelInfo(id=model_id, name=model_name))

    discovered = _dedupe_models(discovered)
    if not discovered:
        return {
            "success": True,
            "message": "No models discovered from provider /models endpoint.",
            "models": [],
            "added_count": 0,
        }

    latest = load_providers_json()
    added_count = _merge_discovered_models(provider_id, discovered, latest)
    if added_count > 0:
        save_providers_json(latest)

    return {
        "success": True,
        "message": (
            f"Discovered {len(discovered)} model(s), "
            f"added {added_count} new model(s)."
        ),
        "models": discovered,
        "added_count": added_count,
    }


# pylint: disable=too-many-return-statements,too-many-branches
# pylint: disable=too-many-statements
async def test_provider_connection(
    provider_id: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    chat_model: Optional[str] = None,
) -> dict[str, Any]:
    """Test if a provider's URL and API key are valid.

    (without testing a specific model).

    This tests network connectivity and authentication at the provider
    level.

    Args:
        provider_id: The provider identifier to test
        api_key: Optional API key to use (overrides saved config)
        base_url: Optional Base URL to use (overrides saved config)

    Returns:
        dict with keys:
        - success: bool - Whether the connection test passed
        - message: str - Human-readable result message

    Raises:
        ValueError: If provider is not found
    """
    try:
        import httpx
    except ImportError:
        return {
            "success": False,
            "message": "httpx library is not installed.",
        }

    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    data = load_providers_json()

    # Local providers don't need credentials test
    if defn.is_local:
        # For local providers, just check if models are available
        if len(defn.models) > 0:
            return {
                "success": True,
                "message": (
                    f"{defn.name} is ready with {len(defn.models)} model(s)."
                ),
            }
        else:
            return {
                "success": False,
                "message": f"{defn.name} has no models available.",
            }

    # Ollama special handling - check daemon connectivity
    if provider_id == "ollama":
        try:
            from .ollama_manager import OllamaModelManager

            effective_url = base_url
            if not effective_url:
                s = data.providers.get("ollama")
                effective_url = s.base_url if s else None
            host = (
                _base_url_to_ollama_host(effective_url)
                if effective_url
                else None
            )
            models = OllamaModelManager.list_models(host=host)
            return {
                "success": True,
                "message": (
                    f"Ollama daemon is reachable with {len(models)} model(s)."
                ),
            }
        except ImportError:
            return {
                "success": False,
                "message": "Ollama Python SDK is not installed.",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Ollama daemon is not reachable: {str(e)}",
            }

    # Remote providers - test API credentials
    # Use provided credentials or fall back to saved config
    if not base_url or not api_key:
        saved_base_url, saved_api_key = data.get_credentials(provider_id)
        if not base_url:
            base_url = saved_base_url or defn.default_base_url
        if not api_key:
            api_key = saved_api_key

    # If still no credentials (and provider requires them), fail
    if not api_key and not base_url:
        # Some providers might work without key if local custom,
        # but generally we need something
        if not data.is_configured(defn) and not (api_key or base_url):
            return {
                "success": False,
                "message": f"{defn.name} not configured. Please add API key.",
            }

    # Get chat model class for this provider
    try:
        chat_model_class_name = _resolve_chat_model_name(
            provider_id,
            data,
            chat_model,
        )
    except ValueError as e:
        return {
            "success": False,
            "message": str(e),
        }
    try:
        chat_model_class = get_chat_model_class(chat_model_class_name)
    except ValueError as e:
        return {
            "success": False,
            "message": str(e),
        }

    # Use a lightweight test approach: try to make a simple API call
    # For OpenAI-compatible APIs, we can use the models list endpoint
    # This validates URL + Key without needing a specific model ID
    try:
        # Most OpenAI-compatible APIs have a /models endpoint
        # This is a lightweight way to test credentials
        test_url = f"{base_url.rstrip('/')}/models"

        headers = _build_remote_provider_headers(
            provider_id,
            api_key,
            chat_model_name=chat_model_class_name,
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(test_url, headers=headers)

            if response.status_code in (401, 403):
                return {
                    "success": False,
                    "message": f"{defn.name} API key is invalid or expired.",
                }
            elif response.status_code == 404:
                # Some providers don't have /models endpoint
                # try model instantiation
                pass
            elif response.status_code >= 500:
                return {
                    "success": False,
                    "message": (
                        f"{defn.name} server error: {response.status_code}"
                    ),
                }
            elif response.status_code == 200:
                return {
                    "success": True,
                    "message": f"{defn.name} URL and API key are valid.",
                }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": (
                f"Cannot connect to {defn.name}. Please check the Base URL."
            ),
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": f"Connection to {defn.name} timed out.",
        }
    except Exception:
        # If /models endpoint fails,
        # fall through to model instantiation test
        pass

    # Fallback: try to instantiate a chat model
    # (may fail if no valid model exists)
    # Use the first available model or a common one
    test_model = None
    if len(defn.models) > 0:
        test_model = defn.models[0].id
    else:
        # Provider-specific fallback models
        fallback_models = {
            "openai": "gpt-3.5-turbo",
            "dashscope": "qwen-max",
            "modelscope": "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "aliyun-codingplan": "qwen3.5-plus",
            "anthropic": "claude-3-5-sonnet-latest",
        }
        if chat_model_class_name == "AnthropicChatModel":
            test_model = fallback_models["anthropic"]
        else:
            test_model = fallback_models.get(provider_id, "gpt-3.5-turbo")

    try:
        # Try to instantiate the model with the configured credentials
        # Note: This part might still be sync if the SDK init is sync,
        # but usually init is fast.
        chat_model_class(
            model_name=test_model,
            api_key=api_key,
            stream=True,
            client_kwargs={"base_url": base_url} if base_url else {},
        )

        return {
            "success": True,
            "message": f"{defn.name} URL and API key are valid.",
        }
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "authentication" in error_msg.lower():
            return {
                "success": False,
                "message": f"{defn.name} API key is invalid.",
            }
        elif "connection" in error_msg.lower():
            return {
                "success": False,
                "message": (
                    f"Cannot connect to {defn.name}. "
                    f"Please check the Base URL."
                ),
            }
        else:
            return {
                "success": False,
                "message": (
                    f"{defn.name} configuration test failed: {error_msg}"
                ),
            }


# pylint: disable=too-many-return-statements,too-many-branches
async def test_model_connection(
    provider_id: str,
    model_id: str,
) -> dict[str, Any]:
    """Test if a specific model can be used with the configured provider.

    This tests the complete call chain: URL + Key + ModelID.

    Args:
        provider_id: The provider identifier
        model_id: The specific model ID to test

    Returns:
        dict with keys:
        - success: bool - Whether the model test passed
        - message: str - Human-readable result message

    Raises:
        ValueError: If provider is not found
    """
    try:
        import httpx
    except ImportError:
        return {
            "success": False,
            "message": "httpx library is not installed.",
        }

    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    data = load_providers_json()

    # Local providers
    if defn.is_local:
        # Check if the specific model exists
        for model in defn.models:
            if model.id == model_id:
                return {
                    "success": True,
                    "message": f"Model '{model.name}' is available.",
                }
        return {
            "success": False,
            "message": f"Model '{model_id}' is not available.",
        }

    # Ollama special handling
    if provider_id == "ollama":
        try:
            from .ollama_manager import OllamaModelManager

            s = data.providers.get("ollama")
            host = (
                _base_url_to_ollama_host(s.base_url)
                if s and s.base_url
                else None
            )
            models = OllamaModelManager.list_models(host=host)
            for model in models:
                if model.name == model_id:
                    return {
                        "success": True,
                        "message": (
                            f"Model '{model_id}' is available in Ollama."
                        ),
                    }
            return {
                "success": False,
                "message": f"Model '{model_id}' is not found in Ollama.",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Ollama error: {str(e)}",
            }

    # Remote providers - test the complete call chain
    if not data.is_configured(defn):
        return {
            "success": False,
            "message": (
                f"{defn.name} is not configured. Please add API key first."
            ),
        }

    base_url, api_key = data.get_credentials(provider_id)
    try:
        uses_anthropic_protocol = _uses_anthropic_protocol(provider_id, data)
        chat_model_name = _resolve_chat_model_name(provider_id, data)
    except ValueError as e:
        return {
            "success": False,
            "message": str(e),
        }

    # For remote providers, use direct API call for more reliable testing
    if uses_anthropic_protocol:
        chat_url = f"{base_url.rstrip('/')}/messages"
        headers = _build_remote_provider_headers(
            provider_id,
            api_key,
            chat_model_name=chat_model_name,
            json_body=True,
        )
        test_payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
    else:
        # Most OpenAI-compatible APIs use the chat completions endpoint
        chat_url = f"{base_url.rstrip('/')}/chat/completions"
        headers = _build_remote_provider_headers(
            provider_id,
            api_key,
            chat_model_name=chat_model_name,
            json_body=True,
        )
        test_payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                chat_url,
                json=test_payload,
                headers=headers,
            )

            if response.status_code in (401, 403):
                return {
                    "success": False,
                    "message": "API key is invalid or expired.",
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "message": (
                        f"Model '{model_id}' does not exist "
                        f"or is not available."
                    ),
                }
            elif response.status_code == 400:
                # Check error details for invalid model
                try:
                    error_data = response.json()
                    if "model" in str(error_data).lower():
                        return {
                            "success": False,
                            "message": (
                                f"Model '{model_id}' is invalid "
                                f"or not supported."
                            ),
                        }
                    return {
                        "success": False,
                        "message": f"Bad request: {error_data}",
                    }
                except Exception:
                    return {
                        "success": False,
                        "message": "Bad request (400). Model may be invalid.",
                    }
            elif response.status_code >= 500:
                return {
                    "success": False,
                    "message": f"Server error: {response.status_code}",
                }
            elif response.status_code == 200:
                # Successfully called the model!
                try:
                    result = response.json()
                    # Check if there's an error in the response body
                    if isinstance(result, dict) and "error" in result:
                        error_info = result["error"]
                        error_msg = error_info.get("message", str(error_info))
                        if (
                            "model" in error_msg.lower()
                            or "not found" in error_msg.lower()
                        ):
                            return {
                                "success": False,
                                "message": (
                                    f"Model '{model_id}' error: {error_msg}"
                                ),
                            }
                        return {
                            "success": False,
                            "message": f"API returned error: {error_msg}",
                        }

                    # Verify we got actual choices/content
                    if (
                        uses_anthropic_protocol
                        and "content" in result
                        and isinstance(result["content"], list)
                        and len(result["content"]) > 0
                    ):
                        return {
                            "success": True,
                            "message": (
                                f"Model '{model_id}' is working correctly."
                            ),
                        }

                    if "choices" in result and len(result["choices"]) > 0:
                        return {
                            "success": True,
                            "message": (
                                f"Model '{model_id}' is working correctly."
                            ),
                        }
                    else:
                        # Some APIs return 200 but with no choices
                        # (e.g., processing error)
                        return {
                            "success": False,
                            "message": (
                                f"Model '{model_id}' returned no content. "
                                f"It may be unavailable."
                            ),
                        }
                except Exception:
                    # If we can't parse JSON but got 200,
                    # consider it a success
                    return {
                        "success": True,
                        "message": (
                            f"Model '{model_id}' responded "
                            f"(connection test passed)."
                        ),
                    }
            else:
                return {
                    "success": False,
                    "message": (
                        f"Unexpected response code: {response.status_code}"
                    ),
                }

    except httpx.ConnectError as e:
        return {
            "success": False,
            "message": (
                f"Cannot connect to {defn.name}. Check the Base URL: {str(e)}"
            ),
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": f"Connection to {defn.name} timed out.",
        }
    except Exception as e:
        error_msg = str(e)
        return {
            "success": False,
            "message": f"Model test failed: {error_msg}",
        }
