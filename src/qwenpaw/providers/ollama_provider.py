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

# Accept any positive context; ModelInfo allows ge=1 on auto_detected.
_MIN_CONTEXT_TOKENS = 1
# Conservative estimate used only after a successful /api/show that omitted
# num_ctx and the model is not loaded. This is not a value Ollama reports.
# 4096 is Ollama's smallest documented default (<24 GiB VRAM); under-
# estimating is safer than the 128k placeholder. A failed probe must not
# apply this number.
# Ref: https://docs.ollama.com/context-length
_CONSERVATIVE_CONTEXT_TOKENS = 4096
# Bound concurrent /api/show probes when many models are installed.
_SHOW_PROBE_CONCURRENCY = 8

_NUM_CTX_RE = re.compile(
    r"(?m)^\s*num_ctx\s+(\d+)\s*$",
)


def parse_ollama_num_ctx(parameters: str | None) -> int | None:
    """Return Modelfile ``num_ctx`` from an ``/api/show`` parameters block."""
    if not parameters:
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
    use_conservative_fallback: bool = True,
) -> int | None:
    """Pick the active Ollama context window for compaction.

    Precedence:

    1. ``/api/ps`` ``context_length`` when the model is currently loaded —
       this reflects ``OLLAMA_CONTEXT_LENGTH`` and the load-time window;
    2. explicit Modelfile ``num_ctx`` from a successful ``/api/show``;
    3. ``_CONSERVATIVE_CONTEXT_TOKENS`` (4k) only when ``show_payload`` is
       a dict that omitted ``num_ctx`` and *use_conservative_fallback* is
       true. That 4k figure is a conservative estimate, not a value Ollama
       reported.

    ``show_payload is None`` means the probe failed (timeout, 401/403, or
    an invalid body). That is not an empty successful show: this returns
    ``None`` so the caller leaves the model unchanged.

    GGUF ``*.context_length`` is the model's maximum supported context, not
    the window Ollama is serving. It is not used.
    """
    if (
        isinstance(served_context, int)
        and served_context >= _MIN_CONTEXT_TOKENS
    ):
        return served_context
    # Do not coerce None to {} — a failed probe must not invent 4096.
    if not isinstance(show_payload, dict):
        return None
    explicit = parse_ollama_num_ctx(show_payload.get("parameters"))
    if explicit is not None:
        return explicit
    if use_conservative_fallback:
        return _CONSERVATIVE_CONTEXT_TOKENS
    return None


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

        A failed ``/api/show`` leaves that model unchanged. The 4k
        estimate applies only after a successful show that omitted
        ``num_ctx``.
        """
        models = await super().fetch_models(timeout=timeout)
        if not models:
            return models
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers=self._native_probe_headers(),
            ) as client:
                served = await self._fetch_served_contexts(client)
                semaphore = asyncio.Semaphore(_SHOW_PROBE_CONCURRENCY)
                enriched = await asyncio.gather(
                    *[
                        self._enrich_model_context(
                            client,
                            model,
                            served,
                            semaphore,
                        )
                        for model in models
                    ],
                )
            return list(enriched)
        except Exception:
            # Discovery must still return the model list if native probes fail.
            return models

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
        result: dict[str, int] = {}
        for row in payload.get("models") or []:
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
        served_context = None
        for alias in _ollama_model_aliases(model.id):
            if alias in served:
                served_context = served[alias]
                break
        # /api/ps already has the final window; skip /api/show.
        if (
            isinstance(served_context, int)
            and served_context >= _MIN_CONTEXT_TOKENS
        ):
            return model.model_copy(
                update={"max_input_length_auto_detected": served_context},
            )

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
            # None is a failed probe. 4096 applies only when show returned
            # a payload that simply omitted num_ctx.
            use_conservative_fallback=show_payload is not None,
        )
        if detected is None:
            return model
        return model.model_copy(
            update={"max_input_length_auto_detected": detected},
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
