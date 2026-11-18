# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=ungrouped-imports
"""MiniMax image-generation provider (image-01 / image-01-live).

Endpoint:  POST {base}/v1/image_generation   (synchronous)
Protocol:  https://platform.minimaxi.com/docs/api-reference/image-generation-t2i

The endpoint is a single synchronous JSON call: it authenticates with
``Authorization: Bearer <API key>`` and returns the finished image inline, so
there is no task id or polling loop (unlike MiniMax's video API).

Request shape (verified against the official OpenAPI):

- ``model`` (``image-01`` / ``image-01-live``) and ``prompt`` (<=1500 chars)
  are required.
- ``aspect_ratio`` is an 8-value enum; ``21:9`` only applies to ``image-01``.
  An explicit ``width``/``height`` pair is overridden by ``aspect_ratio`` when
  both are sent, so Creator only ever sends ``aspect_ratio``.
- ``subject_reference`` carries at most one character image. The endpoint takes
  either a public URL or a Base64 **data URL**
  (``data:image/jpeg;base64,...``), so a local reference is inlined through
  ``reference_media_data_url`` the way the Ark provider does. BFL's bare-base64
  form does not apply here: MiniMax reads neither a URL nor a media type out of
  it, so the value is rejected before any image is generated.

A successful body still answers HTTP 200, so ``base_resp.status_code`` (0 means
success) is the authoritative status and is checked before the image is read.
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
from models.minimax_errors import minimax_base_resp_error
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

logger = setup_logger("model.image.minimax")

DEFAULT_BASE_URL = "https://api.minimax.io"
DEFAULT_MODEL_NAME = "image-01"

# The documented ceiling for one reference image. The shared data-URL builder
# only guards Seedance's larger limit, so the provider states its own; base64
# also inflates the body by a third, which makes the ceiling worth enforcing
# locally instead of taking a bare parameter error from the endpoint.
MINIMAX_REFERENCE_IMAGE_MAX_BYTES = 10 * 1024 * 1024

# Creator aspect ratio -> the documented enum. Creator only emits ratios that
# MiniMax already lists, so this is a pass-through map kept explicit to reject a
# stray value rather than sending an out-of-enum string.
MINIMAX_ASPECT_RATIOS = frozenset(
    {
        "1:1",
        "16:9",
        "4:3",
        "3:2",
        "2:3",
        "3:4",
        "9:16",
        "21:9",
    },
)


class MiniMaxImageModel(BaseImageModel):
    """MiniMax synchronous image_generation endpoint."""

    backend_name = "minimax"

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
    def from_config(cls) -> "MiniMaxImageModel":
        """Read MINIMAX_IMAGE_* (legacy IMAGE_*) env / Tools config."""
        return cls(
            model_name=_configured_value(
                "model",
                "MINIMAX_IMAGE_MODEL_NAME",
                os.environ.get(
                    "MINIMAX_IMAGE_MODEL_NAME",
                    os.environ.get("IMAGE_MODEL_NAME", DEFAULT_MODEL_NAME),
                ),
            ),
            api_key=_configured_value(
                "api_key",
                "MINIMAX_IMAGE_API_KEY",
                os.environ.get(
                    "MINIMAX_IMAGE_API_KEY",
                    os.environ.get("IMAGE_API_KEY", ""),
                ),
            ),
            base_url=_configured_value(
                ("base_url", "endpoint"),
                "MINIMAX_IMAGE_BASE_URL",
                os.environ.get(
                    "MINIMAX_IMAGE_BASE_URL",
                    os.environ.get("IMAGE_BASE_URL", DEFAULT_BASE_URL),
                ),
            ),
            timeout=_configured_int(
                "timeout",
                "MINIMAX_IMAGE_TIMEOUT",
                int(
                    os.environ.get(
                        "MINIMAX_IMAGE_TIMEOUT",
                        os.environ.get("IMAGE_TIMEOUT", "240"),
                    )
                    or 240,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "MINIMAX_IMAGE_CONCURRENCY",
                int(
                    os.environ.get(
                        "MINIMAX_IMAGE_CONCURRENCY",
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
        return f"{base}/v1/image_generation"

    def _enforce_reference_budget(self, reference_count: int) -> None:
        limit = image_reference_limit(self.model_name)
        if limit is None:
            if reference_count:
                raise ModelError(
                    f"MiniMax model `{self.model_name}` has no registered "
                    "official reference capability; remove the reference "
                    "images or register the model's documented limit first",
                    model_name=self.model_name,
                )
            return
        if reference_count > limit:
            raise ModelError(
                f"MiniMax model `{self.model_name}` officially accepts at "
                f"most {limit} input reference images, got {reference_count}",
                model_name=self.model_name,
            )

    async def _resolve_reference(self, url: str) -> str:
        """Return a ``subject_reference.image_file`` value MiniMax can read.

        That field accepts a public URL or a Base64 data URL, not bare base64:
        with no ``data:<mime>;base64,`` prefix the endpoint can treat the value
        as neither, and the request dies on a parameter error before generating.
        """
        if url.startswith(("http://", "https://")):
            return url
        content, filename = await read_reference_media(url)
        if len(content) >= MINIMAX_REFERENCE_IMAGE_MAX_BYTES:
            raise ModelError(
                "MiniMax reference images must be under 10MB; downscale the "
                "media or provide a public HTTPS URL",
                model_name=self.model_name,
            )
        try:
            validate_reference_image_bytes(content)
        except ValueError as exc:
            raise ModelError(
                f"MiniMax reference image is not a decodable image: "
                f"{url[:120]} ({exc})",
                model_name=self.model_name,
            ) from exc
        return reference_media_data_url(content, filename)

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
            "aspect_ratio": (
                aspect_ratio
                if aspect_ratio in MINIMAX_ASPECT_RATIOS
                else "1:1"
            ),
            "response_format": "url",
            "n": 1,
        }
        if clean_reference_urls:
            body["subject_reference"] = [
                {
                    "type": "character",
                    "image_file": await self._resolve_reference(
                        clean_reference_urls[0],
                    ),
                },
            ]
        logger.info(
            "MiniMax image request | model=%s, references=%d, ratio=%s",
            self.model_name,
            len(clean_reference_urls),
            body["aspect_ratio"],
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
        if not isinstance(data, dict):
            raise ModelError(
                f"MiniMax returned an unexpected response shape: "
                f"{str(data)[:400]}",
                model_name=self.model_name,
            )
        # HTTP 200 is not success here; base_resp carries the real status.
        base_resp_error = minimax_base_resp_error(data)
        if base_resp_error is not None:
            raise ModelError(base_resp_error, model_name=self.model_name)
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise ModelError(
                f"No image in MiniMax response: {str(data)[:400]}",
                model_name=self.model_name,
            )
        image_urls = payload.get("image_urls")
        if isinstance(image_urls, list) and image_urls:
            # Signed URLs expire after 24h; download and persist immediately.
            local_url = await download_remote_image(
                str(image_urls[0]),
                self.model_name,
            )
            return {"url": local_url, "source_url": ""}
        image_base64 = payload.get("image_base64")
        if isinstance(image_base64, list) and image_base64:
            local_url = persist_image_bytes(
                base64.b64decode(str(image_base64[0])),
                self.model_name,
                "minimax base64",
            )
            return {"url": local_url, "source_url": ""}
        raise ModelError(
            f"No image in MiniMax response: {str(data)[:400]}",
            model_name=self.model_name,
        )
