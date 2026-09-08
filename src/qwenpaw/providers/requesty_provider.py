# -*- coding: utf-8 -*-
"""Requesty provider (OpenAI-compatible LLM router).

Requesty exposes a single OpenAI-compatible API in front of many upstream
vendors, so the standard ``OpenAIProvider`` flow works out of the box. Two
adjustments are needed on top of it:

* attribution headers (``HTTP-Referer`` / ``X-Title``) are attached to every
  request, matching what ``OpenRouterProvider`` does for OpenRouter;
* ``/v1/models`` uses a different field map than OpenAI/OpenRouter
  (``context_window`` instead of ``context_length``, an ``api`` field that
  distinguishes chat models from embedding/image/audio ones), so discovery
  is normalized here to surface only chat models with their limits.
"""

from __future__ import annotations

from typing import Any, List

from .openai_provider import OpenAIProvider
from .provider import ModelInfo


class RequestyProvider(OpenAIProvider):
    """OpenAI-compatible provider for the Requesty router."""

    _DEFAULT_HEADERS = {
        "HTTP-Referer": "https://qwenpaw.agentscope.io/",
        "X-Title": "QwenPaw",
    }

    def _build_default_headers(self) -> dict:
        # Attribution headers come first; user custom_headers can supplement
        # or override them.
        return {**self._DEFAULT_HEADERS, **self.custom_headers}

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        rows = getattr(payload, "data", [])
        for row in rows or []:
            model_id = str(getattr(row, "id", "") or "").strip()
            if not model_id:
                continue
            api = getattr(row, "api", None)
            if isinstance(api, str) and api.strip().lower() != "chat":
                continue
            model_name = (
                str(getattr(row, "name", "") or model_id).strip() or model_id
            )
            metadata: dict[str, Any] = {}
            context_window = getattr(row, "context_window", None)
            if isinstance(context_window, (int, float)) and (
                context_window >= 1000
            ):
                metadata["max_input_length_auto_detected"] = int(
                    context_window,
                )
            output_limit = getattr(row, "max_output_tokens", None)
            if isinstance(output_limit, (int, float)) and output_limit > 0:
                metadata["max_output_length"] = int(output_limit)
            supports_vision = getattr(row, "supports_vision", None)
            if isinstance(supports_vision, bool):
                metadata["supports_image"] = supports_vision
                metadata["supports_multimodal"] = supports_vision
                metadata["probe_source"] = "documentation"
            models.append(
                ModelInfo(id=model_id, name=model_name, **metadata),
            )

        deduped: List[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if model.id in seen:
                continue
            seen.add(model.id)
            deduped.append(model)
        return deduped
