# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=ungrouped-imports
"""OpenAI Images API image provider (routify / gpt-image-2).

Endpoint:  POST {IMAGE_BASE_URL}[/v1]/images/generations[/edits]
           (the /v1 segment is added only when the base URL lacks it)
Protocol:  https://developers.openai.com/api/reference/resources/images/methods/generate/
"""

import base64
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from models.media_transport import read_reference_media
from utils.exceptions import ModelError
from models.image.base import (
    BaseImageModel,
    _configured_int,
    _configured_value,
    download_remote_image,
    persist_image_bytes,
)


OPENAI_SIZE_MAP = {
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "1:1": "1024x1024",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "21:9": "2560x1080",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
}

DEFAULT_BASE_URL = "https://routify.alibaba-inc.com/protocol/openai"
DEFAULT_MODEL_NAME = "gpt-image-2"

# Cap the aggregate reference payload so 16 near-limit images cannot pile
# up hundreds of MiB in one request.
REFERENCE_IMAGES_TOTAL_MAX_BYTES = 256 * 1024 * 1024


async def build_reference_image_files(
    reference_image_urls: list[str],
) -> list[tuple[str, tuple[str, bytes, str]]]:
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    total_bytes = 0
    for index, raw_url in enumerate(
        dict.fromkeys(reference_image_urls[:16]),
        start=1,
    ):
        url = raw_url.strip()
        if not url:
            continue
        content, filename = await read_reference_media(url)
        total_bytes += len(content)
        if total_bytes > REFERENCE_IMAGES_TOTAL_MAX_BYTES:
            raise ModelError(
                "reference images exceed "
                f"{REFERENCE_IMAGES_TOTAL_MAX_BYTES} bytes in total",
                model_name=DEFAULT_MODEL_NAME,
            )
        suffix = Path(filename).suffix.lower()
        if not suffix:
            suffix = Path(urlparse(url).path).suffix.lower()
        mime_type = mimetypes.types_map.get(suffix, "image/png")
        safe_filename = filename or f"reference_{index}{suffix or '.png'}"
        files.append(("image", (safe_filename, content, mime_type)))
    return files


class OpenAIImageModel(BaseImageModel):
    """OpenAI Images API format: POST {base}[/v1]/images/generations[/edits]."""

    backend_name = "openai"

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        quality: str,
        timeout: int,
        concurrency: int = 1,
    ) -> None:
        super().__init__(model_name, api_key, timeout, concurrency)
        self.base_url = base_url
        self.quality = quality

    @classmethod
    def from_config(cls) -> "OpenAIImageModel":
        """Read OPENAI_IMAGE_* (legacy IMAGE_*) env / Tools config."""
        base_url = _configured_value(
            ("base_url", "endpoint"),
            "OPENAI_IMAGE_BASE_URL",
            os.environ.get(
                "OPENAI_IMAGE_BASE_URL",
                os.environ.get("IMAGE_BASE_URL", DEFAULT_BASE_URL),
            ),
        )
        return cls(
            model_name=_configured_value(
                "model",
                "OPENAI_IMAGE_MODEL_NAME",
                os.environ.get(
                    "OPENAI_IMAGE_MODEL_NAME",
                    os.environ.get("IMAGE_MODEL_NAME", DEFAULT_MODEL_NAME),
                ),
            ),
            api_key=_configured_value(
                "api_key",
                "OPENAI_IMAGE_API_KEY",
                os.environ.get(
                    "OPENAI_IMAGE_API_KEY",
                    os.environ.get("IMAGE_API_KEY", ""),
                ),
            ),
            base_url=base_url,
            quality=_configured_value(
                "quality",
                "OPENAI_IMAGE_QUALITY",
                os.environ.get(
                    "OPENAI_IMAGE_QUALITY",
                    os.environ.get("IMAGE_QUALITY", "low"),
                ),
            ),
            timeout=_configured_int(
                "timeout",
                "OPENAI_IMAGE_TIMEOUT",
                int(
                    os.environ.get(
                        "OPENAI_IMAGE_TIMEOUT",
                        os.environ.get("IMAGE_TIMEOUT", "120"),
                    )
                    or 120,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "OPENAI_IMAGE_CONCURRENCY",
                int(os.environ.get("OPENAI_IMAGE_CONCURRENCY", "1") or 1),
            ),
        )

    @property
    def generation_url(self) -> str:
        return self._url(clean_reference_urls=[])

    def _url(self, clean_reference_urls: list[str]) -> str:
        base = self.base_url.rstrip("/")
        resource = (
            "images/edits" if clean_reference_urls else "images/generations"
        )
        # UI-saved OpenAI endpoints usually already carry the version
        # segment (e.g. https://api.openai.com/v1); only prepend /v1 when
        # absent so both styles resolve to a single /v1/images/... path
        # instead of the broken /v1/v1/... duplicate.
        if base.endswith("/v1"):
            return f"{base}/{resource}"
        return f"{base}/v1/{resource}"

    async def _request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
    ) -> httpx.Response:
        url = self._url(clean_reference_urls)
        body = {
            "model": self.model_name,
            "prompt": prompt,
            "n": 1,
            "size": OPENAI_SIZE_MAP.get(aspect_ratio, "1536x1024"),
            "quality": self.quality,
            "output_format": "png",
            "stream": False,
        }

        if clean_reference_urls:
            files = await build_reference_image_files(clean_reference_urls)
            return await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={
                    key: str(value).lower()
                    if isinstance(value, bool)
                    else value
                    for key, value in body.items()
                },
                files=files,
            )
        return await client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json=body,
        )

    async def _decode(self, data: dict | list) -> str:
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", [])
        else:
            raise ModelError(
                f"Unexpected image response type: {type(data).__name__}",
                model_name=self.model_name,
            )
        if not items:
            raise ModelError(
                f"Empty data in response: {data}",
                model_name=self.model_name,
            )

        item = items[0]
        if isinstance(item, list) and item:
            item = item[0]
        if not isinstance(item, dict):
            raise ModelError(
                f"Unexpected image response item: {item}",
                model_name=self.model_name,
            )

        if item.get("b64_json"):
            img_bytes = base64.b64decode(item["b64_json"])
            return persist_image_bytes(
                img_bytes,
                self.model_name,
                "base64→file",
            )
        if item.get("url"):
            return await download_remote_image(
                str(item["url"]),
                self.model_name,
            )
        raise ModelError(
            f"No b64_json or url in response item: {item}",
            model_name=self.model_name,
        )
