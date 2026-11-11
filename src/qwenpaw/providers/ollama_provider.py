# -*- coding: utf-8 -*-
"""An Ollama provider implementation."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, List

import httpx
from agentscope.model import ChatModelBase
from openai import AsyncOpenAI

from qwenpaw.providers.capping_formatter import _CappingOpenAIFormatter
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelConnectionResult
from qwenpaw.utils.io_utils import run_async_to_completion, run_sync_io

logger = logging.getLogger(__name__)

# Accept any positive context; ModelInfo allows ge=1 on auto_detected.
_MIN_CONTEXT_TOKENS = 1
# Bound concurrent /api/show probes when many models are installed.
_SHOW_PROBE_CONCURRENCY = 8

_NUM_CTX_RE = re.compile(
    r"(?m)^\s*num_ctx\s+(\d+)\s*$",
)


def parse_ollama_num_ctx(parameters: Any) -> int | None:
    """Return Modelfile ``num_ctx`` from an ``/api/show`` parameters block.

    Non-string values (a dict, list, or number) are ignored so one
    malformed model cannot abort the batch.
    """
    if not isinstance(parameters, str) or not parameters:
        return None
    match = _NUM_CTX_RE.search(parameters)
    if match is None:
        return None
    value = int(match.group(1))
    return value if value >= _MIN_CONTEXT_TOKENS else None


def _parse_positive_context_int(raw: Any) -> int | None:
    """Return a strict positive integer, or None.

    Only a real ``int`` or a digit string of at least
    ``_MIN_CONTEXT_TOKENS`` is accepted. Bools are a subclass of ``int``
    and are rejected. Floats are rejected so they are not truncated
    into a context length.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= _MIN_CONTEXT_TOKENS else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text.isdigit():
            return None
        value = int(text)
        return value if value >= _MIN_CONTEXT_TOKENS else None
    return None


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


def resolve_ollama_context_window(
    *,
    show_payload: dict[str, Any] | None = None,
) -> int | None:
    """Return the clamped Modelfile ``num_ctx`` our next chat will use.

    QwenPaw chats through the OpenAI-compatible endpoint, which cannot
    set Ollama's context size, so chat ``options.num_ctx`` is not a
    source. The window is the explicit Modelfile ``num_ctx`` from a
    successful ``/api/show``, clamped to the training context when that
    cap is present. Ollama reads the cap from
    ``model_info[general.architecture + ".context_length"]`` and clamps
    ``NumCtx`` to it. When the cap is missing, the raw Modelfile value
    is kept. Do not invent a fallback: ``OLLAMA_CONTEXT_LENGTH`` may be
    below any guessed constant.

    ``show_payload is None`` means the probe failed (timeout, 401/403, or
    an invalid body). That is not an empty successful show: this returns
    ``None`` so the caller leaves the model unchanged (merge keeps any
    previous auto-detected window). A dict payload with no usable
    ``num_ctx`` also returns ``None``; the caller then clears a stale
    auto-detected value.

    A non-string ``parameters`` value is malformed, not an omitted
    ``num_ctx``. This also returns ``None``; the caller must treat it like
    a failed show and retain any previous auto-detected window.

    GGUF training context is not a window by itself: a show with only
    ``model_info`` and no ``num_ctx`` returns ``None``. It is used only
    as a cap on an explicit Modelfile ``num_ctx``.
    """
    if not isinstance(show_payload, dict) or _show_parameters_malformed(
        show_payload,
    ):
        return None
    show_context = parse_ollama_num_ctx(show_payload.get("parameters"))
    if show_context is None:
        return None
    cap = parse_ollama_model_training_context(show_payload.get("model_info"))
    if cap is not None and cap > 0:
        return min(show_context, cap)
    return show_context


def _show_parameters_malformed(show_payload: dict[str, Any]) -> bool:
    """True when ``parameters`` is present but not a Modelfile string."""
    parameters = show_payload.get("parameters")
    return parameters is not None and not isinstance(parameters, str)


class OllamaProvider(OpenAIProvider):
    """Provider implementation for Ollama local LLM hosting platform."""

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        normalized_base_url = (base_url or "").rstrip("/")
        if normalized_base_url.endswith("/v1"):
            # For backwards compatibility, if the URL ends with /v1,
            # we strip it to get the Ollama server base URL.
            normalized_base_url = normalized_base_url[:-3].rstrip("/")
        return normalized_base_url

    def _openai_compatible_base_url(self) -> str:
        return (
            self._normalize_base_url(
                self.base_url,  # type: ignore [has-type]
            )
            + "/v1"
        )

    def model_post_init(self, __context: Any) -> None:
        if not self.base_url:  # type: ignore
            self.base_url = (
                os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
            )
        self.base_url = self._normalize_base_url(self.base_url)

    def update_config(self, config: dict[str, Any]) -> None:
        super().update_config(config)
        self.base_url = self._normalize_base_url(self.base_url)

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        kwargs: dict = {
            "base_url": self._openai_compatible_base_url(),
            "api_key": self.api_key,
            "timeout": timeout,
        }
        headers = self._build_default_headers()
        if headers:
            kwargs["default_headers"] = headers
        return AsyncOpenAI(**kwargs)

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> ModelConnectionResult:
        """Confirm the model id is listed via ``/v1/models`` only.

        ``fetch_models`` also probes ``/api/show`` for every model. A
        connection check must not do that.
        """
        models = await super().fetch_models(timeout=timeout)
        if any(model.id == model_id for model in models):
            return ModelConnectionResult(
                success=True,
                verification="provider_only",
            )
        return ModelConnectionResult(
            success=False,
            message=f"Model '{model_id}' not found",
            error_kind="model_not_found",
            verification="provider_only",
        )

    def _native_probe_headers(self) -> dict[str, str]:
        """Headers for native ``/api/show`` probes.

        The OpenAI-compatible client already sends ``api_key`` and
        ``_build_default_headers()``. Secured Ollama can accept
        ``/v1/models`` and reject bare native calls, so these probes carry
        the same material. An Authorization value already configured in
        the headers is left unchanged.
        """
        headers = {
            str(key): str(value)
            for key, value in (self._build_default_headers() or {}).items()
        }
        if any(
            str(key).lower() == "authorization" and str(value).strip()
            for key, value in headers.items()
        ):
            return headers
        api_key = (self.api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _context_catalog_enabled(self) -> bool:
        """Ollama serves models locally: the family's cloud window does not
        apply (a local ``qwen3-coder:30b`` truncates at ``num_ctx``, not at
        262k). Skip the static catalog; an explicit per-model
        ``max_input_length`` still wins. When discovery has populated
        ``max_input_length_auto_detected`` from ``/api/show``, that
        value is used; otherwise the 128k default remains."""
        return False

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """List models, then attach Ollama's real context window when known.

        The OpenAI-compatible ``/v1/models`` rows do not carry context
        metadata, so without this step every Ollama model stays at the
        128k placeholder and compaction never aligns with ``num_ctx``.

        A failed ``/api/show`` or malformed ``parameters`` leaves that
        model unchanged so merge can keep a previous auto-detected
        window. A successful show that omitted ``num_ctx`` clears
        ``max_input_length_auto_detected``.

        An explicit Modelfile ``num_ctx`` is clamped to the training
        context (``model_info[general.architecture + ".context_length"]``)
        when that cap is a positive integer. Chat ``generate_kwargs``
        ``num_ctx`` is not used: the OpenAI-compatible endpoint cannot
        set the context size. With no explicit Modelfile ``num_ctx``,
        the 128k default remains.

        ``timeout`` is a shared wall-clock deadline for the ``/api/show``
        probes. HTTPX's per-call timeout does not cap total response
        time, so a slow ``/api/show`` is cancelled at this deadline.
        When it expires, completed ``/api/show`` results are kept; only
        unfinished probes stay unset.
        """
        models = await super().fetch_models(timeout=timeout)
        if not models:
            return models

        client: httpx.AsyncClient | None = None
        try:
            # AsyncClient loads the default SSL context in __init__.
            # Build it off the event loop, same as dashscope discovery.
            client = await run_sync_io(
                httpx.AsyncClient,
                timeout=timeout,
                headers=self._native_probe_headers(),
            )
            return await self._enrich_listed_models(
                client,
                models,
                timeout,
            )
        except Exception:
            # Setup failed before probing, or enrichment raised before
            # any result was recorded. Keep the un-enriched list.
            logger.debug(
                "Ollama model enrichment failed before probes completed",
                exc_info=True,
            )
            return models
        finally:
            if client is not None:
                await client.aclose()

    async def _enrich_listed_models(
        self,
        client: httpx.AsyncClient,
        models: List[ModelInfo],
        timeout: float,
    ) -> List[ModelInfo]:
        """Attach verified windows under a shared probing deadline.

        Every model is probed with ``/api/show``. A show that finishes
        in time is kept; a cancelled show leaves its model unset.
        """
        result = [model.model_copy() for model in models]
        try:
            await self._probe_show_models(
                client,
                result,
                timeout,
            )
        except Exception:
            logger.debug(
                "Ollama context enrichment failed",
                exc_info=True,
            )
            return result
        return result

    async def _probe_show_models(
        self,
        client: httpx.AsyncClient,
        result: List[ModelInfo],
        timeout: float,
    ) -> None:
        """Run ``/api/show`` for every model until *timeout*.

        Finished probes are kept. Unfinished probes stay unset.
        """
        semaphore = asyncio.Semaphore(_SHOW_PROBE_CONCURRENCY)
        task_to_index: dict[asyncio.Task[ModelInfo], int] = {}
        for index in range(len(result)):
            task = asyncio.create_task(
                self._enrich_model_context(
                    client,
                    result[index],
                    semaphore,
                ),
            )
            task_to_index[task] = index

        done: set[asyncio.Task[ModelInfo]] = set()
        pending: set[asyncio.Task[ModelInfo]] = set(task_to_index)
        try:
            done, pending = await asyncio.wait(
                set(task_to_index),
                timeout=timeout,
            )
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
            for task in done | pending:
                if not task.done() or task.cancelled():
                    continue
                index = task_to_index[task]
                try:
                    result[index] = task.result()
                except Exception:
                    logger.debug(
                        "Ollama context probe failed",
                        exc_info=True,
                    )
                    continue

    async def _enrich_model_context(
        self,
        client: httpx.AsyncClient,
        model: ModelInfo,
        semaphore: asyncio.Semaphore,
    ) -> ModelInfo:
        """Attach one model's window. Failures leave that model unchanged."""
        try:
            return await self._read_model_context(
                client,
                model,
                semaphore,
            )
        except Exception:
            logger.debug(
                "Ollama context enrichment failed for model %s",
                model.id,
                exc_info=True,
            )
            return model

    async def _read_model_context(
        self,
        client: httpx.AsyncClient,
        model: ModelInfo,
        semaphore: asyncio.Semaphore,
    ) -> ModelInfo:
        show_payload: dict[str, Any] | None = None

        async def _show() -> dict[str, Any] | None:
            try:
                response = await client.post(
                    f"{self.base_url}/api/show",
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
            return None

        async with semaphore:
            show_payload = await _show()

        detected = resolve_ollama_context_window(show_payload=show_payload)
        if detected is not None:
            return model.model_copy(
                update={"max_input_length_auto_detected": detected},
            )
        if show_payload is None:
            # Probe failed (timeout, auth, invalid body). Omit the field
            # so merge_discovered_model keeps any previous auto-detected
            # window instead of inventing a fallback.
            return model
        if _show_parameters_malformed(show_payload):
            # Malformed parameters are not "successful but unknown".
            # Keep any previous auto-detected window.
            return model
        # Successful show with no usable num_ctx: clear a stale
        # auto-detected value from an earlier discovery.
        return model.model_copy(
            update={"max_input_length_auto_detected": None},
        )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.credential._openai import OpenAICredential
        from agentscope.model import OpenAIChatModel

        from .openai_chat_model_compat import OpenAIChatModelCompat

        credential = OpenAICredential(
            id=f"qwenpaw-{self.id}",
            api_key=self.api_key or "ollama",
            base_url=self._openai_compatible_base_url(),
        )
        gen_kwargs = self.get_effective_generate_kwargs(model_id)
        parameters = OpenAIChatModel.Parameters(
            max_tokens=gen_kwargs.pop("max_tokens", None),
            temperature=gen_kwargs.pop("temperature", None),
            top_p=gen_kwargs.pop("top_p", None),
        )
        disable_kwargs = self.get_agent_thinking_kwargs(model_id, "off")
        disable_kwargs.pop("disable_thinking", None)
        return OpenAIChatModelCompat(
            credential=credential,
            provider_id=self.id,
            disable_thinking_kwargs=disable_kwargs,
            model=model_id,
            parameters=parameters,
            stream=True,
            default_headers=self._build_default_headers() or None,
            extra_generate_kwargs=gen_kwargs or None,
            context_size=self._get_context_size(model_id),
            formatter=_CappingOpenAIFormatter(
                max_bytes=self.max_inline_media_bytes,
                relay_reasoning_content=self._get_relay_reasoning(model_id),
            ),
        )
