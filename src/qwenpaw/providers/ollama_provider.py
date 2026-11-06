# -*- coding: utf-8 -*-
"""An Ollama provider implementation."""

from __future__ import annotations

import asyncio
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
from qwenpaw.utils.io_utils import run_sync_io

# Accept any positive context; ModelInfo allows ge=1 on auto_detected.
_MIN_CONTEXT_TOKENS = 1
# Bound concurrent /api/show probes when many models are installed.
_SHOW_PROBE_CONCURRENCY = 8

_NUM_CTX_RE = re.compile(
    r"(?m)^\s*num_ctx\s+(\d+)\s*$",
)


def parse_ollama_num_ctx(parameters: Any) -> int | None:
    """Return Modelfile ``num_ctx`` from an ``/api/show`` parameters block.

    Non-string values (a dict, list, or number) are ignored. Searching
    them used to raise ``TypeError`` and abort every model in the batch.
    """
    if not isinstance(parameters, str) or not parameters:
        return None
    match = _NUM_CTX_RE.search(parameters)
    if match is None:
        return None
    value = int(match.group(1))
    return value if value >= _MIN_CONTEXT_TOKENS else None


def resolve_ollama_context_window(
    *,
    show_payload: dict[str, Any] | None = None,
    served_context: int | None = None,
) -> int | None:
    """Pick the active Ollama context window for compaction.

    Precedence:

    1. ``/api/ps`` ``context_length`` when the model is currently loaded —
       this reflects ``OLLAMA_CONTEXT_LENGTH`` and the load-time window;
    2. explicit Modelfile ``num_ctx`` from a successful ``/api/show``.

    If neither is available, return ``None``. Do not invent a fallback:
    the server-level context is unknown until the model is loaded, and
    ``OLLAMA_CONTEXT_LENGTH`` may be below any guessed constant.

    ``show_payload is None`` means the probe failed (timeout, 401/403, or
    an invalid body). That is not an empty successful show: this returns
    ``None`` so the caller leaves the model unchanged (merge keeps any
    previous auto-detected window). A dict payload with no usable
    ``num_ctx`` also returns ``None``; the caller then clears a stale
    auto-detected value.

    A non-string ``parameters`` value is malformed, not an omitted
    ``num_ctx``. This also returns ``None``.

    GGUF ``*.context_length`` is the model's maximum supported context, not
    the window Ollama is serving. It is not used.
    """
    if (
        isinstance(served_context, int)
        and served_context >= _MIN_CONTEXT_TOKENS
    ):
        return served_context
    # Do not coerce None to {} — a failed probe must stay unset.
    if not isinstance(show_payload, dict):
        return None
    parameters = show_payload.get("parameters")
    if parameters is not None and not isinstance(parameters, str):
        return None
    return parse_ollama_num_ctx(parameters)


def _ollama_model_aliases(model_id: str) -> set[str]:
    """Match ids against ``/api/ps`` name/model fields (with/without tag)."""
    normalized = (model_id or "").strip()
    if not normalized:
        return set()
    aliases = {normalized, normalized.lower()}
    if ":" not in normalized:
        aliases.add(f"{normalized}:latest")
        aliases.add(f"{normalized}:latest".lower())
    else:
        base, _, tag = normalized.partition(":")
        if tag == "latest":
            aliases.add(base)
            aliases.add(base.lower())
    return aliases


def _with_served_context(
    model: ModelInfo,
    served: dict[str, int],
) -> ModelInfo | None:
    """Return a copy that uses a loaded ``/api/ps`` window, if present."""
    served_context: int | None = None
    for alias in _ollama_model_aliases(model.id):
        if alias not in served:
            continue
        raw = served[alias]
        served_context = raw if isinstance(raw, int) else None
        break
    if served_context is None or served_context < _MIN_CONTEXT_TOKENS:
        return None
    return model.model_copy(
        update={"max_input_length_auto_detected": served_context},
    )


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

        ``fetch_models`` also probes ``/api/show`` for every unloaded
        model. A connection check must not do that.
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
        """Headers for native ``/api/ps`` and ``/api/show`` probes.

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
        ``max_input_length_auto_detected`` from ``/api/show`` / ``/api/ps``,
        that value is used; otherwise the 128k default remains."""
        return False

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """List models, then attach Ollama's real context window when known.

        The OpenAI-compatible ``/v1/models`` rows do not carry context
        metadata, so without this step every Ollama model stays at the
        128k placeholder and compaction never aligns with ``num_ctx``.

        A failed ``/api/show`` leaves that model unchanged so merge can
        keep a previous auto-detected window. A successful show that
        omitted ``num_ctx`` (and with no served ``/api/ps`` window)
        explicitly clears ``max_input_length_auto_detected``, so a stale
        value from an earlier discovery is not retained.

        ``timeout`` bounds each native HTTP call and the ``/api/show``
        fan-out. Loaded ``/api/ps`` windows are applied before that
        deadline. When it expires, completed ``/api/ps`` and ``/api/show``
        results are kept; only unfinished probes stay unset.
        """
        models = await super().fetch_models(timeout=timeout)
        if not models:
            return models

        client: httpx.AsyncClient | None = None
        enriched: List[ModelInfo] | None = None
        try:
            # AsyncClient loads the default SSL context in __init__.
            # Build it off the event loop, same as dashscope discovery.
            client = await run_sync_io(
                httpx.AsyncClient,
                timeout=timeout,
                headers=self._native_probe_headers(),
            )
            enriched = await self._enrich_listed_models(
                client,
                models,
                timeout,
            )
            return enriched
        except Exception:
            # Setup failed before probing, or enrichment raised. Keep a
            # partial list once any probe has been recorded.
            if enriched is not None:
                return enriched
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
        """Attach ``/api/ps`` windows, then bounded ``/api/show`` probes.

        Served contexts are applied before the show deadline. A show that
        finishes in time is kept; a cancelled show leaves its model unset.
        """
        result = [model.model_copy() for model in models]
        try:
            served = await self._fetch_served_contexts(client)
            need_show: list[int] = []
            for index, model in enumerate(result):
                loaded = _with_served_context(model, served)
                if loaded is not None:
                    result[index] = loaded
                else:
                    need_show.append(index)
            if need_show:
                await self._probe_unloaded_models(
                    client,
                    result,
                    served,
                    need_show,
                    timeout,
                )
        except Exception:
            return result
        return result

    async def _probe_unloaded_models(
        self,
        client: httpx.AsyncClient,
        result: List[ModelInfo],
        served: dict[str, int],
        need_show: list[int],
        timeout: float,
    ) -> None:
        """Run ``/api/show`` until *timeout* and keep finished probes."""
        semaphore = asyncio.Semaphore(_SHOW_PROBE_CONCURRENCY)
        task_to_index: dict[asyncio.Task[ModelInfo], int] = {}
        for index in need_show:
            task = asyncio.create_task(
                self._enrich_model_context(
                    client,
                    result[index],
                    served,
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
                # cancelled, so those probes do not keep running.
                await asyncio.shield(
                    asyncio.gather(*pending, return_exceptions=True),
                )
            for task in done | pending:
                if not task.done() or task.cancelled():
                    continue
                index = task_to_index[task]
                try:
                    result[index] = task.result()
                except Exception:
                    continue

    async def _fetch_served_contexts(
        self,
        client: httpx.AsyncClient,
    ) -> dict[str, int]:
        """Map loaded model ids to their runtime ``context_length``."""
        try:
            response = await client.get(f"{self.base_url}/api/ps")
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return {}
        # Malformed /api/ps must not abort enrichment: return {} so
        # /api/show probes can still attach a valid num_ctx.
        if not isinstance(payload, dict):
            return {}
        models = payload.get("models")
        if models is None:
            models = []
        if not isinstance(models, (list, tuple)):
            return {}
        result: dict[str, int] = {}
        for row in models:
            if not isinstance(row, dict):
                continue
            raw = row.get("context_length")
            if raw is None:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value < _MIN_CONTEXT_TOKENS:
                continue
            for key in (row.get("name"), row.get("model")):
                name = str(key or "").strip()
                if name:
                    result[name] = value
                    result[name.lower()] = value
        return result

    async def _enrich_model_context(
        self,
        client: httpx.AsyncClient,
        model: ModelInfo,
        served: dict[str, int],
        semaphore: asyncio.Semaphore | None = None,
    ) -> ModelInfo:
        """Attach one model's window. Failures leave that model unchanged."""
        try:
            return await self._read_model_context(
                client,
                model,
                served,
                semaphore,
            )
        except Exception:
            return model

    async def _read_model_context(
        self,
        client: httpx.AsyncClient,
        model: ModelInfo,
        served: dict[str, int],
        semaphore: asyncio.Semaphore | None = None,
    ) -> ModelInfo:
        # /api/ps already has the final window; skip /api/show.
        loaded = _with_served_context(model, served)
        if loaded is not None:
            return loaded

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
                return None
            return None

        if semaphore is None:
            show_payload = await _show()
        else:
            async with semaphore:
                show_payload = await _show()

        detected = resolve_ollama_context_window(
            show_payload=show_payload,
            served_context=None,
        )
        if detected is not None:
            return model.model_copy(
                update={"max_input_length_auto_detected": detected},
            )
        if show_payload is None:
            # Probe failed (timeout, auth, invalid body). Omit the field
            # so merge_discovered_model keeps any previous auto-detected
            # window instead of inventing a fallback.
            return model
        # Successful show without usable num_ctx / served context: clear
        # a stale auto-detected value from an earlier discovery.
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
