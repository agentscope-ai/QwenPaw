# -*- coding: utf-8 -*-
"""Audio transcription utility.

Transcribes audio files to text using either:
- An OpenAI-compatible ``/v1/audio/transcriptions`` endpoint (Whisper API), or
- The locally installed ``openai-whisper`` Python library (Local Whisper).

Transcription is only attempted when explicitly enabled via the
``transcription_provider_type`` config setting.  The default is ``"disabled"``.
"""

import asyncio
import io
import logging
import os
import shutil
import tempfile
import threading
import wave
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Cached local-whisper model (lazy singleton)
# ------------------------------------------------------------------
_local_whisper_model = None
_local_whisper_lock = threading.Lock()


def _get_local_whisper_model():
    """Return a cached whisper model, loading it on first call."""
    global _local_whisper_model  # noqa: PLW0603
    if _local_whisper_model is not None:
        return _local_whisper_model
    with _local_whisper_lock:
        if _local_whisper_model is not None:
            return _local_whisper_model
        import whisper

        _local_whisper_model = whisper.load_model("base")
        return _local_whisper_model


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
    """Check whether the local whisper provider can be used.

    Returns a dict with::

        {
            "available": bool,
            "ffmpeg_installed": bool,
            "whisper_installed": bool,
        }
    """
    ffmpeg_ok = shutil.which("ffmpeg") is not None

    whisper_ok = False
    try:
        import whisper as _whisper  # noqa: F401

        whisper_ok = True
    except ImportError:
        pass

    return {
        "available": ffmpeg_ok and whisper_ok,
        "ffmpeg_installed": ffmpeg_ok,
        "whisper_installed": whisper_ok,
    }


# ------------------------------------------------------------------
# SILK format detection and conversion for QQ voice messages
# ------------------------------------------------------------------


def _is_silk_file(file_path: str) -> bool:
    """Check if a file is in QQ SILK voice format.

    QQ voice messages start with the bytes ``\\x02#!SILK_V3``.
    The leading ``\\x02`` byte is part of the QQ protocol header and
    must be included in the check.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(10)
        return header[:10] == b"\x02#!SILK_V3"
    except Exception:
        return False


def _convert_silk_to_wav(silk_path: str) -> Optional[str]:
    """Decode a QQ SILK voice file to a 16 kHz WAV file.

    Returns the path to the temporary WAV file, or ``None`` on failure.
    The caller is responsible for cleaning up the returned file.
    """
    try:
        import pysilk as silk
        from scipy.signal import resample_poly

        # Decode SILK to PCM at 24 kHz
        pcm_buffer = io.BytesIO()
        with open(silk_path, "rb") as in_file:
            silk.decode(in_file, pcm_buffer, 24000)

        pcm_data = pcm_buffer.getvalue()
        if not pcm_data:
            logger.warning("SILK decode returned empty data for %s", silk_path)
            return None

        # Convert PCM bytes to numpy array (16-bit signed integers)
        pcm_array = np.frombuffer(pcm_data, dtype=np.int16)

        # Resample 24 kHz -> 16 kHz (ratio 24/16 = 3/2)
        resampled = resample_poly(pcm_array, 2, 3)

        # Write to temporary WAV file at 16 kHz
        temp_wav = tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False
        )
        with wave.open(temp_wav.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(16000)
            wf.writeframes(resampled.astype(np.int16).tobytes())

        logger.debug("Converted SILK %s -> WAV %s", silk_path, temp_wav.name)
        return temp_wav.name

    except ImportError:
        logger.warning(
            "pysilk or scipy not installed; cannot decode SILK file %s. "
            "Install with: pip install pysilk scipy numpy",
            silk_path,
        )
        return None
    except Exception:
        logger.exception("Failed to convert SILK to WAV for %s", silk_path)
        return None


# ------------------------------------------------------------------
# Transcription backends
# ------------------------------------------------------------------


async def _transcribe_local_whisper(file_path: str) -> Optional[str]:
    """Transcribe using the locally installed ``openai-whisper`` library.

    Requires both ``ffmpeg`` and ``openai-whisper`` to be installed.
    If the input file is in QQ SILK format, it is automatically decoded
    to WAV before transcription.
    Returns the transcribed text, or ``None`` on failure.
    """
    # Auto-detect and convert QQ SILK voice format
    wav_path = None
    if _is_silk_file(file_path):
        logger.debug("Detected QQ SILK format, converting to WAV...")
        wav_path = _convert_silk_to_wav(file_path)
        if wav_path is None:
            logger.warning(
                "SILK conversion failed for %s; "
                "attempting transcription with original file anyway.",
                file_path,
            )
        else:
            file_path = wav_path

    status = check_local_whisper_available()
    if not status["available"]:
        missing = []
        if not status["ffmpeg_installed"]:
            missing.append("ffmpeg")
        if not status["whisper_installed"]:
            missing.append("openai-whisper")
        logger.warning(
            "Local Whisper unavailable (missing: %s). "
            "Install the missing dependencies to use local transcription.",
            ", ".join(missing),
        )
        if wav_path and os.path.exists(wav_path):
            os.unlink(wav_path)
        return None

    def _run():
        model = _get_local_whisper_model()
        result = model.transcribe(file_path)
        return (result.get("text") or "").strip()

    try:
        text = await asyncio.to_thread(_run)
        if text:
            logger.debug(
                "Local Whisper transcribed %s: %s",
                file_path,
                text[:80],
            )
            return text
        logger.warning(
            "Local Whisper returned empty text for %s",
            file_path,
        )
        return None
    except Exception:
        logger.warning(
            "Local Whisper transcription failed for %s",
            file_path,
            exc_info=True,
        )
        return None
    finally:
        # Clean up temporary WAV file created from SILK conversion
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass


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
    creds = _get_configured_provider_creds()
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

    logger.warning("Unknown transcription_provider_type: %s", provider_type)
    return None
