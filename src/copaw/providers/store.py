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


def get_providers_json_path() -> Path:
    """Return providers.json path under SECRET_DIR."""
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


# pylint: disable=too-many-return-statements,too-many-branches
# pylint: disable=too-many-statements
async def test_provider_connection(
    provider_id: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
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

            models = OllamaModelManager.list_models()
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
            base_url = saved_base_url
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
    chat_model_class_name = get_provider_chat_model(provider_id, data)
    chat_model_class = get_chat_model_class(chat_model_class_name)

    # Use a lightweight test approach: try to make a simple API call
    # For OpenAI-compatible APIs, we can use the models list endpoint
    # This validates URL + Key without needing a specific model ID
    try:
        # Most OpenAI-compatible APIs have a /models endpoint
        # This is a lightweight way to test credentials
        test_url = f"{base_url.rstrip('/')}/models"

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(test_url, headers=headers)

            if response.status_code == 401:
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
        }
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

            models = OllamaModelManager.list_models()
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

    # For remote providers, use direct API call for more reliable testing
    # Most OpenAI-compatible APIs use the chat completions endpoint
    chat_url = f"{base_url.rstrip('/')}/chat/completions"

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Prepare a minimal test request
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

            if response.status_code == 401:
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
