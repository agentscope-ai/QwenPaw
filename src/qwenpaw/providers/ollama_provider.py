# -*- coding: utf-8 -*-
"""An Ollama provider implementation."""

from __future__ import annotations

import os
from typing import Any, List

from agentscope.model import ChatModelBase
from openai import AsyncOpenAI

from qwenpaw.providers.capping_formatter import _CappingOpenAIFormatter
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.ollama_discovery import enrich_listed_models
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelConnectionResult


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
        return await enrich_listed_models(
            self.base_url,
            self._native_probe_headers(),
            models,
            timeout,
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
