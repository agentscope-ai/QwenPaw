# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=ungrouped-imports
"""Ideogram API image provider (Ideogram 3.0 / 4.0).

Endpoint:  POST {IMAGE_BASE_URL}/v1/{model}/generate  (multipart/form-data)
Protocol:  https://developer.ideogram.ai/api-reference/api-reference/generate-v3
           https://developer.ideogram.ai/api-reference/api-reference/generate-v4

Both generate endpoints are synchronous and authenticate with the
``Api-Key`` header. The two documented parameter sets differ:

- ``ideogram-v3``: ``prompt`` + ``aspect_ratio`` (enum such as ``16x9``)
  + ``rendering_speed``; a single reference image may be attached as
  ``character_reference_images`` (officially limited to 1 image, JPEG/
  PNG/WebP, <=25MB, whole request <50MB).
- ``ideogram-v4``: ``text_prompt`` + ``rendering_speed``; the endpoint
  documents no aspect-ratio or reference-image fields, so Creator treats
  it as text-to-image only and does not send an aspect ratio.

Result URLs are ephemeral signed links, so the image is downloaded and
persisted immediately.
"""

import mimetypes
import os
from pathlib import Path

import httpx

from models import config as model_config
from models.media_transport import (
    read_reference_media,
    validate_reference_image_bytes,
)
from utils.exceptions import ModelError
from utils.logger import setup_logger
from models.image.base import (
    BaseImageModel,
    _configured_int,
    _configured_value,
    download_remote_image,
    image_reference_limit,
)

logger = setup_logger("model.image.ideogram")

DEFAULT_BASE_URL = "https://api.ideogram.ai"
DEFAULT_MODEL_NAME = "ideogram-v3"

# Creator aspect ratio -> the documented ideogram-v3 aspect_ratio enum.
# 21:9 has no enum value, so it falls back to the widest documented one.
IDEOGRAM_V3_ASPECT_RATIOS = {
    "16:9": "16x9",
    "9:16": "9x16",
    "1:1": "1x1",
    "4:3": "4x3",
    "3:4": "3x4",
    "3:2": "3x2",
    "2:3": "2x3",
    "21:9": "16x9",
}

_SINGLE_REFERENCE_MAX_BYTES = 25 * 1024 * 1024


def _is_v4(model_name: str) -> bool:
    return model_name.strip().casefold().startswith("ideogram-v4")


class IdeogramImageModel(BaseImageModel):
    """Ideogram generate endpoint (multipart) for ideogram-v3 / ideogram-v4."""

    backend_name = "ideogram"

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout: int,
        concurrency: int = 1,
    ) -> None:
        super().__init__(model_name, api_key, timeout, concurrency)
        self.base_url = base_url

    @classmethod
    def from_config(cls) -> "IdeogramImageModel":
        """Read IDEOGRAM_IMAGE_* (legacy IMAGE_*) env / Tools config."""
        return cls(
            model_name=_configured_value(
                "model",
                "IDEOGRAM_IMAGE_MODEL_NAME",
                os.environ.get(
                    "IDEOGRAM_IMAGE_MODEL_NAME",
                    os.environ.get("IMAGE_MODEL_NAME", DEFAULT_MODEL_NAME),
                ),
            ),
            api_key=_configured_value(
                "api_key",
                "IDEOGRAM_IMAGE_API_KEY",
                os.environ.get(
                    "IDEOGRAM_IMAGE_API_KEY",
                    os.environ.get("IMAGE_API_KEY", ""),
                ),
            ),
            base_url=_configured_value(
                ("base_url", "endpoint"),
                "IDEOGRAM_IMAGE_BASE_URL",
                os.environ.get(
                    "IDEOGRAM_IMAGE_BASE_URL",
                    os.environ.get("IMAGE_BASE_URL", DEFAULT_BASE_URL),
                ),
            ),
            timeout=_configured_int(
                "timeout",
                "IDEOGRAM_IMAGE_TIMEOUT",
                int(
                    os.environ.get(
                        "IDEOGRAM_IMAGE_TIMEOUT",
                        os.environ.get("IMAGE_TIMEOUT", "240"),
                    )
                    or 240,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "IDEOGRAM_IMAGE_CONCURRENCY",
                int(
                    os.environ.get(
                        "IDEOGRAM_IMAGE_CONCURRENCY",
                        os.environ.get("IMAGE_CONCURRENCY", "0"),
                    )
                    or 0,
                )
                or model_config.get_media_parallelism(),
            ),
        )

    @property
    def generation_url(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/v1/{self.model_name}/generate"

    def _enforce_reference_budget(self, reference_count: int) -> None:
        limit = image_reference_limit(self.model_name)
        if limit is None:
            if reference_count:
                raise ModelError(
                    f"Ideogram model `{self.model_name}` has no registered "
                    "official reference capability; remove the reference "
                    "images or register the model's documented limit first",
                    model_name=self.model_name,
                )
            return
        if reference_count > limit:
            official = (
                f"at most {limit} reference image(s)"
                if limit
                else "no reference images (text-to-image only)"
            )
            raise ModelError(
                f"Ideogram model `{self.model_name}` officially accepts "
                f"{official}, got {reference_count}",
                model_name=self.model_name,
            )

    async def _request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
        mode: str = "generate",
    ) -> httpx.Response:
        del mode  # only "generate" reaches this provider
        self._enforce_reference_budget(len(clean_reference_urls))
        if _is_v4(self.model_name):
            data = {
                "text_prompt": prompt,
                "rendering_speed": "DEFAULT",
            }
            files: list = []
        else:
            data = {
                "prompt": prompt,
                "aspect_ratio": IDEOGRAM_V3_ASPECT_RATIOS.get(
                    aspect_ratio,
                    "16x9",
                ),
                "rendering_speed": "DEFAULT",
            }
            files = []
            for raw_url in clean_reference_urls[:1]:
                content, filename = await read_reference_media(raw_url)
                try:
                    validate_reference_image_bytes(content)
                except ValueError as exc:
                    raise ModelError(
                        "Ideogram reference image is not a decodable image: "
                        f"{raw_url[:120]} ({exc})",
                        model_name=self.model_name,
                    ) from exc
                if len(content) > _SINGLE_REFERENCE_MAX_BYTES:
                    raise ModelError(
                        "Ideogram reference images must be at most 25MB "
                        f"each, got {len(content)} bytes",
                        model_name=self.model_name,
                    )
                suffix = Path(filename or "").suffix.lower()
                mime_type = mimetypes.types_map.get(suffix, "image/png")
                files.append(
                    (
                        "character_reference_images",
                        (filename or "reference.png", content, mime_type),
                    ),
                )
        logger.info(
            "Ideogram image request | model=%s, references=%d",
            self.model_name,
            len(clean_reference_urls),
        )
        return await client.post(
            self.generation_url,
            headers={"Api-Key": self.api_key},
            data=data,
            files=files or None,
        )

    async def _decode(self, data: dict | list) -> dict:
        items = data.get("data") if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("is_image_safe") is False:
                    raise ModelError(
                        "Ideogram rejected the generation as unsafe "
                        "(is_image_safe=false); adjust the prompt",
                        model_name=self.model_name,
                    )
                if item.get("url"):
                    # Ephemeral signed URL; persist immediately.
                    local_url = await download_remote_image(
                        str(item["url"]),
                        self.model_name,
                    )
                    return {"url": local_url, "source_url": ""}
        raise ModelError(
            f"No image in Ideogram response: {str(data)[:400]}",
            model_name=self.model_name,
        )
