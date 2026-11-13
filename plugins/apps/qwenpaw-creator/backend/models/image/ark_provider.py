# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=ungrouped-imports
"""Volcengine Ark image provider (Doubao Seedream family).

Endpoint:  POST {IMAGE_BASE_URL}/api/v3/images/generations
Protocol:  https://www.volcengine.com/docs/82379/1541523

The endpoint is synchronous. Reference images ride in the ``image``
field (a single URL string, or an array for multi-image input): public
HTTP(S) URLs pass through untouched, local/generated media is inlined
as ``data:<mime>;base64,...`` (each image <30MB per the Ark contract).

Official model IDs and documented input limits:

- ``doubao-seedream-5-0-pro-*``   — up to 10 reference images,
  pixel sizes within [1280x720, 2048x2048*1.1025].
- ``doubao-seedream-5-0-lite-*``  — up to 14 references.
- ``doubao-seedream-4-5-*``       — up to 14 references,
  pixel sizes within [2560x1440, 4096x4096].
- ``doubao-seedream-4-0-*``       — up to 14 references.

``sequential_image_generation`` is left at its documented default
(``disabled``): Creator renders exactly one image per call and 5.0 pro
does not accept the parameter at all.
"""

import base64
import os

import httpx

from models import config as model_config
from models.media_transport import (
    read_reference_media,
    reference_media_data_url,
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
    persist_image_bytes,
)

logger = setup_logger("model.image.ark")

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com"
DEFAULT_MODEL_NAME = "doubao-seedream-5-0-pro-260628"

_GENERATION_SUFFIX = "/api/v3/images/generations"

# Aspect ratio -> "WIDTHxHEIGHT" pixel size. The 1:1, 16:9 and 21:9 rows
# reproduce the official 2K tier examples (2048x2048 / 2848x1600 /
# 3136x1344); the remaining rows stay inside every documented per-model
# total-pixel window (the strictest intersection is [3686400, 4624220]
# across 4.0-5.0 pro), so one map serves the whole family.
ARK_SIZE_MAP = {
    "1:1": "2048x2048",
    "16:9": "2848x1600",
    "9:16": "1600x2848",
    "21:9": "3136x1344",
    "4:3": "2464x1856",
    "3:4": "1856x2464",
    "3:2": "2624x1744",
    "2:3": "1744x2624",
}


async def build_ark_reference_images(
    reference_image_urls: list[str],
    model_name: str,
) -> list[str]:
    """Resolve references into Ark-acceptable URL / data-URL strings."""

    resolved: list[str] = []
    for raw_url in reference_image_urls:
        url = raw_url.strip()
        if not url:
            continue
        if url.startswith(("http://", "https://")):
            resolved.append(url)
            continue
        content, filename = await read_reference_media(url)
        try:
            validate_reference_image_bytes(content)
        except ValueError as exc:
            raise ModelError(
                f"Seedream reference image is not a decodable image: "
                f"{url[:120]} ({exc})",
                model_name=model_name,
            ) from exc
        resolved.append(reference_media_data_url(content, filename))
    return resolved


class ArkImageModel(BaseImageModel):
    """Volcengine Ark images/generations format (doubao-seedream-*)."""

    backend_name = "ark"

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
    def from_config(cls) -> "ArkImageModel":
        """Read ARK_IMAGE_* (legacy IMAGE_*) env / Tools config."""
        return cls(
            model_name=_configured_value(
                "model",
                "ARK_IMAGE_MODEL_NAME",
                os.environ.get(
                    "ARK_IMAGE_MODEL_NAME",
                    os.environ.get("IMAGE_MODEL_NAME", DEFAULT_MODEL_NAME),
                ),
            ),
            api_key=_configured_value(
                "api_key",
                "ARK_IMAGE_API_KEY",
                os.environ.get(
                    "ARK_IMAGE_API_KEY",
                    os.environ.get("IMAGE_API_KEY", ""),
                ),
            ),
            base_url=_configured_value(
                ("base_url", "endpoint"),
                "ARK_IMAGE_BASE_URL",
                os.environ.get(
                    "ARK_IMAGE_BASE_URL",
                    os.environ.get("IMAGE_BASE_URL", DEFAULT_BASE_URL),
                ),
            ),
            timeout=_configured_int(
                "timeout",
                "ARK_IMAGE_TIMEOUT",
                int(
                    os.environ.get(
                        "ARK_IMAGE_TIMEOUT",
                        os.environ.get("IMAGE_TIMEOUT", "240"),
                    )
                    or 240,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "ARK_IMAGE_CONCURRENCY",
                int(
                    os.environ.get(
                        "ARK_IMAGE_CONCURRENCY",
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
        if base.endswith(_GENERATION_SUFFIX):
            return base
        return f"{base}{_GENERATION_SUFFIX}"

    def _enforce_reference_budget(self, reference_count: int) -> None:
        limit = image_reference_limit(self.model_name)
        if limit is None:
            if reference_count:
                raise ModelError(
                    f"Seedream image model `{self.model_name}` has no "
                    "registered official reference capability; remove the "
                    "reference images or register the model's documented "
                    "limit first",
                    model_name=self.model_name,
                )
            return
        if reference_count > limit:
            raise ModelError(
                f"Seedream image model `{self.model_name}` officially "
                f"accepts at most {limit} input reference images, got "
                f"{reference_count}",
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
        body: dict = {
            "model": self.model_name,
            "prompt": prompt,
            "size": ARK_SIZE_MAP.get(aspect_ratio, "2048x2048"),
            "response_format": "url",
            # Creator media is watermark-free; the documented default is true.
            "watermark": False,
        }
        if clean_reference_urls:
            resolved = await build_ark_reference_images(
                clean_reference_urls,
                self.model_name,
            )
            body["image"] = resolved[0] if len(resolved) == 1 else resolved
        logger.info(
            "Ark image request | model=%s, references=%d, size=%s",
            self.model_name,
            len(clean_reference_urls),
            body["size"],
        )
        return await client.post(
            self.generation_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json=body,
        )

    async def _decode(self, data: dict | list) -> dict:
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            error = data["error"]
            raise ModelError(
                f"Seedream generation failed: {error.get('code')}: "
                f"{error.get('message')}",
                model_name=self.model_name,
            )
        items = data.get("data") if isinstance(data, dict) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("url"):
                    # The returned URL expires after 24 hours; persist now.
                    local_url = await download_remote_image(
                        str(item["url"]),
                        self.model_name,
                    )
                    return {"url": local_url, "source_url": ""}
                if item.get("b64_json"):
                    local_url = persist_image_bytes(
                        base64.b64decode(item["b64_json"]),
                        self.model_name,
                        "ark-b64",
                    )
                    return {"url": local_url, "source_url": ""}
        raise ModelError(
            f"No image in Ark response: {str(data)[:400]}",
            model_name=self.model_name,
        )
