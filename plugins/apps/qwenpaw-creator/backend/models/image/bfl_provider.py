# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=ungrouped-imports
"""Black Forest Labs FLUX API image provider (FLUX.2 family).

Endpoint:  POST {IMAGE_BASE_URL}/v1/{model}
Protocol:  https://docs.bfl.ai (FLUX.2 text-to-image / image editing)

The API is asynchronous: the create call returns ``{id, polling_url}``
and the result must be fetched from the returned ``polling_url`` until
``status == "Ready"`` (``result.sample`` is a signed URL valid for only
10 minutes, so it is downloaded immediately). Authentication uses the
``x-key`` header.

Reference images ride in ``input_image`` .. ``input_image_8`` (up to 8
via the API); each value is either a public URL or a base64-encoded
image. Text-to-image and editing share the same endpoint — providing
``input_image*`` switches the request to editing.
"""

import asyncio
import base64
import os

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
    format_http_error_detail,
    image_reference_limit,
)

logger = setup_logger("model.image.bfl")

DEFAULT_BASE_URL = "https://api.bfl.ai"
DEFAULT_MODEL_NAME = "flux-2-pro"

BFL_MAX_REFERENCE_IMAGES = 8

# Aspect ratio -> (width, height). All values are multiples of 32 within
# the documented bounds (>= 64 per side, multi-reference editing output
# capped at 4MP).
BFL_SIZE_MAP = {
    "16:9": (2048, 1152),
    "9:16": (1152, 2048),
    "1:1": (1440, 1440),
    "4:3": (1600, 1216),
    "3:4": (1216, 1600),
    "21:9": (2176, 928),
    "3:2": (1728, 1152),
    "2:3": (1152, 1728),
}

POLL_INTERVAL_SECONDS = 2
_PENDING_STATUSES = frozenset({"Pending", "Reasoning", "Generating"})
_FAILED_STATUSES = frozenset(
    {
        "Error",
        "Failed",
        "Request Moderated",
        "Content Moderated",
        "Task not found",
    },
)


async def build_bfl_input_images(
    reference_image_urls: list[str],
    model_name: str,
) -> list[str]:
    """Resolve references into BFL-acceptable URL / base64 strings."""

    resolved: list[str] = []
    for raw_url in reference_image_urls:
        url = raw_url.strip()
        if not url:
            continue
        if url.startswith(("http://", "https://")):
            resolved.append(url)
            continue
        content, _filename = await read_reference_media(url)
        try:
            validate_reference_image_bytes(content)
        except ValueError as exc:
            raise ModelError(
                f"FLUX reference image is not a decodable image: "
                f"{url[:120]} ({exc})",
                model_name=model_name,
            ) from exc
        resolved.append(base64.b64encode(content).decode("ascii"))
    return resolved


class BFLImageModel(BaseImageModel):
    """BFL FLUX API format: submit to /v1/{model}, poll the polling_url."""

    backend_name = "bfl"

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
    def from_config(cls) -> "BFLImageModel":
        """Read BFL_IMAGE_* (legacy IMAGE_*) env / Tools config."""
        return cls(
            model_name=_configured_value(
                "model",
                "BFL_IMAGE_MODEL_NAME",
                os.environ.get(
                    "BFL_IMAGE_MODEL_NAME",
                    os.environ.get("IMAGE_MODEL_NAME", DEFAULT_MODEL_NAME),
                ),
            ),
            api_key=_configured_value(
                "api_key",
                "BFL_IMAGE_API_KEY",
                os.environ.get(
                    "BFL_IMAGE_API_KEY",
                    os.environ.get("IMAGE_API_KEY", ""),
                ),
            ),
            base_url=_configured_value(
                ("base_url", "endpoint"),
                "BFL_IMAGE_BASE_URL",
                os.environ.get(
                    "BFL_IMAGE_BASE_URL",
                    os.environ.get("IMAGE_BASE_URL", DEFAULT_BASE_URL),
                ),
            ),
            timeout=_configured_int(
                "timeout",
                "BFL_IMAGE_TIMEOUT",
                int(
                    os.environ.get(
                        "BFL_IMAGE_TIMEOUT",
                        os.environ.get("IMAGE_TIMEOUT", "240"),
                    )
                    or 240,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "BFL_IMAGE_CONCURRENCY",
                int(
                    os.environ.get(
                        "BFL_IMAGE_CONCURRENCY",
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
        if base.endswith("/v1"):
            return f"{base}/{self.model_name}"
        return f"{base}/v1/{self.model_name}"

    def _enforce_reference_budget(self, reference_count: int) -> None:
        limit = image_reference_limit(self.model_name)
        if limit is None:
            if reference_count:
                raise ModelError(
                    f"FLUX image model `{self.model_name}` has no registered "
                    "official reference capability; remove the reference "
                    "images or register the model's documented limit first",
                    model_name=self.model_name,
                )
            return
        if reference_count > limit:
            raise ModelError(
                f"FLUX image model `{self.model_name}` officially accepts "
                f"at most {limit} input reference images via the API, got "
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
        width, height = BFL_SIZE_MAP.get(aspect_ratio, (1440, 1440))
        body: dict = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "output_format": "png",
        }
        if clean_reference_urls:
            resolved = await build_bfl_input_images(
                clean_reference_urls,
                self.model_name,
            )
            for index, value in enumerate(resolved, start=1):
                field = "input_image" if index == 1 else f"input_image_{index}"
                body[field] = value
        logger.info(
            "BFL image request | model=%s, references=%d, size=%dx%d",
            self.model_name,
            len(clean_reference_urls),
            width,
            height,
        )
        submit = await client.post(
            self.generation_url,
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
                "x-key": self.api_key,
            },
            json=body,
        )
        if submit.status_code != 200:
            # Hand HTTP errors (incl. 429) to the base-class envelope.
            return submit
        payload = submit.json()
        polling_url = (
            str(payload.get("polling_url") or "")
            if isinstance(payload, dict)
            else ""
        )
        if not polling_url:
            raise ModelError(
                f"BFL submit returned no polling_url: {str(payload)[:300]}",
                model_name=self.model_name,
            )
        return await self._poll(client, polling_url)

    async def _poll(
        self,
        client: httpx.AsyncClient,
        polling_url: str,
    ) -> httpx.Response:
        """Poll the returned polling_url until the task is terminal."""

        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            try:
                response = await client.get(
                    polling_url,
                    headers={
                        "accept": "application/json",
                        "x-key": self.api_key,
                    },
                    timeout=30,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning(
                    "BFL poll transport error, retrying: %s",
                    type(exc).__name__,
                )
                response = None
            if response is not None and response.status_code == 200:
                payload = response.json()
                status = (
                    str(payload.get("status") or "")
                    if isinstance(payload, dict)
                    else ""
                )
                if status == "Ready":
                    return response
                if status in _FAILED_STATUSES:
                    raise ModelError(
                        f"BFL generation ended {status}: "
                        f"{str(payload)[:400]}",
                        model_name=self.model_name,
                    )
                if status not in _PENDING_STATUSES:
                    logger.warning("BFL poll unknown status: %s", status)
            elif response is not None and (
                response.status_code == 429 or response.status_code >= 500
            ):
                logger.warning(
                    "BFL poll got %s, retrying",
                    response.status_code,
                )
            elif response is not None:
                raise ModelError(
                    f"BFL poll failed with status {response.status_code}: "
                    f"{format_http_error_detail(response)[:300]}",
                    model_name=self.model_name,
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise ModelError(
                    f"BFL generation timed out after {self.timeout}s",
                    model_name=self.model_name,
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _decode(self, data: dict | list) -> dict:
        result = data.get("result") if isinstance(data, dict) else None
        sample = (
            str(result.get("sample") or "") if isinstance(result, dict) else ""
        )
        if not sample:
            raise ModelError(
                f"No image in BFL response: {str(data)[:400]}",
                model_name=self.model_name,
            )
        # Signed URLs expire after 10 minutes; download immediately.
        local_url = await download_remote_image(sample, self.model_name)
        return {"url": local_url, "source_url": ""}
