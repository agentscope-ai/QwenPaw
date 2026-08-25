# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=ungrouped-imports
"""OpenAI Images API image provider (routify / gpt-image-2).

Endpoint:  POST {IMAGE_BASE_URL}[/v1]/images/generations[/edits]
           (the /v1 segment is added only when the base URL lacks it)
Protocol:  https://developers.openai.com/api/reference/resources/images/methods/generate/

When ``background_model`` is configured (a Responses-API host model such
as gpt-5.x), generation switches to background mode: submit
``POST {base}[/v1]/responses`` with ``background: true`` and the
``image_generation`` tool, then poll ``GET {base}[/v1]/responses/{id}``
until terminal — no HTTP exchange ever spans a render. The classic
Images API stays the default because gpt-image-2 renders in ~40s and has
no async mode of its own; both transports share the configured base URL.
"""

import asyncio
import base64
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from models import config as model_config
from models.media_transport import read_reference_media
from models.provider_tasks import note_provider_task
from utils.exceptions import ModelError
from utils.logger import setup_logger
from models.image.base import (
    BaseImageModel,
    _configured_int,
    _configured_value,
    download_remote_image,
    persist_image_bytes,
)

logger = setup_logger("model.image.openai")


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

# Background (Responses API) poll cadence: cheap GETs against the response
# object. The overall deadline stays the provider timeout.
RESPONSES_POLL_INTERVAL_SECONDS = 5
RESPONSES_POLL_REQUEST_TIMEOUT = 30
RESPONSES_SUBMIT_TIMEOUT = 60

_RESPONSES_PENDING = frozenset({"queued", "in_progress"})


async def build_reference_image_files(
    reference_image_urls: list[str],
) -> list[tuple[str, tuple[str, bytes, str]]]:
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    total_bytes = 0
    unique_urls = [
        url
        for url in dict.fromkeys(
            raw.strip() for raw in reference_image_urls[:16]
        )
        if url
    ]
    # The Images edits API takes one part named ``image``; multiple
    # references must be sent as ``image[]``. Some gateway deployments used
    # to tolerate a repeated ``image`` field, but enforcement now rejects
    # it with 400 "Duplicate parameter: 'image'".
    field_name = "image" if len(unique_urls) <= 1 else "image[]"
    for index, raw_url in enumerate(
        unique_urls,
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
        files.append((field_name, (safe_filename, content, mime_type)))
    return files


async def build_reference_image_data_urls(
    reference_image_urls: list[str],
) -> list[str]:
    """Read references and encode them as data URLs for the Responses API.

    Background mode sends references as ``input_image`` content blocks;
    data URLs keep local/generated media self-contained without a separate
    upload step. The aggregate cap mirrors the multipart path.
    """

    data_urls: list[str] = []
    total_bytes = 0
    unique_urls = [
        url
        for url in dict.fromkeys(
            raw.strip() for raw in reference_image_urls[:16]
        )
        if url
    ]
    for raw_url in unique_urls:
        content, filename = await read_reference_media(raw_url)
        total_bytes += len(content)
        if total_bytes > REFERENCE_IMAGES_TOTAL_MAX_BYTES:
            raise ModelError(
                "reference images exceed "
                f"{REFERENCE_IMAGES_TOTAL_MAX_BYTES} bytes in total",
                model_name=DEFAULT_MODEL_NAME,
            )
        suffix = Path(filename).suffix.lower()
        if not suffix:
            suffix = Path(urlparse(raw_url).path).suffix.lower()
        mime_type = mimetypes.types_map.get(suffix, "image/png")
        encoded = base64.b64encode(content).decode("ascii")
        data_urls.append(f"data:{mime_type};base64,{encoded}")
    return data_urls


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
        background_model: str = "",
    ) -> None:
        super().__init__(model_name, api_key, timeout, concurrency)
        self.base_url = base_url
        self.quality = quality
        # Responses-API host model for background mode; empty keeps the
        # classic synchronous Images API.
        self.background_model = background_model.strip()

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
                        os.environ.get("IMAGE_TIMEOUT", "240"),
                    )
                    or 240,
                ),
            ),
            concurrency=_configured_int(
                "concurrency",
                "OPENAI_IMAGE_CONCURRENCY",
                int(
                    os.environ.get(
                        "OPENAI_IMAGE_CONCURRENCY",
                        os.environ.get("IMAGE_CONCURRENCY", "0"),
                    )
                    or 0,
                )
                # Default follows the scheduler's dispatch cap so the
                # provider semaphore never silently serializes renders.
                or model_config.get_media_parallelism(),
            ),
            background_model=_configured_value(
                "background_model",
                "OPENAI_IMAGE_BACKGROUND_MODEL",
                os.environ.get(
                    "OPENAI_IMAGE_BACKGROUND_MODEL",
                    os.environ.get("IMAGE_BACKGROUND_MODEL", ""),
                ),
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

    @property
    def responses_url(self) -> str:
        """Responses API root on the same configured base URL."""
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/responses"
        return f"{base}/v1/responses"

    async def _request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
        mode: str = "generate",
    ) -> httpx.Response:
        # Only ``generate`` reaches a provider without edit/translate support;
        # the envelope rejects the other modes before this point.
        del mode
        if self.background_model:
            return await self._background_request(
                client,
                prompt,
                aspect_ratio,
                clean_reference_urls,
            )
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

    async def _background_request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
    ) -> httpx.Response:
        """Responses-API background transport: submit, poll, return terminal.

        Image generation in the Responses API is a tool of a host model,
        so ``background_model`` drives the request while ``model_name``
        (gpt-image-2 etc.) stays the billed image generator configured on
        the tool. The returned response carries the terminal payload, so
        the base-class ``resp.json()`` → ``_decode`` contract holds.
        """

        content: list[dict] = [{"type": "input_text", "text": prompt}]
        for data_url in await build_reference_image_data_urls(
            clean_reference_urls,
        ):
            content.append(
                {"type": "input_image", "image_url": data_url},
            )
        body = {
            "model": self.background_model,
            "input": [{"role": "user", "content": content}],
            "tools": [
                {
                    "type": "image_generation",
                    "model": self.model_name,
                    "size": OPENAI_SIZE_MAP.get(aspect_ratio, "1536x1024"),
                    "quality": self.quality,
                    "output_format": "png",
                },
            ],
            "tool_choice": "required",
            "background": True,
        }
        submit = await client.post(
            self.responses_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json=body,
            timeout=RESPONSES_SUBMIT_TIMEOUT,
        )
        if submit.status_code != 200:
            # 429 and HTTP errors go to the base-class envelope untouched.
            return submit
        payload = submit.json()
        response_id = str(payload.get("id") or "")
        status = str(payload.get("status") or "").lower()
        if not response_id or status not in _RESPONSES_PENDING:
            # Terminal right away (tiny render or proxy without background
            # support): decode this payload directly.
            return submit
        # Billed on acceptance: record the id in the paying Task's durable
        # ledger so an interrupted poll stays retrievable. The append is a
        # small durable write; keep it off the event loop.
        await asyncio.to_thread(
            note_provider_task,
            provider_task_id=response_id,
            model=self.model_name,
            kind="image_generation",
        )
        return await self._poll_response(client, response_id)

    async def _poll_response(
        self,
        client: httpx.AsyncClient,
        response_id: str,
    ) -> httpx.Response:
        """Poll the response object until terminal or the render deadline."""

        deadline = asyncio.get_running_loop().time() + self.timeout
        poll_url = f"{self.responses_url}/{response_id}"
        logger.info(
            "Image background response submitted | model=%s, id=%s",
            self.model_name,
            response_id,
        )
        while True:
            try:
                response = await client.get(
                    poll_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=RESPONSES_POLL_REQUEST_TIMEOUT,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # The render continues server-side; a flaky poll must not
                # fail the task. The deadline below still bounds the wait.
                logger.warning(
                    "Image background poll transport error, retrying | "
                    "id=%s: %s",
                    response_id,
                    type(exc).__name__,
                )
                response = None
            if response is not None and response.status_code == 200:
                payload = response.json()
                status = str(payload.get("status") or "").lower()
                if status and status not in _RESPONSES_PENDING:
                    if status == "completed":
                        return response
                    error = payload.get("error")
                    detail = ""
                    if isinstance(error, dict):
                        detail = str(
                            error.get("message") or error.get("code") or "",
                        )
                    raise ModelError(
                        f"Image background response {response_id} ended "
                        f"{status}" + (f": {detail}" if detail else ""),
                        model_name=self.model_name,
                    )
            elif response is not None and (
                response.status_code == 429 or response.status_code >= 500
            ):
                # Transient poll hiccup: the render continues server-side,
                # so keep polling instead of failing the task.
                logger.warning(
                    "Image background poll got %s, retrying | id=%s",
                    response.status_code,
                    response_id,
                )
            elif response is not None:
                response.raise_for_status()
            if asyncio.get_running_loop().time() >= deadline:
                raise ModelError(
                    f"Image generation timed out after {self.timeout}s "
                    f"(background response {response_id} still running "
                    "server-side)",
                    model_name=self.model_name,
                )
            await asyncio.sleep(RESPONSES_POLL_INTERVAL_SECONDS)

    def _persist_base64_image(self, encoded: str) -> str:
        """Decode and durably stage one image; runs in a worker thread.

        Both the base64 decode of a full image and the durable write
        (fsync + rename + directory fsync) are heavyweight, so callers
        offload this via ``asyncio.to_thread``; contextvars carry the Task
        scope into the worker thread.
        """

        return persist_image_bytes(
            base64.b64decode(encoded),
            self.model_name,
            "base64→file",
        )

    async def _decode(self, data: dict | list) -> dict:
        # Responses-API payloads carry the image inside an
        # image_generation_call output block as base64.
        if isinstance(data, dict) and isinstance(data.get("output"), list):
            for block in data["output"]:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "image_generation_call"
                    and block.get("result")
                ):
                    local_url = await asyncio.to_thread(
                        self._persist_base64_image,
                        str(block["result"]),
                    )
                    return {"url": local_url, "source_url": ""}
            raise ModelError(
                f"No image_generation_call result in response: {data}",
                model_name=self.model_name,
            )
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
            local_url = await asyncio.to_thread(
                self._persist_base64_image,
                str(item["b64_json"]),
            )
            return {"url": local_url, "source_url": ""}
        if item.get("url"):
            original_url = str(item["url"])
            local_url = await download_remote_image(
                original_url,
                self.model_name,
            )
            return {"url": local_url, "source_url": ""}
        raise ModelError(
            f"No b64_json or url in response item: {item}",
            model_name=self.model_name,
        )
