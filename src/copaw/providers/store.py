# -*- coding: utf-8 -*-
"""Reading and writing provider configuration (providers.json)."""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Optional

from .models import (
    CustomProviderData,
    ModelInfo,
    ModelSlotConfig,
    ProviderSettings,
    ProvidersData,
    ResolvedModelConfig,
    VisionAudioSettings,
    VisionImageSettings,
    VisionSettings,
    VisionVideoSettings,
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

# Cache for OpenAI-compatible /v1/models responses (key: (base_url, normalized_api_key)).
MODELS_CACHE_TTL_SEC = 600
_openai_models_cache: dict[tuple[str, str], tuple[list[ModelInfo], float]] = {}

_PROVIDERS_DIR = Path(__file__).resolve().parent
_PROVIDERS_JSON = _PROVIDERS_DIR / "providers.json"
_LOG = logging.getLogger(__name__)


def _normalize_api_key(api_key: str) -> str:
    """Normalize API key input.

    Accept both raw tokens and values like ``Bearer <token>``.
    """
    key = (api_key or "").strip()
    lower = key.lower()
    if lower.startswith("bearer "):
        key = key[7:].strip()
    return key


def get_providers_json_path() -> Path:
    return _PROVIDERS_JSON


def _ensure_base_url(settings: ProviderSettings, defn) -> None:
    if not settings.base_url and defn.default_base_url:
        settings.base_url = defn.default_base_url


def _build_models_url(base_url: str) -> str:
    """Build OpenAI-compatible models endpoint from a provider base URL."""
    clean = (base_url or "").strip().rstrip("/")
    if not clean:
        return ""
    parsed = urlsplit(clean)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        models_path = f"{path}/models"
    else:
        models_path = f"{path}/v1/models"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            models_path,
            parsed.query,
            parsed.fragment,
        ),
    )


def _fetch_openai_models(
    base_url: str,
    api_key: str,
    *,
    provider_id: str = "",
    use_cache: bool = True,
) -> list[ModelInfo]:
    """Fetch model list from OpenAI-compatible endpoint.

    Results are cached for MODELS_CACHE_TTL_SEC (600s) per (base_url, api_key).
    Pass use_cache=False to force a fresh fetch (e.g. after saving provider config).
    Returns an empty list if fetching/parsing fails.
    """
    endpoint = _build_models_url(base_url)
    if not endpoint:
        return []

    normalized_key = _normalize_api_key(api_key)
    cache_key = (base_url.strip().rstrip("/"), normalized_key)
    if use_cache:
        entry = _openai_models_cache.get(cache_key)
        if entry is not None and time.monotonic() <= entry[1]:
            return list(entry[0])

    headers = {"Accept": "application/json"}
    if normalized_key:
        headers["Authorization"] = f"Bearer {normalized_key}"

    try:
        req = Request(endpoint, headers=headers, method="GET")
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:
        if provider_id:
            _LOG.warning(
                "Failed to fetch models for provider '%s' from %s: %s",
                provider_id,
                endpoint,
                exc,
            )
        else:
            _LOG.warning("Failed to fetch models from %s: %s", endpoint, exc)
        return []

    data = payload.get("data")
    if not isinstance(data, list):
        return []

    models: list[ModelInfo] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        mid = item.get("id")
        if not isinstance(mid, str):
            continue
        mid = mid.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        models.append(ModelInfo(id=mid, name=mid))

    if use_cache:
        _openai_models_cache[cache_key] = (
            models,
            time.monotonic() + MODELS_CACHE_TTL_SEC,
        )
    return models


def _refresh_custom_provider_models(
    custom_providers: dict[str, CustomProviderData],
) -> None:
    """Refresh models for configured custom providers.

    Best-effort only: keep existing models when fetch fails or returns empty.
    """
    for provider_id, cpd in custom_providers.items():
        base_url = (cpd.base_url or cpd.default_base_url or "").strip()
        if not base_url:
            continue
        fetched_models = _fetch_openai_models(
            base_url,
            cpd.api_key,
            provider_id=provider_id,
        )
        if fetched_models:
            cpd.models = fetched_models


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
    """Returns parsed providers.json fields for the current schema."""
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
    vlm_raw = raw.get("active_vlm")
    active_vlm = (
        ModelSlotConfig.model_validate(vlm_raw)
        if isinstance(vlm_raw, dict)
        else ModelSlotConfig()
    )
    fallbacks_raw = raw.get("active_vlm_fallbacks")
    active_vlm_fallbacks: list[ModelSlotConfig] = []
    if isinstance(fallbacks_raw, list):
        for item in fallbacks_raw:
            if isinstance(item, dict):
                active_vlm_fallbacks.append(
                    ModelSlotConfig.model_validate(item),
                )
    vision_raw = raw.get("vision")
    vision = (
        VisionSettings.model_validate(vision_raw)
        if isinstance(vision_raw, dict)
        else VisionSettings()
    )
    return (
        providers,
        custom_providers,
        active_llm,
        active_vlm,
        active_vlm_fallbacks,
        vision,
    )


def _parse_legacy_format(raw: dict):
    """Returns parsed providers.json fields for legacy schema."""
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
    return (
        providers,
        custom_providers,
        active_llm,
        ModelSlotConfig(),
        [],
        VisionSettings(),
    )


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


def _validate_active_vlm(data: ProvidersData) -> None:
    """Clear active_vlm/fallbacks if provider settings are stale."""
    pid = data.active_vlm.provider_id
    if pid:
        defn = PROVIDERS.get(pid)
        if defn is None or not data.is_configured(defn):
            data.active_vlm = ModelSlotConfig()

    valid_fallbacks: list[ModelSlotConfig] = []
    for fallback in data.active_vlm_fallbacks:
        fb_pid = fallback.provider_id
        if not fb_pid:
            continue
        defn = PROVIDERS.get(fb_pid)
        if defn is None or not data.is_configured(defn):
            continue
        valid_fallbacks.append(fallback)
    data.active_vlm_fallbacks = valid_fallbacks


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


# -- Load / Save --


def load_providers_json(path: Optional[Path] = None) -> ProvidersData:
    """Load providers.json, creating/repairing as needed."""
    if path is None:
        path = get_providers_json_path()

    providers: dict[str, ProviderSettings] = {}
    custom_providers: dict[str, CustomProviderData] = {}
    active_llm = ModelSlotConfig()
    active_vlm = ModelSlotConfig()
    active_vlm_fallbacks: list[ModelSlotConfig] = []
    vision = VisionSettings()

    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw: dict = json.load(fh)
            if "providers" in raw and isinstance(raw["providers"], dict):
                (
                    providers,
                    custom_providers,
                    active_llm,
                    active_vlm,
                    active_vlm_fallbacks,
                    vision,
                ) = _parse_new_format(raw)
            else:
                (
                    providers,
                    custom_providers,
                    active_llm,
                    active_vlm,
                    active_vlm_fallbacks,
                    vision,
                ) = _parse_legacy_format(raw)
        except (json.JSONDecodeError, ValueError):
            providers = {}

    _refresh_custom_provider_models(custom_providers)
    sync_custom_providers(custom_providers)
    sync_local_models()
    sync_ollama_models()
    _ensure_all_providers(providers)

    data = ProvidersData(
        providers=providers,
        custom_providers=custom_providers,
        active_llm=active_llm,
        active_vlm=active_vlm,
        active_vlm_fallbacks=active_vlm_fallbacks,
        vision=vision,
    )
    _validate_active_llm(data)
    _validate_active_vlm(data)
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
        "active_vlm": data.active_vlm.model_dump(mode="json"),
        "active_vlm_fallbacks": [
            slot.model_dump(mode="json")
            for slot in data.active_vlm_fallbacks
        ],
        "vision": data.vision.model_dump(mode="json"),
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
            cpd.api_key = _normalize_api_key(api_key)
        if base_url is not None:
            cpd.base_url = base_url.strip()
        if not cpd.base_url:
            cpd.base_url = cpd.default_base_url
        fetched_models = _fetch_openai_models(
            cpd.base_url,
            cpd.api_key,
            provider_id=provider_id,
            use_cache=False,
        )
        if fetched_models:
            cpd.models = fetched_models
        register_custom_provider(cpd)
    else:
        settings = data.providers.setdefault(provider_id, ProviderSettings())
        if api_key is not None:
            settings.api_key = _normalize_api_key(api_key)
        if base_url is not None:
            settings.base_url = base_url.strip()
        if not settings.base_url:
            defn = PROVIDERS.get(provider_id)
            if defn:
                settings.base_url = defn.default_base_url

    if api_key == "" and data.active_llm.provider_id == provider_id:
        data.active_llm = ModelSlotConfig()
    if api_key == "" and data.active_vlm.provider_id == provider_id:
        data.active_vlm = ModelSlotConfig()
    data.active_vlm_fallbacks = [
        slot for slot in data.active_vlm_fallbacks if slot.provider_id != provider_id
    ]

    save_providers_json(data)
    return data


def set_active_llm(provider_id: str, model: str) -> ProvidersData:
    data = load_providers_json()
    data.active_llm = ModelSlotConfig(provider_id=provider_id, model=model)
    save_providers_json(data)
    return data


def set_active_vlm(provider_id: str, model: str) -> ProvidersData:
    data = load_providers_json()
    data.active_vlm = ModelSlotConfig(provider_id=provider_id, model=model)
    save_providers_json(data)
    return data


def set_active_vlm_fallbacks(
    fallbacks: list[ModelSlotConfig],
) -> ProvidersData:
    data = load_providers_json()
    data.active_vlm_fallbacks = list(fallbacks)
    save_providers_json(data)
    return data


def _normalize_attachments_mode(value: str | None) -> str | None:
    if value is None:
        return None
    mode = value.strip().lower()
    return mode if mode in {"first", "all"} else "first"


def _update_vision_capability_settings(
    *,
    capability: str,
    updates: dict,
) -> ProvidersData:
    data = load_providers_json()
    current = getattr(data.vision, capability)
    payload: dict = current.model_dump(mode="json")
    payload.update(updates)
    model_type = type(current)
    setattr(data.vision, capability, model_type.model_validate(payload))
    save_providers_json(data)
    return data


def _get_vision_capability_settings(capability: str):
    data = load_providers_json()
    return getattr(data.vision, capability)


def update_vision_image_settings(
    *,
    enabled: bool | None = None,
    attachments_mode: str | None = None,
    max_images: int | None = None,
    prompt_override: str | None = None,
    timeout_seconds: int | None = None,
    max_output_chars: int | None = None,
) -> ProvidersData:
    """Partially update vision.image settings in providers.json."""
    updates: dict = {}
    if enabled is not None:
        updates["enabled"] = bool(enabled)
    mode = _normalize_attachments_mode(attachments_mode)
    if mode is not None:
        updates["attachments_mode"] = mode
    if max_images is not None:
        updates["max_images"] = max_images
    if prompt_override is not None:
        updates["prompt_override"] = prompt_override
    if timeout_seconds is not None:
        updates["timeout_seconds"] = timeout_seconds
    if max_output_chars is not None:
        updates["max_output_chars"] = max_output_chars
    return _update_vision_capability_settings(capability="image", updates=updates)


def get_vision_image_settings() -> VisionImageSettings:
    """Return current vision.image settings."""
    return _get_vision_capability_settings("image")


def update_vision_audio_settings(
    *,
    enabled: bool | None = None,
    attachments_mode: str | None = None,
    max_items: int | None = None,
    prompt_override: str | None = None,
    timeout_seconds: int | None = None,
    max_output_chars: int | None = None,
) -> ProvidersData:
    """Partially update vision.audio settings in providers.json."""
    updates: dict = {}
    if enabled is not None:
        updates["enabled"] = bool(enabled)
    mode = _normalize_attachments_mode(attachments_mode)
    if mode is not None:
        updates["attachments_mode"] = mode
    if max_items is not None:
        updates["max_items"] = max_items
    if prompt_override is not None:
        updates["prompt_override"] = prompt_override
    if timeout_seconds is not None:
        updates["timeout_seconds"] = timeout_seconds
    if max_output_chars is not None:
        updates["max_output_chars"] = max_output_chars
    return _update_vision_capability_settings(capability="audio", updates=updates)


def get_vision_audio_settings() -> VisionAudioSettings:
    """Return current vision.audio settings."""
    return _get_vision_capability_settings("audio")


def update_vision_video_settings(
    *,
    enabled: bool | None = None,
    attachments_mode: str | None = None,
    max_items: int | None = None,
    prompt_override: str | None = None,
    timeout_seconds: int | None = None,
    max_output_chars: int | None = None,
) -> ProvidersData:
    """Partially update vision.video settings in providers.json."""
    updates: dict = {}
    if enabled is not None:
        updates["enabled"] = bool(enabled)
    mode = _normalize_attachments_mode(attachments_mode)
    if mode is not None:
        updates["attachments_mode"] = mode
    if max_items is not None:
        updates["max_items"] = max_items
    if prompt_override is not None:
        updates["prompt_override"] = prompt_override
    if timeout_seconds is not None:
        updates["timeout_seconds"] = timeout_seconds
    if max_output_chars is not None:
        updates["max_output_chars"] = max_output_chars
    return _update_vision_capability_settings(capability="video", updates=updates)


def get_vision_video_settings() -> VisionVideoSettings:
    """Return current vision.video settings."""
    return _get_vision_capability_settings("video")


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
            provider_id=pid,
            model=slot.model,
            is_local=True,
        )

    if pid not in data.custom_providers and pid not in data.providers:
        return None
    base_url, api_key = data.get_credentials(pid)
    return ResolvedModelConfig(
        provider_id=pid,
        model=slot.model,
        base_url=base_url,
        api_key=api_key,
    )


def get_active_llm_config() -> Optional[ResolvedModelConfig]:
    data = load_providers_json()
    return _resolve_slot(data.active_llm, data)


def get_active_vlm_config() -> Optional[ResolvedModelConfig]:
    data = load_providers_json()
    return _resolve_slot(data.active_vlm, data)


def get_active_vlm_fallback_configs() -> list[ResolvedModelConfig]:
    data = load_providers_json()
    out: list[ResolvedModelConfig] = []
    for slot in data.active_vlm_fallbacks:
        cfg = _resolve_slot(slot, data)
        if cfg is not None:
            out.append(cfg)
    return out


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
    api_key: str = "",
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
        default_base_url=default_base_url.strip(),
        api_key_prefix=api_key_prefix,
        models=models or [],
        base_url=default_base_url.strip(),
        api_key=_normalize_api_key(api_key),
    )
    fetched_models = _fetch_openai_models(
        cpd.base_url,
        cpd.api_key,
        provider_id=provider_id,
        use_cache=False,
    )
    if fetched_models:
        cpd.models = fetched_models
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
    if data.active_vlm.provider_id == provider_id:
        data.active_vlm = ModelSlotConfig()
    data.active_vlm_fallbacks = [
        slot for slot in data.active_vlm_fallbacks if slot.provider_id != provider_id
    ]

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
    if (
        data.active_vlm.provider_id == provider_id
        and data.active_vlm.model == model_id
    ):
        data.active_vlm = ModelSlotConfig()
    data.active_vlm_fallbacks = [
        slot
        for slot in data.active_vlm_fallbacks
        if not (slot.provider_id == provider_id and slot.model == model_id)
    ]

    save_providers_json(data)
    return data
