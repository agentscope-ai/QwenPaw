# -*- coding: utf-8 -*-
"""A Google Gemini provider implementation using AgentScope's native
GeminiChatModel."""

from __future__ import annotations

import logging
import time
from typing import Any, List

from agentscope.model import ChatModelBase, GeminiChatModel
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from qwenpaw.providers.multimodal_prober import (
    ProbeResult,
    _PROBE_IMAGE_B64,
    _IMAGE_PROBE_PROMPT,
    _PROBE_VIDEO_URL,
    _is_media_keyword_error,
    evaluate_image_probe_answer,
)
from qwenpaw.providers.provider import ModelInfo, Provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini tool schema sanitisation
# ---------------------------------------------------------------------------
# Gemini's function-calling API validates tool schemas against a strict subset
# of JSON Schema / OpenAPI 3.0.  Two patterns that are valid JSON Schema but
# rejected by Gemini with 400 INVALID_ARGUMENT:
#
#   1. ``additionalProperties`` – Gemini function calling does not recognise
#      this keyword at all (neither boolean nor schema object).  The error is
#      'Unknown name "additional_properties"'.
#
#   2. ``{"type": "null"}`` inside ``anyOf``  –  Python's ``Optional[X]``
#      annotation produces ``anyOf: [X, {"type": "null"}]``.  Gemini does
#      not support ``type: null``; the correct idiom is ``nullable: true``
#      on the non-null schema.
#
# This sanitiser fixes both issues before schemas reach the Gemini SDK.

# JSON Schema keywords whose value is itself a full schema object.
_SINGLE_SCHEMA_KEYWORDS = frozenset(
    {
        "items",
        "additionalItems",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
    },
)
_ARRAY_SCHEMA_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_MAP_SCHEMA_KEYWORDS = frozenset(
    {
        "properties",
        "patternProperties",
        "$defs",
        "definitions",
        "dependentSchemas",
    },
)


# pylint: disable=too-many-return-statements, too-many-branches
def _sanitize_schema_for_gemini(schema: Any) -> Any:
    """Recursively sanitize a JSON Schema dict for Gemini API compatibility.

    Transformations applied:

    * ``anyOf: [X, {"type": "null"}]``  →  ``{...X, "nullable": true}``
      (Python ``Optional[X]`` pattern).  Extra top-level fields such as
      ``default`` and ``description`` are preserved.
    * ``additionalProperties``  →  removed entirely (Gemini function
      calling does not recognise this keyword at all – not as boolean
      and not as schema object).
    * Any bare boolean schema (``true`` / ``false``) in a schema position
      is replaced with ``{}`` / ``{"not": {}}`` respectively.
    * ``required: <bool>``  →  removed (malformed; real JSON Schema uses
      ``required: ["field"]`` on the parent object).
    """
    if schema is True:
        return {}
    if schema is False:
        return {"not": {}}
    if not isinstance(schema, dict):
        return schema

    # --- anyOf / oneOf: collapse Optional[X] → nullable: true -------------
    for kw in ("anyOf", "oneOf"):
        if kw not in schema:
            continue
        variants = schema[kw]
        if not isinstance(variants, list):
            continue
        non_null = [
            v
            for v in variants
            if not (isinstance(v, dict) and v.get("type") == "null")
        ]
        has_null = len(non_null) < len(variants)
        if not has_null:
            continue
        extra = {
            k: v
            for k, v in schema.items()
            if k not in (kw, "nullable", "additionalProperties")
        }
        if len(non_null) == 0:
            return {**extra, "nullable": True}
        if len(non_null) == 1:
            merged = dict(_sanitize_schema_for_gemini(non_null[0]))
            merged["nullable"] = True
            for k, v in extra.items():
                merged.setdefault(k, v)
            return merged
        sanitized_variants = [_sanitize_schema_for_gemini(v) for v in non_null]
        return {**extra, kw: sanitized_variants, "nullable": True}

    # --- Recurse through remaining keywords --------------------------------
    result: dict[str, Any] = {}
    for key, value in schema.items():
        # Gemini function calling does not support additionalProperties at all
        if key == "additionalProperties":
            continue
        if key == "required" and isinstance(value, bool):
            continue

        if key in _SINGLE_SCHEMA_KEYWORDS:
            if key == "items" and isinstance(value, list):
                result[key] = [_sanitize_schema_for_gemini(v) for v in value]
            else:
                result[key] = _sanitize_schema_for_gemini(value)
        elif key in _ARRAY_SCHEMA_KEYWORDS:
            result[key] = (
                [_sanitize_schema_for_gemini(v) for v in value]
                if isinstance(value, list)
                else value
            )
        elif key in _MAP_SCHEMA_KEYWORDS:
            result[key] = (
                {k: _sanitize_schema_for_gemini(v) for k, v in value.items()}
                if isinstance(value, dict)
                else value
            )
        elif key == "dependencies" and isinstance(value, dict):
            result[key] = {
                k: (
                    _sanitize_schema_for_gemini(v)
                    if isinstance(v, (dict, bool))
                    else v
                )
                for k, v in value.items()
            }
        else:
            result[key] = value
    return result


def _sanitize_tool_schemas_for_gemini(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sanitize OpenAI-format tool schemas for Gemini API compatibility.

    Applies :func:`_sanitize_schema_for_gemini` to the ``parameters`` of
    each tool's function definition before they are passed to
    :meth:`GeminiChatModel._format_tools_json_schemas`.
    """
    sanitized = []
    for tool in tools:
        if not isinstance(tool, dict):
            sanitized.append(tool)
            continue
        func = tool.get("function")
        if not isinstance(func, dict):
            sanitized.append(tool)
            continue
        params = func.get("parameters")
        if not isinstance(params, dict):
            sanitized.append(tool)
            continue
        sanitized.append(
            {
                **tool,
                "function": {
                    **func,
                    "parameters": _sanitize_schema_for_gemini(params),
                },
            },
        )
    return sanitized


# Monkey-patch GeminiChatModel to sanitize tool schemas before they reach
# the Gemini SDK.  This avoids creating a subclass and keeps the rest of
# the codebase (model_factory formatter map, provider instance creation)
# working with the vanilla GeminiChatModel class.
_original_format_tools_json_schemas = (
    # pylint: disable=protected-access
    GeminiChatModel._format_tools_json_schemas
)


def _patched_format_tools_json_schemas(
    self: Any,
    schemas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _original_format_tools_json_schemas(
        self,
        _sanitize_tool_schemas_for_gemini(schemas),
    )


# pylint: disable=protected-access
GeminiChatModel._format_tools_json_schemas = _patched_format_tools_json_schemas


class GeminiProvider(Provider):
    """Provider implementation for Google Gemini API."""

    def _build_default_headers(self) -> dict:
        return dict(self.custom_headers) if self.custom_headers else {}

    def _client(self, timeout: float = 10) -> Any:
        headers = self._build_default_headers() or None
        return genai.Client(
            api_key=self.api_key,
            http_options=genai_types.HttpOptions(
                timeout=int(timeout * 1000),
                headers=headers,
            ),
        )

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        for row in payload or []:
            model_id = str(getattr(row, "name", "") or "").strip()

            if not model_id:
                continue

            # Gemini API returns model names like "models/gemini-2.5-flash"
            # Strip the "models/" prefix for cleaner IDs
            if model_id.startswith("models/"):
                model_id = model_id[len("models/") :]

            display_name = str(
                getattr(row, "display_name", "") or model_id,
            ).strip()

            if not display_name or display_name.startswith("models/"):
                display_name = model_id

            models.append(ModelInfo(id=model_id, name=display_name))

        deduped: List[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if model.id in seen:
                continue
            seen.add(model.id)
            deduped.append(model)
        return deduped

    async def check_connection(self, timeout: float = 10) -> tuple[bool, str]:
        """Check if Google Gemini provider is reachable."""
        try:
            client = self._client(timeout=timeout)
            # Use the async list models endpoint to verify connectivity
            async for _ in await client.aio.models.list():
                break
            return True, ""
        except genai_errors.APIError:
            return (
                False,
                "Failed to connect to Google Gemini API. "
                "Check your API key.",
            )
        except Exception:
            return (
                False,
                "Unknown exception when connecting to Google Gemini API.",
            )

    async def fetch_models(self, timeout: float = 10) -> List[ModelInfo]:
        """Fetch available models from Gemini API."""
        try:
            client = self._client(timeout=timeout)
            payload = []
            async for model in await client.aio.models.list():
                payload.append(model)
            models = self._normalize_models_payload(payload)
            return models
        except genai_errors.APIError:
            return []
        except Exception:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> tuple[bool, str]:
        """Check if a specific Gemini model is reachable/usable."""
        target = (model_id or "").strip()
        if not target:
            return False, "Empty model ID"

        try:
            client = self._client(timeout=timeout)
            response = await client.aio.models.generate_content_stream(
                model=target,
                contents="ping",
            )
            async for _ in response:
                break
            return True, ""
        except genai_errors.APIError:
            return (
                False,
                f"Model '{model_id}' is not reachable or usable",
            )
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to model '{model_id}'",
            )

    @staticmethod
    def _adapt_generate_kwargs_for_gemini(
        kwargs: dict,
    ) -> dict:
        """Translate OpenAI-style keys to Gemini's GenerateContentConfig
        schema.

        google-genai's GenerateContentConfig forbids extra fields, so
        ``max_tokens`` must be renamed to ``max_output_tokens``.  If both are
        present, the explicit ``max_output_tokens`` wins.
        """
        adapted = dict(kwargs)
        max_tokens = adapted.pop("max_tokens", None)
        if max_tokens is not None and "max_output_tokens" not in adapted:
            adapted["max_output_tokens"] = max_tokens
        return adapted

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        client_kwargs: dict = {}
        headers = self._build_default_headers()
        if headers:
            client_kwargs["http_options"] = genai_types.HttpOptions(
                headers=headers,
            )
        generate_kwargs = self._adapt_generate_kwargs_for_gemini(
            self.get_effective_generate_kwargs(model_id),
        )
        return GeminiChatModel(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            client_kwargs=client_kwargs or None,
            generate_kwargs=generate_kwargs,
        )

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 60,
        image_only: bool = False,
    ) -> ProbeResult:
        """Probe multimodal support using Gemini generateContent API.

        Gemini supports both image and video via inline_data.  Each
        modality is probed independently with a minimal payload.
        """
        img_ok, img_msg = await self._probe_image_support(model_id, timeout)
        if image_only:
            return ProbeResult(
                supports_image=img_ok,
                supports_video=False,
                image_message=img_msg,
                video_message="Skipped: image_only=True",
            )
        vid_ok, vid_msg = await self._probe_video_support(model_id, timeout)
        return ProbeResult(
            supports_image=img_ok,
            supports_video=vid_ok,
            image_message=img_msg,
            video_message=vid_msg,
        )

    async def _probe_image_support(
        self,
        model_id: str,
        timeout: float = 15,
    ) -> tuple[bool, str]:
        """Probe image support via Gemini generateContent with inline_data.

        Sends a solid-red 16x16 PNG and asks the model to name the colour.
        """
        import base64

        logger.info(
            "Image probe start: model=%s url=%s",
            model_id,
            self.base_url,
        )
        start_time = time.monotonic()
        client = self._client(timeout=timeout)
        try:
            image_bytes = base64.b64decode(_PROBE_IMAGE_B64)
            response = await client.aio.models.generate_content(
                model=model_id,
                contents=[
                    genai_types.Part(
                        inline_data=genai_types.Blob(
                            mime_type="image/png",
                            data=image_bytes,
                        ),
                    ),
                    genai_types.Part(text=_IMAGE_PROBE_PROMPT),
                ],
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=20,
                ),
            )
            answer = response.text or ""
            return evaluate_image_probe_answer(
                answer,
                model_id,
                start_time,
            )
        except genai_errors.APIError as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            status = getattr(e, "code", None)
            if status == 400 or _is_media_keyword_error(e):
                return False, f"Image not supported: {e}"
            return False, f"Probe inconclusive: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            return False, f"Probe failed: {e}"

    async def _probe_video_support(
        self,
        model_id: str,
        timeout: float = 30,
    ) -> tuple[bool, str]:
        """Probe video support via Gemini generateContent with a video URL.

        Asks the model whether the video contains moving content.
        """
        logger.info(
            "Video probe start: model=%s url=%s",
            model_id,
            self.base_url,
        )
        start_time = time.monotonic()
        client = self._client(timeout=timeout)
        try:
            response = await client.aio.models.generate_content(
                model=model_id,
                contents=[
                    genai_types.Part(
                        file_data=genai_types.FileData(
                            file_uri=_PROBE_VIDEO_URL,
                            mime_type="video/mp4",
                        ),
                    ),
                    genai_types.Part(
                        text=(
                            "Does this contain moving content? "
                            "Reply with ONLY 'yes' or 'no', nothing else."
                        ),
                    ),
                ],
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=10,
                ),
            )
            answer = (response.text or "").lower().strip()
            if "yes" in answer:
                result = True, f"Video supported (answer={answer!r})"
                elapsed = time.monotonic() - start_time
                logger.info(
                    "Video probe done: model=%s result=%s %.2fs",
                    model_id,
                    result[0],
                    elapsed,
                )
                return result
            result = (
                False,
                f"Model did not recognise video (answer={answer!r})",
            )
            elapsed = time.monotonic() - start_time
            logger.info(
                "Video probe done: model=%s result=%s %.2fs",
                model_id,
                result[0],
                elapsed,
            )
            return result
        except genai_errors.APIError as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Video probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            status = getattr(e, "code", None)
            if status == 400 or _is_media_keyword_error(e):
                return False, f"Video not supported: {e}"
            return False, f"Probe inconclusive: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Video probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            return False, f"Probe failed: {e}"
