# -*- coding: utf-8 -*-
"""A Google Gemini provider implementation using AgentScope's native
GeminiChatModel."""

from __future__ import annotations

import logging
import time
from typing import Any, List

from agentscope.model import ChatModelBase
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from copaw.providers.multimodal_prober import (
    ProbeResult,
    _PROBE_IMAGE_B64,
    _PROBE_VIDEO_URL,
    _is_media_keyword_error,
)
from copaw.providers.provider import ModelInfo, Provider

logger = logging.getLogger(__name__)


class GeminiProvider(Provider):
    """Provider implementation for Google Gemini API."""

    def _client(self, timeout: float = 10) -> Any:
        return genai.Client(
            api_key=self.api_key,
            http_options=genai_types.HttpOptions(timeout=int(timeout * 1000)),
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

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.model import GeminiChatModel

        return GeminiChatModel(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            generate_kwargs=self.get_effective_generate_kwargs(model_id),
        )

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> ProbeResult:
        """Probe multimodal support using Gemini generateContent API.

        Gemini supports both image and video via inline_data.  Each
        modality is probed independently with a minimal payload.
        """
        img_ok, img_msg = await self._probe_image_support(model_id, timeout)
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
                    genai_types.Part(
                        text=(
                            "What is the single dominant color of this "
                            "image? Reply with ONLY the color name, "
                            "nothing else."
                        ),
                    ),
                ],
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=20,
                ),
            )
            answer = (response.text or "").lower().strip()
            if any(kw in answer for kw in ("red", "红")):
                result = True, f"Image supported (answer={answer!r})"
                elapsed = time.monotonic() - start_time
                logger.info(
                    "Image probe done: model=%s result=%s %.2fs",
                    model_id,
                    result[0],
                    elapsed,
                )
                return result
            result = (
                False,
                f"Model did not recognise image (answer={answer!r})",
            )
            elapsed = time.monotonic() - start_time
            logger.info(
                "Image probe done: model=%s result=%s %.2fs",
                model_id,
                result[0],
                elapsed,
            )
            return result
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
