# -*- coding: utf-8 -*-
"""Reading and writing provider configuration (providers.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

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
    is_builtin,
    register_custom_provider,
    sync_custom_providers,
    sync_local_models,
    sync_ollama_models,
    unregister_custom_provider,
    validate_custom_provider_id,
)

_PROVIDERS_DIR = Path(__file__).resolve().parent
_PROVIDERS_JSON = _PROVIDERS_DIR / "providers.json"


def get_providers_json_path() -> Path:
    return _PROVIDERS_JSON


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

            names = {m.name for m in OllamaModelManager.list_models()}
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
    sync_ollama_models()
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
    path.parent.mkdir(parents=True, exist_ok=True)

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


# -- Mutators --


def update_provider_settings(
    provider_id: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ProvidersData:
    """Partially update a provider's settings. Returns updated state."""
    data = load_providers_json()
    cpd = data.custom_providers.get(provider_id)

    if cpd is not None:
        if api_key is not None:
            cpd.api_key = api_key
        if base_url is not None:
            cpd.base_url = base_url
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
    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    data = load_providers_json()

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
    defn = PROVIDERS.get(provider_id)
    if defn is None:
        raise ValueError(f"Provider '{provider_id}' not found.")

    data = load_providers_json()

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
