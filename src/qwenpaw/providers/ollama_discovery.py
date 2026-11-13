# -*- coding: utf-8 -*-
"""Ollama native ``/api/show`` parsing and context-window probes."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Literal

import httpx

from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.utils.io_utils import run_async_to_completion, run_sync_io

logger = logging.getLogger(__name__)

# Bound concurrent /api/show probes when many models are installed.
_SHOW_PROBE_CONCURRENCY = 8
# ASCII digits only, length-capped so int() cannot raise on overlong input.
_NUM_CTX_RE = re.compile(
    r"(?m)^\s*num_ctx\s+(\d{1,18})\s*$",
    re.ASCII,
)

OllamaShowStatus = Literal["failed", "malformed", "unknown", "resolved"]


def parse_ollama_num_ctx(parameters: Any) -> int | None:
    """Return Modelfile ``num_ctx`` from an ``/api/show`` parameters block.

    Non-string values (a dict, list, or number) are ignored so one
    malformed model cannot abort the batch. Overlong digit strings are
    ignored rather than raising.
    """
    if not isinstance(parameters, str) or not parameters:
        return None
    match = _NUM_CTX_RE.search(parameters)
    if match is None:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _parse_positive_context_int(raw: Any) -> int | None:
    """Return a strict positive integer, or None.

    ``model_info`` values arrive as JSON numbers, so only a real ``int``
    greater than zero is accepted. Bools are a subclass of ``int`` and
    are rejected. Floats are rejected so they are not truncated into a
    context length.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw > 0 else None


def parse_ollama_model_training_context(model_info: Any) -> int | None:
    """Return the architecture's training context, or None.

    Ollama reads this only from
    ``model_info[general.architecture + ".context_length"]``
    (``fs/ggml/ggml.go``, v0.19.0). ``general.architecture`` must be a
    non-empty string after stripping whitespace. The value must be a
    strict positive integer. A bare ``context_length`` key and other
    architectures' keys are ignored.

    This is not a window by itself. Callers may use it only to clamp an
    explicit Modelfile ``num_ctx``.
    """
    if not isinstance(model_info, dict):
        return None
    architecture = model_info.get("general.architecture")
    if not isinstance(architecture, str):
        return None
    architecture = architecture.strip()
    if not architecture:
        return None
    return _parse_positive_context_int(
        model_info.get(f"{architecture}.context_length"),
    )


def _show_parameters_malformed(show_payload: dict[str, Any]) -> bool:
    """True when ``parameters`` is present but not a Modelfile string.

    An explicit JSON ``null`` is an invalid value and must be treated as
    malformed. An omitted ``parameters`` field is not malformed: the show
    succeeded, but there is no Modelfile ``num_ctx``.
    """
    return "parameters" in show_payload and not isinstance(
        show_payload["parameters"],
        str,
    )


def classify_ollama_show_payload(
    show_payload: Any,
) -> tuple[OllamaShowStatus, int | None]:
    """Classify an ``/api/show`` result before resolving a window.

    ``failed`` means the probe did not return a JSON object (timeout,
    401/403, or an invalid body). ``malformed`` means the show succeeded
    but ``parameters`` was present and not a string, including explicit
    JSON ``null``. ``unknown`` is a successful, well-formed show with no
    usable ``num_ctx``. ``resolved`` carries the clamped window.
    """
    if not isinstance(show_payload, dict):
        return "failed", None
    if _show_parameters_malformed(show_payload):
        return "malformed", None
    window = resolve_ollama_context_window(show_payload)
    if window is None:
        return "unknown", None
    return "resolved", window


def resolve_ollama_context_window(
    show_payload: dict[str, Any],
) -> int | None:
    """Return the clamped Modelfile ``num_ctx`` from a valid show payload.

    *show_payload* must already be a successful, well-formed
    ``/api/show`` body. Failed or malformed payloads should be
    classified first and not passed here.

    QwenPaw chats through the OpenAI-compatible endpoint, which cannot
    set Ollama's context size, so chat ``options.num_ctx`` is not a
    source. The window is the explicit Modelfile ``num_ctx``, clamped to
    the training context when that cap is present. Ollama reads the cap
    from ``model_info[general.architecture + ".context_length"]`` and
    clamps ``NumCtx`` to it. When the cap is missing, the raw Modelfile
    value is kept. Do not invent a fallback: ``OLLAMA_CONTEXT_LENGTH``
    may be below any guessed constant.

    GGUF training context is not a window by itself: a show with only
    ``model_info`` and no ``num_ctx`` returns ``None``. It is used only
    as a cap on an explicit Modelfile ``num_ctx``.
    """
    show_context = parse_ollama_num_ctx(show_payload.get("parameters"))
    if show_context is None:
        return None
    cap = parse_ollama_model_training_context(show_payload.get("model_info"))
    if cap is not None:
        return min(show_context, cap)
    return show_context


def apply_show_context(
    model: ModelInfo,
    show_payload: Any,
) -> ModelInfo:
    """Attach, clear, or keep a model's auto-detected window."""
    status, window = classify_ollama_show_payload(show_payload)
    if status == "resolved":
        return model.model_copy(
            update={"max_input_length_auto_detected": window},
        )
    if status == "unknown":
        # Successful show with no usable num_ctx: clear a stale
        # auto-detected value from an earlier discovery.
        return model.model_copy(
            update={"max_input_length_auto_detected": None},
        )
    # Failed or malformed: omit the field so merge keeps any previous
    # auto-detected window.
    return model


async def enrich_listed_models(
    base_url: str,
    headers: dict[str, str],
    models: list[ModelInfo],
    timeout: float,
) -> list[ModelInfo]:
    """Attach verified windows under a shared probing deadline.

    A failed ``/api/show`` or malformed ``parameters`` leaves that model
    unchanged so merge can keep a previous auto-detected window. A
    successful show that omitted ``num_ctx`` clears
    ``max_input_length_auto_detected``.

    ``timeout`` is a shared wall-clock deadline for the ``/api/show``
    probes. When it expires, completed results are kept; only
    unfinished probes stay unset. If the HTTP client cannot be
    constructed, the original list is returned unchanged.
    """
    result = [model.model_copy() for model in models]
    client: httpx.AsyncClient | None = None
    try:
        # AsyncClient loads the default SSL context in __init__.
        # Build it off the event loop, same as dashscope discovery.
        client = await run_sync_io(
            httpx.AsyncClient,
            timeout=timeout,
            headers=headers,
        )
        await _probe_show_models(client, base_url, result, timeout)
        return result
    except Exception:
        logger.debug(
            "Ollama model enrichment failed before probes completed",
            exc_info=True,
        )
        return models if client is None else result
    finally:
        if client is not None:
            await client.aclose()


async def _probe_show_models(
    client: httpx.AsyncClient,
    base_url: str,
    result: list[ModelInfo],
    timeout: float,
) -> None:
    """Run ``/api/show`` for every model until *timeout*.

    Each task writes ``result[index]`` itself. Unfinished probes stay
    unset.
    """
    semaphore = asyncio.Semaphore(_SHOW_PROBE_CONCURRENCY)
    tasks = [
        asyncio.create_task(
            _enrich_model_context(
                client,
                base_url,
                result,
                index,
                semaphore,
            ),
        )
        for index in range(len(result))
    ]
    pending: set[asyncio.Task[None]] = set(tasks)
    try:
        _done, pending = await asyncio.wait(tasks, timeout=timeout)
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            # Drain cancelled shows even if discovery itself is
            # cancelled repeatedly, so the caller does not close
            # AsyncClient before those probes finish unwinding.
            await run_async_to_completion(
                asyncio.gather(*pending, return_exceptions=True),
            )


async def _enrich_model_context(
    client: httpx.AsyncClient,
    base_url: str,
    result: list[ModelInfo],
    index: int,
    semaphore: asyncio.Semaphore,
) -> None:
    """Attach one model's window. Failures leave that model unchanged."""
    model = result[index]
    try:
        result[index] = await _read_model_context(
            client,
            base_url,
            model,
            semaphore,
        )
    except Exception:
        logger.debug(
            "Ollama context enrichment failed for model %s",
            model.id,
            exc_info=True,
        )


async def _read_model_context(
    client: httpx.AsyncClient,
    base_url: str,
    model: ModelInfo,
    semaphore: asyncio.Semaphore,
) -> ModelInfo:
    async def _show() -> dict[str, Any] | None:
        try:
            response = await client.post(
                f"{base_url}/api/show",
                json={"model": model.id},
            )
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
        except Exception:
            logger.debug(
                "Ollama /api/show probe failed for model %s",
                model.id,
                exc_info=True,
            )
        return None

    async with semaphore:
        show_payload = await _show()
    return apply_show_context(model, show_payload)
