# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,ungrouped-imports,wrong-import-order
"""DashScope multimodal-generation image provider (qwen-image-2.0-pro).

Endpoint:  POST {IMAGE_BASE_URL}
           (the base URL is already the full
           /api/v1/services/aigc/multimodal-generation/generation path)

Reference images must be publicly reachable URLs; local/generated images are
uploaded through DashScope's model-bound temporary storage (official Bailian
temporary-file upload, 48h TTL) and referenced as ``oss://`` URLs resolved by
the ``X-DashScope-OssResourceResolve: enable`` header.

Text-to-image and instruction editing share this endpoint (qwen-image puts
reference image blocks first and the text instruction last); in-image text
translation is a separate async task on
``/services/aigc/image2image/image-synthesis`` served by ``qwen-mt-image``
and polled through the generic ``/tasks/{task_id}`` API.
"""

import asyncio

import httpx

import os

from models import config as model_config
from models.media_transport import (
    read_reference_media,
    upload_reference_bytes_to_dashscope_temp,
    validate_reference_image_bytes,
)
from models.provider_tasks import note_provider_task
from utils.exceptions import ModelError
from utils.logger import setup_logger
from models.image.base import (
    BaseImageModel,
    _configured_int,
    _configured_value,
    download_remote_image,
    format_http_error_detail,
)

logger = setup_logger("model.image.dashscope")


# Map aspect ratio → DashScope multimodal size string (WIDTH*HEIGHT).
# qwen-image-2.0-pro accepts total pixels between 512*512 and 2048*2048.
DASHSCOPE_SIZE_MAP = {
    "16:9": "1664*928",
    "9:16": "928*1664",
    "1:1": "1328*1328",
    "4:3": "1472*1104",
    "3:4": "1104*1472",
    "3:2": "1472*976",
    "2:3": "976*1472",
}

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
DEFAULT_MODEL_NAME = "qwen-image-2.0-pro"

_GENERATION_SUFFIX = "/services/aigc/multimodal-generation/generation"
_TRANSLATE_SUBMIT_SUFFIX = "/services/aigc/image2image/image-synthesis"
_TRANSLATE_POLL_INTERVAL_SECONDS = 3.0
_TRANSLATE_RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class DashScopeImageModel(BaseImageModel):
    """DashScope multimodal-generation format, used by qwen-image-2.0-pro."""

    backend_name = "dashscope-multimodal"
    supported_modes = frozenset({"generate", "edit", "translate"})

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout: int,
        concurrency: int = 1,
    ) -> None:
        super().__init__(model_name, api_key, timeout, concurrency)
        # The base URL is already the full multimodal-generation endpoint.
        self.base_url = base_url

    @classmethod
    def from_config(cls) -> "DashScopeImageModel":
        """Build from the dedicated key-config system.

        The image model's key/base_url/model are managed independently by the
        frontend key-management UI, which persists them to the dedicated model
        config file (not .env) and are injected into the request-scoped Tool
        Config. Environment variables remain a standalone/local fallback. The
        generic ``IMAGE_*`` values are accepted after provider selection so an
        existing Creator deployment can use its one explicit image endpoint.
        """
        return cls(
            model_name=_configured_value(
                "model",
                "DASHSCOPE_IMAGE_MODEL_NAME",
                os.environ.get(
                    "DASHSCOPE_IMAGE_MODEL_NAME",
                    os.environ.get("IMAGE_MODEL_NAME", DEFAULT_MODEL_NAME),
                ),
            ),
            api_key=_configured_value(
                "api_key",
                "DASHSCOPE_IMAGE_API_KEY",
                os.environ.get(
                    "DASHSCOPE_IMAGE_API_KEY",
                    os.environ.get("IMAGE_API_KEY", ""),
                ),
            ),
            base_url=_configured_value(
                ("base_url", "endpoint"),
                "DASHSCOPE_IMAGE_BASE_URL",
                os.environ.get(
                    "DASHSCOPE_IMAGE_BASE_URL",
                    os.environ.get("IMAGE_BASE_URL", DEFAULT_BASE_URL),
                ),
            ),
            timeout=_configured_int(
                "timeout",
                "DASHSCOPE_IMAGE_TIMEOUT",
                int(
                    os.environ.get(
                        "DASHSCOPE_IMAGE_TIMEOUT",
                        os.environ.get("IMAGE_TIMEOUT", "240"),
                    )
                    or 240,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "DASHSCOPE_IMAGE_CONCURRENCY",
                int(
                    os.environ.get(
                        "DASHSCOPE_IMAGE_CONCURRENCY",
                        os.environ.get("IMAGE_CONCURRENCY", "1"),
                    )
                    or 1,
                ),
            ),
        )

    @property
    def generation_url(self) -> str:
        base = self.base_url.rstrip("/")
        suffix = "/services/aigc/multimodal-generation/generation"
        return base if base.endswith(suffix) else f"{base}{suffix}"

    @property
    def api_root(self) -> str:
        """The /api/v1 root shared by task submission and polling URLs."""

        base = self.base_url.rstrip("/")
        if base.endswith(_GENERATION_SUFFIX):
            return base[: -len(_GENERATION_SUFFIX)]
        return base

    async def _public_reference_url(
        self,
        raw_url: str,
        *,
        model_name: str | None = None,
    ) -> str | None:
        """Return a provider-resolvable URL for one reference image.

        Public HTTP(S) URLs pass through; local/generated media is uploaded
        to DashScope model-bound temporary storage (``oss://`` + resolve
        header). Corrupt local references return ``None`` so a stale project
        file cannot fail the whole request.

        ``model_name`` must be the model that will *consume* the URL: a
        temporary upload is bound to the model its policy was issued for
        (see :mod:`models.media_transport`), so translate uploads bind to
        ``qwen-mt-image`` rather than the generation model.
        """

        url = raw_url.strip()
        if not url:
            return None
        if url.startswith(("http://", "https://", "oss://")):
            return url
        media_bytes, filename = await read_reference_media(url)
        try:
            validate_reference_image_bytes(media_bytes)
        except ValueError:
            return None
        return await upload_reference_bytes_to_dashscope_temp(
            media_bytes,
            filename,
            api_key=self.api_key,
            model_name=model_name or self.model_name,
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
        mode: str = "generate",
    ) -> httpx.Response:
        body = await self._build_body(
            prompt,
            aspect_ratio,
            clean_reference_urls,
            mode,
        )
        return await client.post(
            self.generation_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                # Resolve oss:// temp-upload references server-side.
                "X-DashScope-OssResourceResolve": "enable",
            },
            json=body,
        )

    async def _build_body(
        self,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
        mode: str = "generate",
    ) -> dict:
        # Official qwen-image content order: reference image blocks first, then
        # the single text instruction last (see qwen-image / qwen-image-edit
        # docs). With no references this is a plain text-to-image request;
        # with references it becomes an image-editing request on the same
        # multimodal-generation endpoint.
        content: list[dict] = []
        for raw_url in dict.fromkeys(clean_reference_urls):
            public_url = await self._public_reference_url(raw_url)
            if public_url is None:
                if mode == "edit":
                    # An edit was authorized: silently dropping its input
                    # would bill a text-to-image render of something else.
                    raise ModelError(
                        "Image edit reference cannot be read or is not a "
                        f"decodable image: {raw_url[:120]}",
                        model_name=self.model_name,
                    )
                # A stale or corrupt project reference must not fail the
                # whole generation. Continue with the remaining references,
                # or as text-to-image when none are usable.
                continue
            content.append({"image": public_url})
        content.append({"text": prompt})

        return {
            "model": self.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    },
                ],
            },
            "parameters": {
                "size": DASHSCOPE_SIZE_MAP.get(aspect_ratio, "1328*1328"),
                # Upstream qwen-image sends watermark: false for both t2i
                # and edit; Creator media is watermark-free by default.
                "watermark": False,
            },
        }

    async def _decode(self, data: dict | list) -> str:
        output = data.get("output") if isinstance(data, dict) else None
        if not isinstance(output, dict):
            raise ModelError(
                f"No output in DashScope response: {data}",
                model_name=self.model_name,
            )
        for choice in output.get("choices") or []:
            message = (
                choice.get("message") if isinstance(choice, dict) else None
            )
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("image"):
                        return await download_remote_image(
                            str(block["image"]),
                            self.model_name,
                        )
            if isinstance(content, dict) and content.get("image"):
                return await download_remote_image(
                    str(content["image"]),
                    self.model_name,
                )
        raise ModelError(
            f"No image in DashScope response: {data}",
            model_name=self.model_name,
        )

    async def submit_translate_task(
        self,
        image_url: str,
        *,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Submit one qwen-mt-image translation and return its task id.

        The task is billed on acceptance, so the id is recorded in the
        paying Task's durable ledger before this returns: recovery resumes
        polling from there after a restart.
        """

        translate_model = model_config.get_image_translate_model_name()
        # The temporary upload must be bound to the model that resolves it.
        public_url = await self._public_reference_url(
            image_url,
            model_name=translate_model,
        )
        if public_url is None:
            raise ModelError(
                f"Image translate input is not a readable image: {image_url[:120]}",
                model_name=translate_model,
            )
        logger.info(
            "Submitting image translate task | model=%s, %s->%s",
            translate_model,
            source_lang,
            target_lang,
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.api_root}{_TRANSLATE_SUBMIT_SUFFIX}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "X-DashScope-Async": "enable",
                    "X-DashScope-OssResourceResolve": "enable",
                },
                json={
                    "model": translate_model,
                    "input": {
                        "image_url": public_url,
                        "source_lang": source_lang,
                        "target_lang": target_lang,
                        "ext": {"config": {"imageSegment": False}},
                    },
                },
            )
            response.raise_for_status()
            submitted = response.json()
        output = (
            submitted.get("output")
            if isinstance(submitted.get("output"), dict)
            else {}
        )
        task_id = str(output.get("task_id") or "").strip()
        if not task_id or len(task_id) > 128:
            raise ModelError(
                f"Image translate returned no task_id: {submitted}",
                model_name=translate_model,
            )
        note_provider_task(
            provider_task_id=task_id,
            model=translate_model,
            kind="image_translate",
        )
        return task_id

    async def poll_translate_task(self, task_id: str) -> dict:
        """One poll of a translation task.

        Returns ``{"status": ..., "image_url": ..., "error": ...}`` where
        status is ``RUNNING`` / ``SUCCEEDED`` / ``FAILED``; transient
        transport failures surface as ``RUNNING`` with ``transient`` set, so
        a caller (in-process wait or restart recovery) never abandons a paid
        task because of a rate limit.
        """

        translate_model = model_config.get_image_translate_model_name()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                poll = await client.get(
                    f"{self.api_root}/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            except httpx.TransportError as exc:
                return {
                    "status": "RUNNING",
                    "transient": f"{type(exc).__name__}: {exc}",
                }
            if poll.status_code in _TRANSLATE_RETRY_STATUS:
                return {
                    "status": "RUNNING",
                    "transient": (
                        f"HTTP {poll.status_code} "
                        f"{format_http_error_detail(poll)[:200]}"
                    ),
                }
            if poll.status_code >= 400:
                raise ModelError(
                    f"Image translate poll failed with status "
                    f"{poll.status_code} (task_id={task_id}): "
                    f"{format_http_error_detail(poll)[:400]}",
                    model_name=translate_model,
                )
            payload = poll.json()
        output = (
            payload.get("output")
            if isinstance(payload.get("output"), dict)
            else {}
        )
        status = str(output.get("task_status") or "").upper()
        if status == "SUCCEEDED":
            return {
                "status": "SUCCEEDED",
                "image_url": str(output.get("image_url") or "").strip(),
            }
        if status in {"FAILED", "CANCELED", "UNKNOWN"}:
            return {
                "status": "FAILED",
                "error": str(
                    output.get("message")
                    or output.get("code")
                    or payload.get("message")
                    or status,
                ),
            }
        return {"status": "RUNNING"}

    async def _translate(
        self,
        image_url: str,
        *,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Translate in-image text with qwen-mt-image (async task + poll).

        Protocol (verified against the Bailian qwen-mt-image API reference
        and the upstream ``qwen_image.py`` tool): submit with
        ``X-DashScope-Async: enable`` to ``image2image/image-synthesis``,
        then poll ``/tasks/{task_id}`` until SUCCEEDED and download
        ``output.image_url`` (24h TTL).

        Submission and polling are separate operations so restart recovery
        can resume the same paid task from the durable ledger.
        """

        translate_model = model_config.get_image_translate_model_name()
        task_id = await self.submit_translate_task(
            image_url,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        deadline = asyncio.get_running_loop().time() + max(self.timeout, 30)
        while True:
            result = await self.poll_translate_task(task_id)
            status = str(result.get("status") or "")
            if status == "SUCCEEDED":
                translated_url = str(result.get("image_url") or "")
                if not translated_url:
                    raise ModelError(
                        "Image translate succeeded without image_url "
                        f"(task_id={task_id})",
                        model_name=translate_model,
                    )
                return await download_remote_image(
                    translated_url,
                    translate_model,
                )
            if status == "FAILED":
                raise ModelError(
                    f"Image translate task failed: {result.get('error')}",
                    model_name=translate_model,
                )
            transient = result.get("transient")
            if transient:
                logger.warning(
                    "Image translate poll failed, retrying | task_id=%s: %s",
                    task_id,
                    transient,
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise ModelError(
                    f"Image translate did not finish within {self.timeout}s "
                    f"(task_id={task_id}); the task is billed, stays "
                    "retrievable for 24h, and Creator resumes polling it on "
                    "restart",
                    model_name=translate_model,
                )
            await asyncio.sleep(_TRANSLATE_POLL_INTERVAL_SECONDS)
