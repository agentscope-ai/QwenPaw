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
"""

import httpx

import os

from models.media_transport import (
    read_reference_media,
    upload_reference_bytes_to_dashscope_temp,
    validate_reference_image_bytes,
)
from utils.exceptions import ModelError
from models.image.base import (
    BaseImageModel,
    _configured_int,
    _configured_value,
    download_remote_image,
)


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


class DashScopeImageModel(BaseImageModel):
    """DashScope multimodal-generation format, used by qwen-image-2.0-pro."""

    backend_name = "dashscope-multimodal"

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
                        os.environ.get("IMAGE_TIMEOUT", "120"),
                    )
                    or 120,
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
        return self.base_url

    async def _request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
    ) -> httpx.Response:
        body = await self._build_body(
            prompt,
            aspect_ratio,
            clean_reference_urls,
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
    ) -> dict:
        # Official qwen-image content order: reference image blocks first, then
        # the single text instruction last (see qwen-image / qwen-image-edit
        # docs). With no references this is a plain text-to-image request;
        # with references it becomes an image-editing request on the same
        # multimodal-generation endpoint.
        content: list[dict] = []
        for raw_url in dict.fromkeys(clean_reference_urls):
            url = raw_url.strip()
            if not url:
                continue
            if url.startswith(("http://", "https://")):
                public_url = url
            else:
                media_bytes, filename = await read_reference_media(url)
                try:
                    validate_reference_image_bytes(media_bytes)
                except ValueError:
                    # A stale or corrupt project reference must not fail the
                    # whole generation. Continue with the remaining references,
                    # or as text-to-image when none are usable.
                    continue
                public_url = await upload_reference_bytes_to_dashscope_temp(
                    media_bytes,
                    filename,
                    api_key=self.api_key,
                    model_name=self.model_name,
                )
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
