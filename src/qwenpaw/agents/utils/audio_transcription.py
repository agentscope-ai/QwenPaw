# -*- coding: utf-8 -*-
"""Saved global ASR service with bounded execution and safe failure codes."""

import asyncio
import inspect
import logging
import shutil
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)
LOCAL_MODELS = ("tiny", "base", "small", "medium", "large-v3", "turbo")
_local_models = {}
_local_whisper_lock = threading.Lock()
_local_inference = threading.BoundedSemaphore(1)
_inference_slots = threading.BoundedSemaphore(4)
_private_asr_call = ContextVar("private_asr_call", default=False)


class _PrivateASRLogFilter(logging.Filter):
    def filter(self, record):
        return not _private_asr_call.get()


# Suppress transport diagnostics only within ASR; other requests retain their logs.
_transport_filter = _PrivateASRLogFilter()
for _logger_name in (
    "openai._base_client",
    "openai._client",
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
):
    logging.getLogger(_logger_name).addFilter(_transport_filter)

ERRORS = {
    "TRANSCRIPTION_DISABLED": (400, "Transcription is disabled."),
    "TRANSCRIPTION_NOT_READY": (503, "Transcription is not ready."),
    "UNSUPPORTED_FILE_TYPE": (400, "Unsupported audio file type."),
    "FILE_TOO_LARGE": (413, "Audio exceeds the size limit."),
    "EMPTY_AUDIO": (400, "Audio is empty."),
    "EMPTY_TRANSCRIPT": (422, "No speech was recognized."),
    "TRANSCRIPTION_BUSY": (429, "Transcription is busy. Try again later."),
    "UPSTREAM_TIMEOUT": (504, "Transcription timed out."),
    "UPSTREAM_FAILED": (502, "Transcription failed."),
    "INVALID_VOICE_SETTINGS": (400, "Invalid voice transcription settings."),
    "INVALID_TRANSCRIPTION_REQUEST": (400, "Unsupported transcription fields."),
}


class TranscriptionError(Exception):
    def __init__(self, code):
        self.code = code
        self.status, self.message = ERRORS[code]
        super().__init__(code)


@dataclass(frozen=True)
class TranscriptionSnapshot:
    provider_type: str
    provider_id: str = ""
    model: str = "whisper-1"
    local_model: str = "base"
    base_url: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    headers: tuple = field(default=(), repr=False)


def local_cache_root():
    from ...constant import WORKING_DIR

    return Path(WORKING_DIR).resolve() / "cache" / "whisper"


def _weight_path(model_name):
    if model_name not in LOCAL_MODELS:
        raise TranscriptionError("TRANSCRIPTION_NOT_READY")
    root = local_cache_root().resolve()
    path = root / (model_name + ".pt")
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise TranscriptionError("TRANSCRIPTION_NOT_READY")
    return path


def _get_local_whisper_model(model_name="base"):
    path = _weight_path(model_name)
    key = (model_name, str(path.parent), path.stat().st_mtime_ns, path.stat().st_size)
    with _local_whisper_lock:
        if key not in _local_models:
            import whisper

            # Passing a verified local file prevents whisper's name-based download.
            model = whisper.load_model(str(path), download_root=str(path.parent))
            for cached_key in list(_local_models):
                if cached_key[:2] == key[:2]:
                    del _local_models[cached_key]
            _local_models[key] = model
        return _local_models[key]


async def wait_for_reader(function, *args):
    """Cancellation never outlives a worker that still owns a source file."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


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


def list_transcription_providers():
    manager = _get_manager()
    if manager is None:
        return []
    providers = {
        **getattr(manager, "builtin_providers", {}),
        **getattr(manager, "custom_providers", {}),
    }
    plugins = getattr(manager, "plugin_providers", {})
    if isinstance(plugins, dict):
        for provider_id in plugins:
            providers[provider_id] = manager.get_provider(provider_id)
    result = []
    for provider in providers.values():
        if provider is None:
            continue
        credentials = _url_for_provider(provider)
        if credentials is None:
            from ...providers.openai_provider import OpenAIProvider

            if not isinstance(provider, OpenAIProvider):
                continue
        # Names are display-only; redact credentials even if embedded in a label.
        label = str(provider.name)
        sensitive = [
            getattr(provider, "api_key", ""),
            getattr(provider, "base_url", ""),
        ]
        headers = getattr(provider, "custom_headers", {})
        if isinstance(headers, dict):
            sensitive.extend(headers.values())
        for value in sensitive:
            if isinstance(value, str) and value:
                label = label.replace(value, "[redacted]")
        result.append(
            {"id": provider.id, "name": label, "available": credentials is not None}
        )
    return result


def get_configured_transcription_provider_id():
    from ...config import load_config

    return load_config().agents.transcription_provider_id


def check_local_whisper_available(model_name="base"):
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    whisper_ok = False
    try:
        import whisper

        whisper_ok = True
    except ImportError:
        pass
    try:
        _weight_path(model_name)
        ready = True
    except (OSError, TranscriptionError):
        ready = False
    return {
        "available": ffmpeg_ok and whisper_ok and ready,
        "ffmpeg_installed": ffmpeg_ok,
        "whisper_installed": whisper_ok,
        "model_ready": ready,
    }


def capture_snapshot(agents=None):
    from ...config import load_config

    if agents is None:
        agents = load_config().agents
    kind = agents.transcription_provider_type
    provider_id = agents.transcription_provider_id
    model = agents.transcription_model
    local_model = getattr(agents, "transcription_local_model", "base")
    if kind == "disabled":
        raise TranscriptionError("TRANSCRIPTION_DISABLED")
    if kind not in {"local_whisper", "whisper_api"}:
        raise TranscriptionError("TRANSCRIPTION_NOT_READY")
    if kind == "local_whisper":
        if not check_local_whisper_available(local_model)["available"]:
            raise TranscriptionError("TRANSCRIPTION_NOT_READY")
        return TranscriptionSnapshot(kind, local_model=local_model)
    manager = _get_manager()
    provider = manager.get_provider(provider_id) if manager and provider_id else None
    creds = _url_for_provider(provider) if provider else None
    if not creds or not creds[0] or not model:
        raise TranscriptionError("TRANSCRIPTION_NOT_READY")
    return TranscriptionSnapshot(
        kind,
        provider_id,
        model,
        local_model,
        *creds,
        tuple(dict(provider.custom_headers).items()),
    )


async def require_registered_service(snapshot):
    if snapshot.provider_type != "whisper_api":
        return
    from ...models.runtime import require_transcription_service

    try:
        await require_transcription_service(snapshot.provider_id, snapshot.model)
    except Exception:
        raise TranscriptionError("TRANSCRIPTION_NOT_READY") from None


async def _local(file_path, model_name):
    if not check_local_whisper_available(model_name)["available"]:
        raise TranscriptionError("TRANSCRIPTION_NOT_READY")
    if not _local_inference.acquire(blocking=False):
        raise TranscriptionError("TRANSCRIPTION_BUSY")
    try:

        def run():
            model = _get_local_whisper_model(model_name)
            return (model.transcribe(file_path).get("text") or "").strip()

        return await wait_for_reader(run)
    finally:
        _local_inference.release()


async def _remote(file_path, snapshot):
    token = _private_asr_call.set(True)
    try:
        return await _remote_private(file_path, snapshot)
    finally:
        _private_asr_call.reset(token)


async def _remote_private(file_path, snapshot):
    client = None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=snapshot.base_url,
            api_key=snapshot.api_key or "none",
            default_headers=dict(snapshot.headers),
            timeout=60,
            max_retries=0,
        )
        with open(file_path, "rb") as stream:
            result = await client.audio.transcriptions.create(
                model=snapshot.model, file=stream
            )
        return result.text.strip()
    finally:
        if client is not None:
            close_result = client.close()
            if inspect.isawaitable(close_result):
                close_task = asyncio.ensure_future(close_result)
                cancelled = False
                while not close_task.done():
                    try:
                        await asyncio.shield(close_task)
                    except asyncio.CancelledError:
                        cancelled = True
                close_task.result()
                if cancelled:
                    raise asyncio.CancelledError


async def transcribe_snapshot(file_path, snapshot):
    if not _inference_slots.acquire(blocking=False):
        raise TranscriptionError("TRANSCRIPTION_BUSY")
    try:
        await require_registered_service(snapshot)
        try:
            text = (
                await _local(file_path, snapshot.local_model)
                if snapshot.provider_type == "local_whisper"
                else await _remote(file_path, snapshot)
            )
            if not text:
                raise TranscriptionError("EMPTY_TRANSCRIPT")
            return text
        except TranscriptionError:
            raise
        except Exception as exc:
            from openai import APITimeoutError

            code = (
                "UPSTREAM_TIMEOUT"
                if isinstance(exc, (TimeoutError, APITimeoutError))
                else "UPSTREAM_FAILED"
            )
            raise TranscriptionError(code) from None
    finally:
        _inference_slots.release()


def _get_configured_provider_creds():
    from ...config import load_config

    provider_id = load_config().agents.transcription_provider_id
    manager = _get_manager() if provider_id else None
    provider = manager.get_provider(provider_id) if manager else None
    return _url_for_provider(provider) if provider else None


async def _transcribe_local_whisper(file_path, snapshot=None):
    try:
        text = await _local(file_path, snapshot.local_model if snapshot else "base")
        return text or None
    except Exception:
        return None


async def _transcribe_whisper_api(file_path, snapshot=None):
    try:
        if snapshot is None:
            from ...config import load_config

            creds = _get_configured_provider_creds()
            if creds is None:
                return None
            snapshot = TranscriptionSnapshot(
                "whisper_api",
                model=load_config().agents.transcription_model,
                base_url=creds[0],
                api_key=creds[1],
            )
        return await transcribe_snapshot(file_path, snapshot)
    except Exception:
        return None


async def transcribe_audio(file_path):
    """Chat auto mode preserves its placeholder fallback, without unsafe logs."""
    try:
        snapshot = capture_snapshot()
        return await transcribe_snapshot(file_path, snapshot)
    except Exception:
        return None
