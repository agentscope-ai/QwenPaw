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

# ModelInfo.max_input_length_auto_detected requires >= 1000.
_MIN_CONTEXT_TOKENS = 1000

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


def parse_ollama_model_context_length(
    model_info: dict[str, Any] | None,
) -> int | None:
    """Return the GGUF ``*.context_length`` from an ``/api/show`` payload."""
    if not model_info:
        return None
    for key, raw in model_info.items():
        if not str(key).endswith(".context_length"):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= _MIN_CONTEXT_TOKENS:
            return value
    return None


def resolve_ollama_context_window(
    *,
    show_payload: dict[str, Any] | None = None,
    served_context: int | None = None,
) -> int | None:
    """Pick the best Ollama context signal for compaction.

    Precedence (most specific first):

    1. ``/api/ps`` ``context_length`` when the model is currently loaded —
       this reflects ``OLLAMA_CONTEXT_LENGTH`` and the load-time window;
    2. Modelfile ``num_ctx`` from ``/api/show`` ``parameters``;
    3. GGUF ``*.context_length`` from ``/api/show`` ``model_info``.

    Returns ``None`` when nothing usable is present so the caller keeps the
    128k default rather than inventing a window.
    """
    if (
        isinstance(served_context, int)
        and served_context >= _MIN_CONTEXT_TOKENS
    ):
        return served_context
    payload = show_payload or {}
    baked = parse_ollama_num_ctx(payload.get("parameters"))
    if baked is not None:
        return baked
    return parse_ollama_model_context_length(payload.get("model_info"))


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
        """Check if a specific model is reachable/usable"""
        models = await self.fetch_models(timeout=timeout)
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
        """
        models = await super().fetch_models(timeout=timeout)
        if not models:
            return models
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                served = await self._fetch_served_contexts(client)
                enriched = await asyncio.gather(
                    *[
                        self._enrich_model_context(client, model, served)
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
    ) -> ModelInfo:
        served_context = None
        for alias in _ollama_model_aliases(model.id):
            if alias in served:
                served_context = served[alias]
                break
        show_payload: dict[str, Any] | None = None
        try:
            response = await client.post(
                f"{self.base_url}/api/show",
                json={"model": model.id},
            )
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict):
                    show_payload = payload
        except Exception:
            show_payload = None
        detected = resolve_ollama_context_window(
            show_payload=show_payload,
            served_context=served_context,
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
        return OpenAIChatModelCompat(
            credential=credential,
            provider_id=self.id,
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
