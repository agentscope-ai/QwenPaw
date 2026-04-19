# -*- coding: utf-8 -*-
"""Shared multimodal probing for OpenAI-compatible providers.

Providers that use the OpenAI chat completions API (OpenRouter, LMStudio,
etc.) can mix in :class:`OpenAICompatibleProbeMixin` to gain image and
video probing without duplicating the logic from
:class:`~qwenpaw.providers.openai_provider.OpenAIProvider`.
"""

import logging
import time

from openai import APIError

logger = logging.getLogger(__name__)


class OpenAICompatibleProbeMixin:
    """Mixin that adds ``probe_model_multimodal`` for any provider with
    a ``_client()`` method returning an ``openai.AsyncOpenAI`` instance.
    """

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 10,
    ):
        from .multimodal_prober import ProbeResult

        img_ok, img_msg = await self._probe_image_support(
            model_id,
            timeout,
        )
        if not img_ok:
            return ProbeResult(
                supports_image=False,
                supports_video=False,
                image_message=img_msg,
                video_message="Skipped: image probe failed",
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
        from .multimodal_prober import (
            _PROBE_IMAGE_B64,
            _IMAGE_PROBE_PROMPT,
            _is_media_keyword_error,
            evaluate_image_probe_answer,
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
                                        f"data:image/png;base64,{_PROBE_IMAGE_B64}"
                                    ),
                                },
                            },
                            {
                                "type": "text",
                                "text": _IMAGE_PROBE_PROMPT,
                            },
                        ],
                    },
                ],
                max_tokens=200,
                timeout=timeout,
            )
            answer = (res.choices[0].message.content or "").lower().strip()
            reasoning = ""
            msg = res.choices[0].message
            if hasattr(msg, "reasoning_content") and msg.reasoning_content:
                reasoning = msg.reasoning_content.lower()
            return evaluate_image_probe_answer(
                answer,
                model_id,
                start_time,
                reasoning,
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
            status = getattr(e, "status_code", None)
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
        answer = (res.choices[0].message.content or "").lower().strip()
        _BLUE_KW = (
            "blue",
            "navy",
            "azure",
            "cobalt",
            "cyan",
            "indigo",
            "蓝",
        )
        if any(kw in answer for kw in _BLUE_KW):
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
        if reasoning and any(kw in reasoning for kw in _BLUE_KW):
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
                "Video probe done: model=%s result=True (http) %.2fs",
                model_id,
                elapsed,
            )
            return True, f"Video supported (http, answer={answer!r})"
        elapsed = time.monotonic() - start_time
        logger.info(
            "Video probe done: model=%s result=False answer=%r %.2fs",
            model_id,
            answer,
            elapsed,
        )
        return (
            False,
            f"Model did not recognise video (answer={answer!r})",
        )
