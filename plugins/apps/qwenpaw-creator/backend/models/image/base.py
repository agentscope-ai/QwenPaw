# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,raise-missing-from
"""Abstract base and shared helpers for image generation providers.

A small provider abstraction so multiple image backends share the same API:

    BaseImageModel.generate(prompt, aspect_ratio, reference_image_urls) -> str

The base class owns the common envelope (api-key check, concurrency slot,
retry/backoff, 429 handling, HTTP error formatting, timeout/exception
wrapping). Each provider only implements:

    _request(client, prompt, aspect_ratio, clean_reference_urls) -> Response
    _decode(data) -> str   (persist the image and return a /generated/ URL)

Adding another backend later means writing one new subclass — no changes to
callers or the retry shell.
"""

import asyncio
import json
import os
from abc import ABC, abstractmethod

import httpx

from models import config as model_config
from models.concurrency import model_slot
from services.runtime_files.atomic_store import atomic_replace_bytes
from utils.logger import setup_logger
from utils.exceptions import ModelError
from utils.paths import media_url_for, unique_task_work_path
from utils.remote_download import download_remote_file

logger = setup_logger("model.image")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 10  # seconds
MIN_IMAGE_BYTES = int(os.environ.get("IMAGE_MIN_BYTES", "10000"))


def format_http_error_detail(response: httpx.Response) -> str:
    body_text = response.text.strip()
    if body_text:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = (
                        error.get("message")
                        or error.get("detail")
                        or error.get("code")
                    )
                    if message:
                        return str(message)
                if isinstance(error, str):
                    return error
                detail = payload.get("detail") or payload.get("message")
                if detail:
                    return (
                        detail
                        if isinstance(detail, str)
                        else json.dumps(detail, ensure_ascii=False)
                    )
        except ValueError:
            pass
        return body_text[:500]
    reason = response.reason_phrase or "empty response body"
    return f"{reason} ({response.request.method} {response.request.url})"


def persist_image_bytes(img_bytes: bytes, model_name: str, source: str) -> str:
    """Validate and atomically stage provider bytes in current Task scratch."""
    if len(img_bytes) < MIN_IMAGE_BYTES:
        raise ModelError(
            f"Image generation returned an unexpectedly small image ({len(img_bytes)} bytes)",
            model_name=model_name,
        )
    image_path = unique_task_work_path("images", ".png", prefix="img_")
    atomic_replace_bytes(image_path, img_bytes)
    result_url = media_url_for(image_path)
    logger.info(
        f"Image saved ({source}) | path={image_path}, size={len(img_bytes)} bytes",
    )
    return result_url


async def download_remote_image(remote_url: str, model_name: str) -> str:
    """Download a remote image URL and persist it in current Task scratch."""
    logger.info(f"Image generated (url) | url={remote_url[:80]}")
    try:
        async with httpx.AsyncClient(
            timeout=60,
            follow_redirects=True,
        ) as client:
            resp = await client.get(remote_url)
            resp.raise_for_status()
            img_bytes = resp.content
    except httpx.TransportError as exc:
        # Model Studio returns a short-lived OSS URL that must be downloaded
        # promptly.  Some local/network stacks cannot establish the OSS route
        # through httpx even though curl can.  Reuse the project's bounded,
        # redirect-following curl transport as a network fallback; HTTP status
        # failures remain authoritative and are not retried through a second
        # client.
        logger.warning(
            "Image URL httpx transport failed; retrying with bounded curl: %s",
            type(exc).__name__,
        )
        temporary = unique_task_work_path(
            "images",
            ".remote",
            prefix="download_",
        )
        try:
            await asyncio.to_thread(
                download_remote_file,
                remote_url,
                str(temporary),
            )
            img_bytes = await asyncio.to_thread(temporary.read_bytes)
        finally:
            temporary.unlink(missing_ok=True)
    return persist_image_bytes(img_bytes, model_name, "url→file")


def _configured_value(
    fields: str | tuple[str, ...],
    env_name: str,
    default: str = "",
) -> str:
    """Read a config value: request-scoped Tools config, then the persisted
    ``model_config.json`` (so background workers that run outside any HTTP
    request still see UI-saved keys), then env, then default.

    Thin wrapper over ``model_config``'s central resolver so the image backend
    shares the same lookup precedence as text/vlm/video instead of re-implement
    it (which previously dropped the persisted-config fallback).
    """
    return model_config._configured_value(
        model_config.CREATOR_IMAGE_CONFIG_TOOL,
        fields,
        env_name,
        default,
    )


def _configured_int(
    fields: str | tuple[str, ...],
    env_name: str,
    default: int,
) -> int:
    return model_config._configured_int(
        model_config.CREATOR_IMAGE_CONFIG_TOOL,
        fields,
        env_name,
        default,
    )


class BaseImageModel(ABC):
    """Common image-generation envelope shared by every backend.

    Subclasses implement ``_request`` (build & send the provider-specific
    HTTP call) and ``_decode`` (parse the provider response into a saved
    image URL). Everything else — retries, rate-limit backoff, concurrency
    slot, error wrapping — is handled here.
    """

    backend_name: str = "base"

    def __init__(
        self,
        model_name: str,
        api_key: str,
        timeout: int,
        concurrency: int = 1,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.timeout = timeout
        self.concurrency = max(1, concurrency)

    @classmethod
    @abstractmethod
    def from_config(cls) -> "BaseImageModel":
        """Construct an instance from the provider's own environment/Tools config."""

    @property
    @abstractmethod
    def generation_url(self) -> str:
        """Return the full URL for a text-to-image generation request."""

    async def generate(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        reference_image_urls: list[str] | None = None,
    ) -> str:
        """Generate an image, persist it, and return a /generated/... URL."""
        if not self.api_key:
            raise ModelError(
                "creator_image_model.api_key or IMAGE_API_KEY is required",
                model_name=self.model_name,
            )

        clean_reference_urls = [
            url.strip()
            for url in (reference_image_urls or [])
            if url and url.strip()
        ]

        logger.info(
            f"Generating image | model={self.model_name}, backend={self.backend_name}, "
            f"prompt_length={len(prompt)}, references={len(clean_reference_urls)}",
        )

        try:
            data = None
            async with model_slot("image"):
                for attempt in range(MAX_RETRIES):
                    async with httpx.AsyncClient(
                        timeout=self.timeout,
                    ) as client:
                        resp = await self._request(
                            client,
                            prompt,
                            aspect_ratio,
                            clean_reference_urls,
                        )
                        if resp.status_code == 429:
                            wait = RETRY_BACKOFF_BASE * (attempt + 1)
                            logger.warning(
                                f"Image generation rate limited (429), retrying in {wait}s "
                                f"(attempt {attempt+1}/{MAX_RETRIES})",
                            )
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                        data = resp.json()
                        try:
                            return await self._decode(data)
                        except ModelError as exc:
                            if attempt == MAX_RETRIES - 1:
                                raise
                            wait = RETRY_BACKOFF_BASE * (attempt + 1)
                            logger.warning(
                                f"Image response validation failed, retrying in {wait}s: {exc}",
                            )
                            await asyncio.sleep(wait)
                            continue
            if data is None:
                raise ModelError(
                    "Image generation failed: rate limited after all retries",
                    model_name=self.model_name,
                )
            raise ModelError(
                "Image generation failed after all retries",
                model_name=self.model_name,
            )

        except ModelError:
            raise
        except httpx.TimeoutException as e:
            logger.error(
                f"Image generation timed out after {self.timeout}s: {type(e).__name__}",
            )
            raise ModelError(
                f"Image generation timed out after {self.timeout}s",
                model_name=self.model_name,
            )
        except httpx.HTTPStatusError as e:
            detail = format_http_error_detail(e.response)
            logger.error(
                f"Image generation HTTP error: {e.response.status_code} - {detail[:500]}",
            )
            raise ModelError(
                f"Image generation failed with status {e.response.status_code}: {detail[:500]}",
                model_name=self.model_name,
            )
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            raise ModelError(
                f"Image generation failed: {str(e)}",
                model_name=self.model_name,
            )

    @abstractmethod
    async def _request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
    ) -> httpx.Response:
        """Build and send the provider-specific generation request."""

    @abstractmethod
    async def _decode(self, data: dict | list) -> str:
        """Parse the provider response, persist the image, return its URL."""
