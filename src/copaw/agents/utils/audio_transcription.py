# -*- coding: utf-8 -*-
"""Audio transcription utility.

Transcribes audio files to text using either:
- An OpenAI-compatible ``/v1/audio/transcriptions`` endpoint (Whisper API), or
- The locally installed ``openai-whisper`` Python library (Local Whisper).

Transcription is only attempted when explicitly enabled via the
``transcription_provider_type`` config setting.  The default is ``"disabled"``.
"""

import asyncio
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Cached local-whisper model (lazy singleton)
# ------------------------------------------------------------------
_local_whisper_model = None
_local_whisper_lock = threading.Lock()
_opencc_converter = None
_opencc_converter_lock = threading.Lock()


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


def _get_transcription_language_hints() -> dict[str, Optional[str]]:
    """Return language and prompt hints for speech transcription.

    The hint follows current agent language setting. For Chinese, we add
    a prompt to bias output toward Simplified Chinese.
    """
    from ...config import load_config

    configured = (load_config().agents.language or "").strip().lower()
    primary = configured.split("-")[0]

    language_map = {
        "en": "en",
        "ru": "ru",
        "ja": "ja",
    }
    whisper_language = language_map.get(primary)

    return {
        "configured": configured,
        "whisper_language": whisper_language,
        "prompt": None,
    }


def _get_opencc_t2s_converter():
    """Return an OpenCC Traditional-to-Simplified converter if available."""
    global _opencc_converter  # noqa: PLW0603
    if _opencc_converter is not None:
        return _opencc_converter

    with _opencc_converter_lock:
        if _opencc_converter is not None:
            return _opencc_converter
        try:
            from opencc import OpenCC

            _opencc_converter = OpenCC("t2s")
        except Exception:
            _opencc_converter = False
        return _opencc_converter


def _contains_chinese(text: str) -> bool:
    return re.search(r"[\u4e00-\u9fff]", text) is not None


def _normalize_transcription_text(
    text: str,
    configured_language: str,
) -> str:
    """Normalize transcription text according to current language setting."""
    if not text:
        return text

    primary = (configured_language or "").strip().lower().split("-")[0]
    if primary != "zh" or not _contains_chinese(text):
        return text

    converter = _get_opencc_t2s_converter()
    if not converter:
        return text

    try:
        return converter.convert(text)
    except Exception:
        logger.debug("Failed to normalize transcription to Simplified Chinese")
        return text


def _run_install_command(command: list[str]) -> dict:
    """Run an installation command and capture its outcome."""
    command_str = " ".join(command)
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {
            "command": command_str,
            "ok": False,
            "output": str(exc),
            "returncode": None,
        }

    return {
        "command": command_str,
        "ok": result.returncode == 0,
        "output": (result.stdout or "").strip(),
        "returncode": result.returncode,
    }


def _build_python_whisper_install_command() -> tuple[list[str], str]:
    """Return the preferred command to install openai-whisper."""
    if shutil.which("uv"):
        return (
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "openai-whisper",
            ],
            "uv pip",
        )
    return (
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "openai-whisper",
            "--disable-pip-version-check",
        ],
        "pip",
    )


def _build_ffmpeg_install_command(
    *,
    system_name: Optional[str] = None,
) -> tuple[Optional[list[str]], Optional[str], Optional[str]]:
    """Return a best-effort command for installing ffmpeg."""
    system_name = (system_name or platform.system()).lower()

    if system_name == "darwin":
        if shutil.which("brew"):
            return (["brew", "install", "ffmpeg"], "brew", None)
        return (
            None,
            None,
            "Automatic ffmpeg installation requires Homebrew on macOS.",
        )

    if system_name == "windows":
        if shutil.which("winget"):
            return (
                [
                    "winget",
                    "install",
                    "--id",
                    "Gyan.FFmpeg",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
                "winget",
                None,
            )
        if shutil.which("choco"):
            return (["choco", "install", "ffmpeg", "-y"], "choco", None)
        return (
            None,
            None,
            "Automatic ffmpeg installation requires winget or Chocolatey on Windows.",
        )

    if system_name == "linux":
        if os.geteuid() == 0:
            if shutil.which("apt-get"):
                return (["apt-get", "install", "-y", "ffmpeg"], "apt-get", None)
            if shutil.which("dnf"):
                return (["dnf", "install", "-y", "ffmpeg"], "dnf", None)
            if shutil.which("yum"):
                return (["yum", "install", "-y", "ffmpeg"], "yum", None)
            if shutil.which("pacman"):
                return (["pacman", "-Sy", "--noconfirm", "ffmpeg"], "pacman", None)
        return (
            None,
            None,
            "Automatic ffmpeg installation on Linux requires running CoPaw with root privileges or installing ffmpeg manually.",
        )

    return (
        None,
        None,
        f"Automatic ffmpeg installation is not supported on {system_name}.",
    )


def auto_install_local_whisper_dependencies() -> dict:
    """Install missing Local Whisper dependencies when possible."""
    status_before = check_local_whisper_available()
    operations: list[dict] = []
    manual_steps: list[str] = []

    if status_before["available"]:
        return {
            "success": True,
            "already_available": True,
            "status_before": status_before,
            "status_after": status_before,
            "operations": operations,
            "manual_steps": manual_steps,
        }

    if not status_before["whisper_installed"]:
        command, installer = _build_python_whisper_install_command()
        result = _run_install_command(command)
        operations.append(
            {
                "name": "openai-whisper",
                "attempted": True,
                "installer": installer,
                **result,
            },
        )

    if not status_before["ffmpeg_installed"]:
        command, installer, manual_step = _build_ffmpeg_install_command()
        if command is None:
            detail = manual_step or "No supported automatic ffmpeg installer was found."
            manual_steps.append(detail)
            operations.append(
                {
                    "name": "ffmpeg",
                    "attempted": False,
                    "installer": installer,
                    "command": "",
                    "ok": False,
                    "output": detail,
                    "returncode": None,
                },
            )
        else:
            result = _run_install_command(command)
            operations.append(
                {
                    "name": "ffmpeg",
                    "attempted": True,
                    "installer": installer,
                    **result,
                },
            )
            if not result["ok"]:
                manual_steps.append(
                    f"Automatic ffmpeg installation via {installer} failed. Install ffmpeg manually and retry.",
                )

    status_after = check_local_whisper_available()
    if not status_after["whisper_installed"]:
        manual_steps.append(
            "Install openai-whisper manually with `uv pip install openai-whisper` or reinstall CoPaw with the [whisper] extra.",
        )

    return {
        "success": status_after["available"],
        "already_available": False,
        "status_before": status_before,
        "status_after": status_after,
        "operations": operations,
        "manual_steps": manual_steps,
    }


# ------------------------------------------------------------------
# Transcription backends
# ------------------------------------------------------------------


async def _transcribe_local_whisper(file_path: str) -> Optional[str]:
    """Transcribe using the locally installed ``openai-whisper`` library.

    Requires both ``ffmpeg`` and ``openai-whisper`` to be installed.
    Returns the transcribed text, or ``None`` on failure.
    """
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
        return None

    hints = _get_transcription_language_hints()

    def _run():
        model = _get_local_whisper_model()
        # Avoid upstream warning on CPU-only environments.
        device = str(getattr(model, "device", "")).lower()
        language = (
            str(hints["whisper_language"])
            if hints["whisper_language"]
            else None
        )
        initial_prompt = str(hints["prompt"]) if hints["prompt"] else None

        if "cpu" in device:
            result = model.transcribe(
                file_path,
                fp16=False,
                language=language,
                initial_prompt=initial_prompt,
            )
        else:
            result = model.transcribe(
                file_path,
                language=language,
                initial_prompt=initial_prompt,
            )

        text = result.get("text") if isinstance(result, dict) else ""
        return str(text or "").strip()

    try:
        text = await asyncio.to_thread(_run)
        if text:
            text = _normalize_transcription_text(
                text,
                hints.get("configured") or "",
            )
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
    hints = _get_transcription_language_hints()

    try:
        with open(file_path, "rb") as f:
            kwargs = {
                "model": model_name,
                "file": f,
            }
            if hints["whisper_language"]:
                kwargs["language"] = hints["whisper_language"]
            if hints["prompt"]:
                kwargs["prompt"] = hints["prompt"]
            transcript = await client.audio.transcriptions.create(
                **kwargs,
            )
        text = transcript.text.strip()
        if text:
            text = _normalize_transcription_text(
                text,
                hints.get("configured") or "",
            )
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
