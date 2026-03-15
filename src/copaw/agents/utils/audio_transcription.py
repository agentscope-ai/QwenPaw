# -*- coding: utf-8 -*-
"""Audio transcription utility.

Transcribes audio files to text using an OpenAI-compatible
``/v1/audio/transcriptions`` endpoint.  The endpoint accepts ``.ogg``
natively, so no format conversion is required for Discord voice messages.
"""

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def _url_for_provider(provider) -> Optional[Tuple[str, str]]:
    """Return ``(base_url, api_key)`` if provider supports transcription."""
    from ...providers.openai_provider import OpenAIProvider
    from ...providers.ollama_provider import OllamaProvider

    if isinstance(provider, OpenAIProvider) and provider.api_key:
        return (provider.base_url, provider.api_key)
    if isinstance(provider, OllamaProvider):
        base = provider.base_url.rstrip("/")
        return (base + "/v1", provider.api_key or "ollama")
    return None


def _get_manager():
    """Return ProviderManager singleton or None."""
    try:
        from ...providers.provider_manager import ProviderManager

        return ProviderManager.get_instance()
    except Exception:
        logger.debug("ProviderManager not initialised yet")
        return None


def list_transcription_providers() -> List[dict]:
    """Return a list of providers capable of audio transcription.

    Each entry is ``{"id": ..., "name": ..., "available": bool}``.
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
                    "available": bool(creds[1]),
                },
            )
    return results


def get_active_transcription_provider_id() -> str:
    """Return the provider ID currently used for transcription.

    If a provider is explicitly configured, returns that.
    Otherwise returns the auto-detected provider ID, or empty string.
    """
    from ...config import load_config

    configured = load_config().agents.transcription_provider_id
    if configured:
        return configured

    # Auto-detect
    creds = _find_transcription_provider()
    if creds and len(creds) == 3:
        return creds[2]
    return ""


def _find_transcription_provider() -> Optional[Tuple[str, str, str]]:
    """Find an OpenAI-compatible provider that can serve transcription.

    Returns ``(base_url, api_key, provider_id)`` or ``None``.
    Checks configured provider first, then active, then scans all.
    """
    manager = _get_manager()
    if manager is None:
        return None

    # 0. Check explicitly configured transcription provider.
    from ...config import load_config

    configured_id = load_config().agents.transcription_provider_id
    if configured_id:
        provider = manager.get_provider(configured_id)
        if provider:
            result = _url_for_provider(provider)
            if result:
                return (*result, provider.id)

    # 1. Try active provider.
    active = manager.get_active_model()
    if active:
        provider = manager.get_provider(active.provider_id)
        if provider:
            result = _url_for_provider(provider)
            if result:
                return (*result, provider.id)

    # 2. Scan all providers for any compatible one.
    all_providers = {
        **getattr(manager, "builtin_providers", {}),
        **getattr(manager, "custom_providers", {}),
    }
    for provider in all_providers.values():
        result = _url_for_provider(provider)
        if result:
            return (*result, provider.id)

    return None


async def transcribe_audio(file_path: str) -> Optional[str]:
    """Transcribe an audio file to text.

    Uses the OpenAI-compatible ``/v1/audio/transcriptions`` endpoint,
    which accepts ogg, mp3, wav, flac, m4a, and other common formats.

    Returns the transcribed text, or ``None`` on failure.
    """
    creds = _find_transcription_provider()
    if creds is None:
        logger.warning(
            "No OpenAI-compatible provider found for audio transcription. "
            "Audio block will be kept as-is.",
        )
        return None

    base_url, api_key, provider_id = creds
    logger.debug("Using provider '%s' for transcription", provider_id)

    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("openai package not installed; cannot transcribe audio")
        return None

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=60)

    try:
        with open(file_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
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
