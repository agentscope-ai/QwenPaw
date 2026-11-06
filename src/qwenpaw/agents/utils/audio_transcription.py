# -*- coding: utf-8 -*-
"""Audio transcription utility.

Transcribes audio files to text using either:
- An OpenAI-compatible ``/v1/audio/transcriptions`` endpoint (Whisper API), or
- The locally installed ``openai-whisper`` Python library (Local Whisper).

Transcription is only attempted when explicitly enabled via the
``transcription_provider_type`` config setting.  The default is ``"disabled"``.
"""

import logging
from typing import List, Optional, Tuple
from ...utils.io_utils import run_sync_io

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Provider helpers
# ------------------------------------------------------------------


def _url_for_provider(provider) -> Optional[Tuple[str, str]]:
    """Return ``(base_url, api_key)`` if *provider* can serve transcription.

    Supports providers that do not require an API key (e.g. local Ollama).
    """
    from ...providers.openai_provider import OpenAIProvider
    from ...providers.ollama_provider import OllamaProvider

    if isinstance(provider, OpenAIProvider):
        requires_key = getattr(provider, "require_api_key", True)
        key = provider.api_key or ""
        if requires_key and not key:
            return None
        base = provider.base_url.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return (base, key or "")
    if isinstance(provider, OllamaProvider):
        base = provider.base_url.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return (base, provider.api_key or "")
    return None


def _get_manager():
    """Return ProviderManager singleton or None."""
    try:
        from ...providers.provider_manager import ProviderManager

        return ProviderManager.get_instance()
    except Exception:
        logger.debug("ProviderManager not initialised yet")
        return None


# ------------------------------------------------------------------
# Public helpers for API / Console UI
# ------------------------------------------------------------------


def list_transcription_providers() -> List[dict]:
    """Return providers capable of audio transcription.

    Each entry is ``{"id": ..., "name": ..., "available": bool}``.
    Availability is based on whether the provider has usable credentials.
    """
    manager = _get_manager()
    if manager is None:
        return []

    results: list[dict] = []
    all_providers = {
        **getattr(manager, "builtin_providers", {}),
        **getattr(manager, "custom_providers", {}),
    }
    for provider in all_providers.values():
        creds = _url_for_provider(provider)
        if creds is not None:
            results.append(
                {
                    "id": provider.id,
                    "name": provider.name,
                    "available": True,
                },
            )
    return results


def get_configured_transcription_provider_id() -> str:
    """Return the explicitly configured provider ID (raw config value)."""
    from ...config import load_config

    return load_config().agents.transcription_provider_id


def check_local_whisper_available() -> dict:
    """Lightweight settings probe; never import the optional recognizer."""
    from ...plugins.local_transcription import get_status

    return get_status()


async def _transcribe_backend(
    backend_id: str,
    file_path: str,
) -> Optional[str]:
    from ...plugins.registry import PluginRegistry
    from ...plugins._workspace import current_workspace_id
    from ...config.context import get_current_session_id

    backend = PluginRegistry().get_transcription_backend(backend_id)
    if backend is None:
        logger.warning("Transcription backend %s is not active", backend_id)
        return None
    try:
        result = await backend.call(
            file_path=file_path,
            workspace_id=current_workspace_id(),
            session_id=get_current_session_id() or "",
        )
        if result.error:
            logger.warning(
                "Transcription %s: %s (%s)",
                backend_id,
                result.error,
                result.message,
            )
            return None
        return result.text.strip() or None
    except Exception:
        logger.warning(
            "Transcription backend %s failed",
            backend_id,
            exc_info=True,
        )
        return None


async def _transcribe_local_whisper(file_path: str) -> Optional[str]:
    """Compatibility entry point; recognition is owned by the SDK plugin."""
    return await _transcribe_backend("local_whisper", file_path)


def _get_configured_provider_creds() -> Optional[Tuple[str, str]]:
    """Return ``(base_url, api_key)`` for the explicitly configured provider.

    Returns ``None`` when no provider is configured or the configured
    provider is not found / has no usable credentials.
    """
    from ...config import load_config

    configured_id = load_config().agents.transcription_provider_id
    if not configured_id:
        return None

    manager = _get_manager()
    if manager is None:
        return None

    provider = manager.get_provider(configured_id)
    if provider is None:
        logger.warning(
            "Configured transcription provider '%s' not found",
            configured_id,
        )
        return None

    creds = _url_for_provider(provider)
    if creds is None:
        logger.warning(
            "Configured transcription provider '%s' has no usable credentials",
            configured_id,
        )
    return creds


async def _transcribe_whisper_api(file_path: str) -> Optional[str]:
    """Transcribe using the OpenAI-compatible Whisper API endpoint.

    Only uses the explicitly configured provider — no auto-detection.
    Returns the transcribed text, or ``None`` on failure.
    """
    creds = await run_sync_io(_get_configured_provider_creds)
    if creds is None:
        logger.warning(
            "No transcription provider configured; skipping transcription",
        )
        return None

    base_url, api_key = creds

    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning(
            "openai package not installed; cannot transcribe audio",
        )
        return None

    from ...config import load_config

    model_name = load_config().agents.transcription_model or "whisper-1"

    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key or "none",
        timeout=60,
    )

    try:
        with open(file_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(
                model=model_name,
                file=f,
            )
        text = transcript.text.strip()
        if text:
            logger.debug("Transcribed audio %s: %s", file_path, text[:80])
            return text
        logger.warning("Transcription returned empty text for %s", file_path)
        return None
    except Exception:
        logger.warning(
            "Audio transcription failed for %s",
            file_path,
            exc_info=True,
        )
        return None


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------


async def transcribe_audio(file_path: str) -> Optional[str]:
    """Transcribe an audio file to text.

    Dispatches to either the Whisper API or local Whisper based on the
    ``transcription_provider_type`` config setting.  When the setting is
    ``"disabled"`` (the default), returns ``None`` immediately.

    Returns the transcribed text, or ``None`` on failure.
    """
    from ...config import load_config

    provider_type = load_config().agents.transcription_provider_type

    if provider_type == "disabled":
        logger.debug("Transcription is disabled; skipping")
        return None
    if provider_type == "local_whisper":
        return await _transcribe_local_whisper(file_path)
    if provider_type == "whisper_api":
        return await _transcribe_whisper_api(file_path)

    return await _transcribe_backend(provider_type, file_path)
