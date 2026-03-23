# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, List

from agentscope.model import ChatModelBase
from openai import APIError, AsyncOpenAI

from copaw.providers.provider import ModelInfo, Provider

if TYPE_CHECKING:
    from copaw.providers.multimodal_prober import ProbeResult

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CODING_DASHSCOPE_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"


class OpenAIProvider(Provider):
    """Provider implementation for OpenAI API and compatible endpoints."""

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
        )

    @staticmethod
    def _normalize_models_payload(payload: Any) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        rows = getattr(payload, "data", [])
        for row in rows or []:
            model_id = str(getattr(row, "id", "") or "").strip()
            if not model_id:
                continue
            model_name = (
                str(getattr(row, "name", "") or model_id).strip() or model_id
            )
            models.append(ModelInfo(id=model_id, name=model_name))

        deduped: List[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if model.id in seen:
                continue
            seen.add(model.id)
            deduped.append(model)
        return deduped

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if OpenAI provider is reachable with current configuration."""
        if self.base_url == CODING_DASHSCOPE_BASE_URL:
            return True, ""
        client = self._client()
        try:
            await client.models.list(timeout=timeout)
            return True, ""
        except APIError:
            return False, f"API error when connecting to `{self.base_url}`"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`",
            )

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch available models."""
        try:
            client = self._client(timeout=timeout)
            payload = await client.models.list(timeout=timeout)
            models = self._normalize_models_payload(payload)
            return models
        except APIError:
            return []
        except Exception:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable"""
        model_id = (model_id or "").strip()
        if not model_id:
            return False, "Empty model ID"

        try:
            client = self._client(timeout=timeout)
            res = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "ping",
                            },
                        ],
                    },
                ],
                timeout=timeout,
                max_tokens=1,
                stream=True,
            )
            # consume the stream to ensure the model is actually responsive
            async for _ in res:
                break
            return True, ""
        except APIError:
            return False, f"API error when connecting to model '{model_id}'"
        except Exception:
            return (
                False,
                f"Unknown exception when connecting to model '{model_id}'",
            )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from .openai_chat_model_compat import OpenAIChatModelCompat

        client_kwargs = {"base_url": self.base_url}

        if self.base_url == DASHSCOPE_BASE_URL:
            client_kwargs["default_headers"] = {
                "x-dashscope-agentapp": json.dumps(
                    {
                        "agentType": "CoPaw",
                        "deployType": "UnKnown",
                        "moduleCode": "model",
                        "agentCode": "UnKnown",
                    },
                    ensure_ascii=False,
                ),
            }
        elif self.base_url == CODING_DASHSCOPE_BASE_URL:
            client_kwargs["default_headers"] = {
                "X-DashScope-Cdpl": json.dumps(
                    {
                        "agentType": "CoPaw",
                        "deployType": "UnKnown",
                        "moduleCode": "model",
                        "agentCode": "UnKnown",
                    },
                    ensure_ascii=False,
                ),
            }

        return OpenAIChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.api_key,
            stream_tool_parsing=False,
            client_kwargs=client_kwargs,
            generate_kwargs=self.generate_kwargs,
        )

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 10,
    ) -> ProbeResult:
        """Probe multimodal support via OpenAI-compatible API."""
        from .multimodal_prober import ProbeResult

        img_ok, img_msg = await self._probe_image_support(
            model_id,
            timeout,
        )
        vid_ok, vid_msg = await self._probe_video_support(
            model_id,
            timeout,
        )
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
        """Probe image support by sending a solid-red 16x16 PNG.

        Uses a two-stage check:
        1. If the API rejects the request → not supported.
        2. If accepted, verify the model can perceive the image.
        """
        from .multimodal_prober import (
            _PROBE_IMAGE_B64,
            _is_media_keyword_error,
        )

        logger.info(
            "Image probe start: model=%s url=%s",
            model_id,
            self.base_url,
        )
        start_time = time.monotonic()
        client = self._client(timeout=timeout)
        try:
            res = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": (
                                        "data:image/png;base64,"
                                        f"{_PROBE_IMAGE_B64}"
                                    ),
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "What is the single dominant "
                                    "color of this image? Reply "
                                    "with ONLY the color name, "
                                    "nothing else."
                                ),
                            },
                        ],
                    },
                ],
                max_tokens=200,
                timeout=timeout,
            )
            return self._evaluate_image_response(
                res,
                model_id,
                start_time,
            )
        except APIError as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            if e.status_code == 400 or _is_media_keyword_error(e):
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

    @staticmethod
    def _evaluate_image_response(
        res,
        model_id: str,
        start_time: float,
    ) -> tuple[bool, str]:
        """Evaluate image probe response."""
        answer = (res.choices[0].message.content or "").lower().strip()
        if any(kw in answer for kw in ("red", "红")):
            elapsed = time.monotonic() - start_time
            logger.info(
                "Image probe done: model=%s result=True %.2fs",
                model_id,
                elapsed,
            )
            return True, f"Image supported (answer={answer!r})"
        reasoning = ""
        msg = res.choices[0].message
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            reasoning = msg.reasoning_content.lower()
        if reasoning and any(kw in reasoning for kw in ("red", "红")):
            elapsed = time.monotonic() - start_time
            logger.info(
                "Image probe done: model=%s result=True %.2fs",
                model_id,
                elapsed,
            )
            return (
                True,
                f"Image supported (reasoning, answer={answer!r})",
            )
        elapsed = time.monotonic() - start_time
        logger.info(
            "Image probe done: model=%s result=False %.2fs",
            model_id,
            elapsed,
        )
        return (
            False,
            f"Model did not recognise image (answer={answer!r})",
        )

    async def _probe_video_support(
        self,
        model_id: str,
        timeout: float = 30,
    ) -> tuple[bool, str]:
        """Probe video support with automatic format fallback."""
        from .multimodal_prober import (
            _PROBE_VIDEO_B64,
            _PROBE_VIDEO_URL,
        )

        logger.info(
            "Video probe start: model=%s url=%s",
            model_id,
            self.base_url,
        )
        start_time = time.monotonic()
        video_urls = [
            f"data:video/mp4;base64,{_PROBE_VIDEO_B64}",
            _PROBE_VIDEO_URL,
        ]
        last_error_msg = ""
        for video_url in video_urls:
            result = await self._try_video_url(
                model_id,
                video_url,
                timeout,
                start_time=start_time,
            )
            if result is not None:
                return result
            last_error_msg = f"format rejected for {video_url}"
        elapsed = time.monotonic() - start_time
        logger.info(
            "Video probe done: model=%s result=False %.2fs",
            model_id,
            elapsed,
        )
        return False, f"Video not supported: {last_error_msg}"

    async def _try_video_url(
        self,
        model_id: str,
        video_url: str,
        timeout: float,
        *,
        start_time: float,
    ) -> tuple[bool, str] | None:
        """Try a single video URL format. Return None to try next."""
        from .multimodal_prober import (
            _PROBE_VIDEO_URL,
            _is_media_keyword_error,
        )

        is_http = video_url == _PROBE_VIDEO_URL
        req_timeout = timeout * 3 if is_http else timeout
        client = self._client(timeout=req_timeout)
        try:
            res = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {"url": video_url},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "What is the single dominant "
                                    "color shown in this video? "
                                    "Reply with ONLY the color "
                                    "name, nothing else."
                                ),
                            },
                        ],
                    },
                ],
                max_tokens=200,
                timeout=req_timeout,
            )
            return self._evaluate_video_response(
                res,
                model_id,
                start_time,
                is_http,
            )
        except APIError as e:
            status = getattr(e, "status_code", None)
            if status == 400:
                logger.debug(
                    "Video probe format rejected (400): %s",
                    e,
                )
                return None
            elapsed = time.monotonic() - start_time
            is_kw = _is_media_keyword_error(e)
            label = "not supported" if is_kw else "inconclusive"
            logger.warning(
                "Video probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            return False, f"Video {label}: {e}"
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

    @staticmethod
    def _evaluate_video_response(
        res,
        model_id: str,
        start_time: float,
        is_http: bool,
    ) -> tuple[bool, str]:
        """Evaluate video probe response."""
        answer = (res.choices[0].message.content or "").lower().strip()
        if any(kw in answer for kw in ("blue", "蓝")):
            elapsed = time.monotonic() - start_time
            logger.info(
                "Video probe done: model=%s result=True %.2fs",
                model_id,
                elapsed,
            )
            return True, f"Video supported (answer={answer!r})"
        reasoning = ""
        msg = res.choices[0].message
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            reasoning = msg.reasoning_content.lower()
        if reasoning and any(kw in reasoning for kw in ("blue", "蓝")):
            elapsed = time.monotonic() - start_time
            logger.info(
                "Video probe done: model=%s result=True %.2fs",
                model_id,
                elapsed,
            )
            return (
                True,
                f"Video supported (reasoning, answer={answer!r})",
            )
        if is_http and answer:
            elapsed = time.monotonic() - start_time
            logger.info(
                "Video probe done: model=%s result=True %.2fs",
                model_id,
                elapsed,
            )
            return True, f"Video supported (answer={answer!r})"
        elapsed = time.monotonic() - start_time
        logger.info(
            "Video probe done: model=%s result=False %.2fs",
            model_id,
            elapsed,
        )
        return (
            False,
            f"Model did not recognise video (answer={answer!r})",
        )
