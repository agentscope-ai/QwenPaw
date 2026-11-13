# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=ungrouped-imports
"""Google Gemini API image provider (Nano Banana family).

Endpoint:  POST {IMAGE_BASE_URL}/models/{model}:generateContent
Protocol:  https://ai.google.dev/api/generate-content

The request follows the official generateContent contract: reference
images travel as ``inlineData`` Blob parts (base64) ahead of the text
part, and ``generationConfig.imageConfig`` carries the documented
``aspectRatio`` / ``imageSize`` fields. The response is synchronous; the
generated image comes back as an ``inlineData`` part in the first
candidate.

Official model IDs and input-reference budgets (see
https://ai.google.dev/gemini-api/docs/image-generation):

- ``gemini-3-pro-image``            — up to 14 reference images
  (6 objects + 5 characters + 3 style), 1K/2K/4K output.
- ``gemini-3.1-flash-image``        — up to 14 references (10 objects +
  4 characters), 512/1K/2K/4K output.
- ``gemini-3.1-flash-lite-image``   — up to 14 references, 1K only.
- ``gemini-2.5-flash-image``        — works best with up to 3 references,
  fixed 1024px output (no ``imageSize``).
"""

import base64
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
    image_reference_limit,
    persist_image_bytes,
)

logger = setup_logger("model.image.gemini")

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL_NAME = "gemini-3-pro-image"

# generationConfig.imageConfig.aspectRatio official enumeration.
GEMINI_ASPECT_RATIOS = frozenset(
    {
        "1:1",
        "1:4",
        "4:1",
        "1:8",
        "8:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
    },
)

# imageSize support per official model table: 3 Pro and 3.1 Flash offer
# 1K/2K/4K (Flash adds 512), Flash Lite is 1K only, and 2.5 Flash has a
# fixed 1024px output so no imageSize is sent at all.
_IMAGE_SIZE_BY_MODEL = (
    ("gemini-3-pro-image", "2K"),
    ("gemini-3.1-flash-image", "2K"),
    ("gemini-3.1-flash-lite-image", "1K"),
)


def _image_size_for(model_name: str) -> str | None:
    lowered = model_name.strip().casefold()
    for prefix, size in _IMAGE_SIZE_BY_MODEL:
        if lowered.startswith(prefix):
            return size
    return None


async def build_inline_image_parts(
    reference_image_urls: list[str],
    model_name: str,
) -> list[dict]:
    """Read references and encode them as generateContent inlineData parts."""

    parts: list[dict] = []
    for raw_url in reference_image_urls:
        url = raw_url.strip()
        if not url:
            continue
        content, filename = await read_reference_media(url)
        try:
            validate_reference_image_bytes(content)
        except ValueError as exc:
            raise ModelError(
                f"Gemini reference image is not a decodable image: "
                f"{url[:120]} ({exc})",
                model_name=model_name,
            ) from exc
        suffix = Path(filename or "").suffix.lower()
        mime_type = mimetypes.types_map.get(suffix, "image/png")
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(content).decode("ascii"),
                },
            },
        )
    return parts


class GeminiImageModel(BaseImageModel):
    """Gemini API generateContent image generation (Nano Banana family)."""

    backend_name = "gemini"

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
    def from_config(cls) -> "GeminiImageModel":
        """Read GEMINI_IMAGE_* (legacy IMAGE_*) env / Tools config."""
        return cls(
            model_name=_configured_value(
                "model",
                "GEMINI_IMAGE_MODEL_NAME",
                os.environ.get(
                    "GEMINI_IMAGE_MODEL_NAME",
                    os.environ.get("IMAGE_MODEL_NAME", DEFAULT_MODEL_NAME),
                ),
            ),
            api_key=_configured_value(
                "api_key",
                "GEMINI_IMAGE_API_KEY",
                os.environ.get(
                    "GEMINI_IMAGE_API_KEY",
                    os.environ.get("IMAGE_API_KEY", ""),
                ),
            ),
            base_url=_configured_value(
                ("base_url", "endpoint"),
                "GEMINI_IMAGE_BASE_URL",
                os.environ.get(
                    "GEMINI_IMAGE_BASE_URL",
                    os.environ.get("IMAGE_BASE_URL", DEFAULT_BASE_URL),
                ),
            ),
            timeout=_configured_int(
                "timeout",
                "GEMINI_IMAGE_TIMEOUT",
                int(
                    os.environ.get(
                        "GEMINI_IMAGE_TIMEOUT",
                        os.environ.get("IMAGE_TIMEOUT", "240"),
                    )
                    or 240,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "GEMINI_IMAGE_CONCURRENCY",
                int(
                    os.environ.get(
                        "GEMINI_IMAGE_CONCURRENCY",
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
        # The official REST base URL already carries the API version; only
        # append it when the user saved the bare host.
        if base.endswith("googleapis.com"):
            base = f"{base}/v1beta"
        return f"{base}/models/{self.model_name}:generateContent"

    def _enforce_reference_budget(self, reference_count: int) -> None:
        limit = image_reference_limit(self.model_name)
        if limit is None:
            if reference_count:
                raise ModelError(
                    f"Gemini image model `{self.model_name}` has no "
                    "registered official reference capability; remove the "
                    "reference images or register the model's documented "
                    "limit first",
                    model_name=self.model_name,
                )
            return
        if reference_count > limit:
            raise ModelError(
                f"Gemini image model `{self.model_name}` officially accepts "
                f"at most {limit} input reference images, got "
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
        parts = await build_inline_image_parts(
            clean_reference_urls,
            self.model_name,
        )
        parts.append({"text": prompt})
        image_config: dict = {}
        if aspect_ratio in GEMINI_ASPECT_RATIOS:
            image_config["aspectRatio"] = aspect_ratio
        image_size = _image_size_for(self.model_name)
        if image_size is not None:
            image_config["imageSize"] = image_size
        generation_config: dict = {"responseModalities": ["TEXT", "IMAGE"]}
        if image_config:
            generation_config["imageConfig"] = image_config
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": generation_config,
        }
        logger.info(
            "Gemini image request | model=%s, references=%d, aspect=%s",
            self.model_name,
            len(clean_reference_urls),
            aspect_ratio,
        )
        return await client.post(
            self.generation_url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            json=body,
        )

    async def _decode(self, data: dict | list) -> dict:
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(candidates, list) or not candidates:
            feedback = (
                data.get("promptFeedback") if isinstance(data, dict) else None
            )
            raise ModelError(
                f"No candidates in Gemini response: {feedback or data}",
                model_name=self.model_name,
            )
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = (
            first.get("content")
            if isinstance(first.get("content"), dict)
            else {}
        )
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            blob = part.get("inlineData") or part.get("inline_data")
            if isinstance(blob, dict) and blob.get("data"):
                img_bytes = base64.b64decode(blob["data"])
                local_url = persist_image_bytes(
                    img_bytes,
                    self.model_name,
                    "gemini-inline",
                )
                return {"url": local_url, "source_url": ""}
        finish_reason = first.get("finishReason", "")
        raise ModelError(
            "No image in Gemini response"
            + (f" (finishReason={finish_reason})" if finish_reason else "")
            + f": {str(data)[:400]}",
            model_name=self.model_name,
        )
