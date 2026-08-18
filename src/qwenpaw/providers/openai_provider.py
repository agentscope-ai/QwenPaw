# -*- coding: utf-8 -*-
"""An OpenAI provider implementation."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Any, List
from urllib.parse import urlparse

import httpx

from agentscope.model import ChatModelBase
from openai import APIError
from pydantic import Field

from qwenpaw.providers.provider import (
    ModelConnectionResult,
    ModelInfo,
    Provider,
)

from .multimodal_prober import evaluate_video_probe_answer
from ..utils.logging import sanitize_log_value
from .capping_formatter import MAX_INLINE_MEDIA_BYTES, _CappingOpenAIFormatter

if TYPE_CHECKING:
    from qwenpaw.providers.multimodal_prober import ProbeResult

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URLS = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
)
CODING_DASHSCOPE_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
TOKEN_PLAN_BASE_URL = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)

_DASHSCOPE_HOSTNAMES = frozenset(
    {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    },
)
_NON_CHAT_TOKEN_KEYWORDS = frozenset(
    {"asr", "tts", "t2v", "i2v", "s2v", "kf2v", "r2v", "t2i", "i2i", "sora"},
)
_NON_CHAT_SUBSTRINGS = (
    "paraformer",
    "sensevoice",
    "gummy",
    "cosyvoice",
    "sambert",
    "whisper",
    "wanx",
    "embedding",
    "rerank",
    "qwen-image",
    "z-image",
    "gpt-image",
    "dall-e",
    "video-synthesis",
    "image-synthesis",
    "seedance",
    "seedream",
    "seededit",
)
_API_TYPE_MISMATCH_MARKERS = (
    "does not support asynchronous calls",
    "does not support synchronous calls",
)
_DASHSCOPE_UPLOAD_POLICY_PATH = "/api/v1/uploads"
_ARK_TASK_LIST_PATH = "/api/v3/contents/generations/tasks"
_DASHSCOPE_UNKNOWN_MODEL_MARKERS = ("not exist", "not found", "invalid model")


def _is_non_chat_model(model_id: str) -> bool:
    """Return whether a model id looks like a non-chat model."""
    name = model_id.strip().lower().rsplit("/", maxsplit=1)[-1]
    if any(sub in name for sub in _NON_CHAT_SUBSTRINGS):
        return True
    tokens = set(re.split(r"[^a-z0-9]+", name))
    return not tokens.isdisjoint(_NON_CHAT_TOKEN_KEYWORDS)


def _http_error_detail(resp: httpx.Response) -> str:
    """Extract a short human-readable error message from a response."""
    try:
        payload = resp.json()
    except Exception:
        return (resp.text or "")[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            payload = error
        message = payload.get("message") or payload.get("msg")
        code = payload.get("code")
        if message:
            return f"{code}: {message}" if code else str(message)
    return str(payload)[:300]


def _uses_max_completion_tokens(model_id: str) -> bool:
    """Return whether an OpenAI model requires max_completion_tokens."""
    model_name = model_id.strip().lower().rsplit("/", maxsplit=1)[-1]
    return model_name.startswith("gpt-5") or (
        len(model_name) > 1
        and model_name[0] == "o"
        and model_name[1].isdigit()
    )


def _token_limit_kwargs(model_id: str, limit: int) -> dict[str, int]:
    """Build the model-specific output token limit argument."""
    if _uses_max_completion_tokens(model_id):
        return {"max_completion_tokens": limit}
    return {"max_tokens": limit}


if os.environ.get("LANGFUSE_SECRET_KEY") and importlib.util.find_spec(
    "langfuse",
):
    from langfuse.openai import AsyncOpenAI  # type: ignore[import]
else:
    if os.environ.get("LANGFUSE_SECRET_KEY"):
        logger.warning(
            "LANGFUSE_SECRET_KEY is set but langfuse is not installed; "
            "install with `pip install langfuse` to enable tracing",
        )
    from openai import AsyncOpenAI  # pylint: disable=ungrouped-imports


class OpenAIProvider(Provider):
    """Provider implementation for OpenAI API and compatible endpoints."""

    max_inline_media_bytes: int = Field(
        default=MAX_INLINE_MEDIA_BYTES,
        ge=0,
        description=(
            "Maximum size (in bytes) of a local media file inlined as "
            "base64 into the model request body. Media above this is "
            "replaced with a text placeholder to avoid oversized requests "
            "when large files (e.g. generated videos) persist in "
            "conversation history. 0 disables capping."
        ),
    )

    def _build_default_headers(self) -> dict:
        return dict(self.custom_headers) if self.custom_headers else {}

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        kwargs: dict = {
            "base_url": self.base_url,
            "api_key": self.api_key,
            "timeout": timeout,
        }
        headers = self._build_default_headers()
        if headers:
            kwargs["default_headers"] = headers
        return AsyncOpenAI(**kwargs)

    @staticmethod
    async def _close_client(client: AsyncOpenAI) -> None:
        """Close a temporary SDK client when it owns async resources."""
        close = getattr(client, "close", None)
        if close is not None:
            await close()

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
            metadata: dict[str, Any] = {}
            for field in (
                "context_length",
                "max_model_len",
                "max_context_length",
            ):
                value = getattr(row, field, None)
                if isinstance(value, (int, float)) and value >= 1000:
                    metadata["max_input_length_auto_detected"] = int(value)
                    break
            output_limit = getattr(row, "max_output_tokens", None)
            if isinstance(output_limit, (int, float)) and output_limit > 0:
                metadata["max_tokens"] = int(output_limit)
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

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if OpenAI provider is reachable with current configuration."""
        client = self._client(timeout=timeout)
        try:
            await client.models.list(timeout=timeout)
            return True, ""
        except APIError as exc:
            detail = self.connection_error_message(exc)
            status = getattr(exc, "status_code", "unknown")
            return (
                False,
                f"API error when connecting to `{self.base_url}` "
                f"(status={status}): {detail}",
            )
        except Exception as exc:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`: "
                f"{self.connection_error_message(exc)}",
            )
        finally:
            await self._close_client(client)

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch available models."""
        client = self._client(timeout=timeout)
        try:
            payload = await client.models.list(timeout=timeout)
            models = self._normalize_models_payload(payload)
            return models
        except APIError:
            return []
        except Exception:
            return []
        finally:
            await self._close_client(client)

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> ModelConnectionResult:
        """Check that a model can complete a basic chat request."""
        model_id = (model_id or "").strip()
        if not model_id:
            return ModelConnectionResult(
                success=False,
                message="Empty model ID",
            )

        if _is_non_chat_model(model_id):
            return await self._check_non_chat_model_connection(
                model_id,
                timeout,
            )

        client = self._client(timeout=timeout)
        try:
            common_kwargs = {
                "model": model_id,
                "timeout": timeout,
                "stream": True,
                **_token_limit_kwargs(model_id, 20),
            }
            res = await client.chat.completions.create(
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
                **common_kwargs,
            )
            try:
                # Consume one event to ensure the model is responsive.
                async for _ in res:
                    break
            finally:
                await res.close()
            return ModelConnectionResult(success=True)
        except APIError as exc:
            detail = self.connection_error_message(exc)
            if any(
                marker in detail.lower()
                for marker in _API_TYPE_MISMATCH_MARKERS
            ):
                return ModelConnectionResult(
                    success=True,
                    message=(
                        f"Model '{model_id}' requires a dedicated non-chat "
                        "API; endpoint and credentials verified"
                    ),
                )
            status = getattr(exc, "status_code", "unknown")
            return ModelConnectionResult(
                success=False,
                message=(
                    f"API error when connecting to model '{model_id}' "
                    f"(status={status}): {detail}"
                ),
                http_status=status if isinstance(status, int) else None,
            )
        except Exception as exc:
            return ModelConnectionResult(
                success=False,
                message=(
                    f"Unknown exception when connecting to model "
                    f"'{model_id}': {self.connection_error_message(exc)}"
                ),
            )
        finally:
            await self._close_client(client)

    async def _check_non_chat_model_connection(
        self,
        model_id: str,
        timeout: float,
    ) -> ModelConnectionResult:
        """Validate a non-chat model without issuing a billable request.

        * DashScope: the model-bound upload-policy API
          (``GET /api/v1/uploads?action=getPolicy&model=...``) verifies
          the endpoint, the API key and the model name at zero cost.
        * Volcano Ark: the content-generation task-list API
          (``GET /api/v3/contents/generations/tasks``) verifies the
          endpoint and the API key at zero cost.
        * Other providers: fall back to provider-level reachability.
        """
        host = (urlparse(self.base_url).hostname or "").lower()
        if host in _DASHSCOPE_HOSTNAMES or host.endswith(
            ".dashscope.aliyuncs.com",
        ):
            success, message = await self._check_dashscope_non_chat_model(
                model_id,
                timeout,
            )
            return ModelConnectionResult(
                success=success,
                message=message,
                verification="provider_only",
            )
        if host == "volces.com" or host.endswith(".volces.com"):
            success, message = await self._check_ark_non_chat_credentials(
                model_id,
                timeout,
            )
            return ModelConnectionResult(
                success=success,
                message=message,
                verification="provider_only",
            )
        ok, msg = await self.check_connection(timeout=timeout)
        if not ok:
            return ModelConnectionResult(
                success=False,
                message=msg,
                verification="provider_only",
            )
        return ModelConnectionResult(
            success=True,
            message=(
                f"Model '{model_id}' is not a chat model; verified "
                "provider connectivity instead of a chat probe"
            ),
            verification="provider_only",
        )

    async def _check_dashscope_non_chat_model(
        self,
        model_id: str,
        timeout: float,
    ) -> tuple[bool, str]:
        """Probe a DashScope task-API model via the upload-policy API."""
        parsed = urlparse(self.base_url)
        policy_url = (
            f"{parsed.scheme}://{parsed.netloc}"
            f"{_DASHSCOPE_UPLOAD_POLICY_PATH}"
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    policy_url,
                    params={"action": "getPolicy", "model": model_id},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except Exception as exc:
            return False, f"Failed to reach `{policy_url}`: {exc}"
        if resp.status_code == 200:
            return (
                True,
                f"Model '{model_id}' verified via the DashScope "
                "upload-policy API (endpoint, API key and model binding "
                "checked without a billable request)",
            )
        detail = _http_error_detail(resp)
        if resp.status_code in (401, 403):
            return (
                False,
                f"DashScope rejected the API key "
                f"(status={resp.status_code}): {detail}",
            )
        lowered = detail.lower()
        if "model" in lowered and any(
            marker in lowered for marker in _DASHSCOPE_UNKNOWN_MODEL_MARKERS
        ):
            return (
                False,
                f"DashScope does not recognise model '{model_id}' "
                f"(status={resp.status_code}): {detail}",
            )
        if resp.status_code in (404, 408, 429) or resp.status_code >= 500:
            # These statuses prove nothing about the key: wrong base URL,
            # rate limiting or provider failure must surface as failures.
            return (
                False,
                f"DashScope upload-policy probe failed "
                f"(status={resp.status_code}): {detail}",
            )
        # Remaining 4xx: auth passed but the model cannot be probed via the
        # upload-policy API (e.g. TTS models without file input); the
        # endpoint and key are verified, which is the best zero-cost
        # signal available.
        return (
            True,
            f"DashScope endpoint and API key verified; model "
            f"'{model_id}' was not invoked to avoid charges ({detail})",
        )

    async def _check_ark_non_chat_credentials(
        self,
        model_id: str,
        timeout: float,
    ) -> tuple[bool, str]:
        """Verify Ark endpoint and key via the free task-list API."""
        parsed = urlparse(self.base_url)
        tasks_url = f"{parsed.scheme}://{parsed.netloc}{_ARK_TASK_LIST_PATH}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    tasks_url,
                    params={"page_size": 1},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except Exception as exc:
            return False, f"Failed to reach `{tasks_url}`: {exc}"
        if resp.status_code == 200:
            return (
                True,
                "Ark endpoint and API key verified via the task-list "
                f"API; model '{model_id}' was not invoked to avoid "
                "charges",
            )
        detail = _http_error_detail(resp)
        if resp.status_code in (401, 403):
            return (
                False,
                f"Volcano Ark rejected the API key "
                f"(status={resp.status_code}): {detail}",
            )
        # Endpoint variants (e.g. the coding plan) may not expose the
        # task-list API; fall back to provider-level reachability.
        ok, msg = await self.check_connection(timeout=timeout)
        if not ok:
            return False, msg
        return (
            True,
            f"Model '{model_id}' is not a chat model; verified "
            "provider connectivity instead of a chat probe",
        )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.credential._openai import OpenAICredential
        from agentscope.model import OpenAIChatModel

        from .openai_chat_model_compat import OpenAIChatModelCompat

        credential = OpenAICredential(
            id=f"qwenpaw-{self.id}",
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # Platform-specific headers injected per-request via extra_headers.
        merged_headers = self._build_default_headers()
        dashscope_meta = json.dumps(
            {
                "agentType": "QwenPaw",
                "deployType": "UnKnown",
                "moduleCode": "model",
                "agentCode": "UnKnown",
            },
            ensure_ascii=False,
        )
        if self.base_url in DASHSCOPE_BASE_URLS:
            merged_headers["x-dashscope-agentapp"] = dashscope_meta
        elif self.base_url in (CODING_DASHSCOPE_BASE_URL, TOKEN_PLAN_BASE_URL):
            merged_headers["X-DashScope-Cdpl"] = dashscope_meta

        gen_kwargs = self.get_effective_generate_kwargs(model_id)
        max_tokens = gen_kwargs.pop("max_tokens", None)
        if _uses_max_completion_tokens(model_id):
            if max_tokens is not None:
                gen_kwargs.setdefault(
                    "max_completion_tokens",
                    max_tokens,
                )
            max_tokens = None
        parameters = OpenAIChatModel.Parameters(
            max_tokens=max_tokens,
            temperature=gen_kwargs.pop("temperature", None),
            top_p=gen_kwargs.pop("top_p", None),
        )

        return OpenAIChatModelCompat(
            credential=credential,
            provider_id=self.id,
            model=model_id,
            parameters=parameters,
            stream=True,
            default_headers=merged_headers or None,
            extra_generate_kwargs=gen_kwargs or None,
            output_token_param=(
                "max_completion_tokens"
                if _uses_max_completion_tokens(model_id)
                else "max_tokens"
            ),
            context_size=self._get_context_size(model_id),
            formatter=_CappingOpenAIFormatter(
                max_bytes=self.max_inline_media_bytes,
                relay_reasoning_content=self._get_relay_reasoning(model_id),
            ),
        )

    async def probe_model_multimodal(
        self,
        model_id: str,
        timeout: float = 60,
        image_only: bool = False,
    ) -> ProbeResult:
        """Probe multimodal support via OpenAI-compatible API."""
        from .multimodal_prober import ProbeResult

        img_ok, img_msg = await self._probe_image_support(
            model_id,
            timeout,
        )
        # Skip video probe when image probe already failed: a model
        # that cannot perceive images will not perceive video either,
        # and some text-only models (e.g. qwen3-max) may randomly
        # guess the correct color keyword, causing false positives.
        if not img_ok:
            return ProbeResult(
                supports_image=False,
                supports_video=False,
                image_message=img_msg,
                video_message="Skipped: image probe failed",
            )
        if image_only:
            return ProbeResult(
                supports_image=img_ok,
                supports_video=False,
                image_message=img_msg,
                video_message="Skipped: image_only=True",
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
        1. If the API rejects the request (400 / media-keyword error)
           → not supported.
        2. If accepted, verify the model can *actually perceive* the
           image content via a semantic check
           (see ``evaluate_image_probe_answer``).

        Why a semantic check is necessary:
            Some models (e.g. qwen3-max via OpenAI-compatible API) silently
            accept image payloads without returning an error, yet they do NOT
            actually process the image — they simply ignore it and respond to
            the text prompt only.  A pure "did the API error?" check would
            produce false positives for these models.  The semantic check
            (asking for the dominant color and verifying the answer) catches
            this class of silent failures.
        """
        from .multimodal_prober import (
            _IMAGE_PROBE_PROMPT,
            _PROBE_IMAGE_B64,
            _is_media_keyword_error,
            evaluate_image_probe_answer,
        )

        log_model = sanitize_log_value(model_id)
        logger.info(
            "Image probe start: model=%s url=%s",
            log_model,
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
                                "text": _IMAGE_PROBE_PROMPT,
                            },
                        ],
                    },
                ],
                timeout=timeout,
                **_token_limit_kwargs(model_id, 200),
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
                log_model,
                type(e).__name__,
                sanitize_log_value(e),
                elapsed,
            )
            # 400 or media-keyword error → definitive rejection.
            # Other API errors are inconclusive (could be transient).
            # Use getattr because APITimeoutError lacks status_code.
            status = getattr(e, "status_code", None)
            if status == 400 or _is_media_keyword_error(e):
                return False, f"Image not supported: {e}"
            return False, f"Probe inconclusive: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Image probe error: model=%s type=%s msg=%s %.2fs",
                log_model,
                type(e).__name__,
                sanitize_log_value(e),
                elapsed,
            )
            return False, f"Probe failed: {e}"
        finally:
            await self._close_client(client)

    async def _probe_video_support(
        self,
        model_id: str,
        timeout: float = 30,
    ) -> tuple[bool, str]:
        """Probe video support with automatic format fallback."""
        from .multimodal_prober import _PROBE_VIDEO_B64, _PROBE_VIDEO_URL

        log_model = sanitize_log_value(model_id)
        logger.info(
            "Video probe start: model=%s url=%s",
            log_model,
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
            log_model,
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
                timeout=req_timeout,
                **_token_limit_kwargs(model_id, 200),
            )
            return self._evaluate_video_response(
                res,
                model_id,
                start_time,
                is_http,
            )
        except APIError as e:
            status = getattr(e, "status_code", None)
            # 400 means this specific video format was rejected, but the
            # model might accept a different format — return None to let
            # the caller try the next URL in the fallback list.
            if status == 400:
                logger.debug(
                    "Video probe format rejected (400): %s",
                    sanitize_log_value(e),
                )
                return None
            elapsed = time.monotonic() - start_time
            # If the error message contains media-related keywords
            # (e.g. "video", "vision"), it's a definitive rejection.
            is_kw = _is_media_keyword_error(e)
            label = "not supported" if is_kw else "inconclusive"
            logger.warning(
                "Video probe error: model=%s type=%s msg=%s %.2fs",
                sanitize_log_value(model_id),
                type(e).__name__,
                sanitize_log_value(e),
                elapsed,
            )
            return False, f"Video {label}: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Video probe error: model=%s type=%s msg=%s %.2fs",
                sanitize_log_value(model_id),
                type(e).__name__,
                sanitize_log_value(e),
                elapsed,
            )
            return False, f"Probe failed: {e}"
        finally:
            await self._close_client(client)

    @staticmethod
    def _evaluate_video_response(
        res,
        model_id: str,
        start_time: float,
        is_http: bool,
    ) -> tuple[bool, str]:
        """Evaluate video probe response.

        Delegates to the shared
        ``evaluate_video_probe_answer`` in
        ``multimodal_prober`` so all providers use the same
        colour-keyword list and logging.
        """
        answer = res.choices[0].message.content or ""
        reasoning = ""
        msg = res.choices[0].message
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            reasoning = msg.reasoning_content
        return evaluate_video_probe_answer(
            answer,
            model_id,
            start_time,
            reasoning=reasoning,
            is_http=is_http,
        )


class _FreeSuffixProviderMixin:
    """Mixin for providers that mark models as free by suffix."""

    _FREE_SUFFIX = "-free"

    async def fetch_models(
        self,
        timeout: float = 5,
    ) -> List[ModelInfo]:
        """Fetch models and mark free ones by suffix."""
        client = self._client(timeout=timeout)
        try:
            payload = await client.models.list(timeout=timeout)
        except Exception:
            return []
        finally:
            await self._close_client(client)

        suffix = self._FREE_SUFFIX
        models: List[ModelInfo] = []
        seen: set[str] = set()
        for row in getattr(payload, "data", []) or []:
            model_id = str(
                getattr(row, "id", "") or "",
            ).strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            is_free = model_id.endswith(suffix)
            display_name = (
                model_id.removesuffix(suffix)
                .replace("-", " ")
                .replace("/", " - ")
                .title()
            )
            models.append(
                ModelInfo(
                    id=model_id,
                    name=display_name,
                    is_free=is_free,
                ),
            )
        return models


class OpenCodeProvider(_FreeSuffixProviderMixin, OpenAIProvider):
    """OpenCode provider with dynamic free model detection."""

    _FREE_SUFFIX = "-free"


class KiloProvider(_FreeSuffixProviderMixin, OpenAIProvider):
    """Kilo Code provider with dynamic free model detection."""

    _FREE_SUFFIX = ":free"


class GitHubModelsProvider(OpenAIProvider):
    """GitHub Models provider.

    GitHub Models exposes an OpenAI-compatible chat completions endpoint at
    ``https://models.github.ai/inference``.  Unlike many OpenAI-compatible
    providers it does **not** implement the ``/models`` listing endpoint, so
    the generic ``OpenAIProvider.check_connection`` (which calls
    ``client.models.list()``) receives a 404 response.  This override checks
    connectivity by issuing a minimal chat completion request instead.
    """

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check connectivity via a tiny chat completion request."""
        # Prefer a built-in model; fall back to a well-known GitHub Models id.
        model_id = ""
        for candidate in ("openai/gpt-4o-mini", "gpt-4o-mini"):
            if any(m.id == candidate for m in self.models):
                model_id = candidate
                break
        if not model_id:
            model_id = (
                self.models[0].id if self.models else "openai/gpt-4o-mini"
            )

        client = self._client(timeout=timeout)
        try:
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
                stream=True,
                **_token_limit_kwargs(model_id, 5),
            )
            try:
                async for _ in res:
                    break
            finally:
                await res.response.aclose()
            return True, ""
        except APIError as exc:
            detail = self.connection_error_message(exc)
            status = getattr(exc, "status_code", "unknown")
            return (
                False,
                f"API error when connecting to `{self.base_url}` "
                f"(status={status}): {detail}",
            )
        except Exception as exc:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`: "
                f"{self.connection_error_message(exc)}",
            )
        finally:
            await self._close_client(client)
