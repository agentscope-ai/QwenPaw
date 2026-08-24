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
from dataclasses import dataclass
import json
import os
import re
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

# Tool-level image operation modes. ``generate`` keeps the historical
# behaviour (text-to-image, optionally guided by references); ``edit`` and
# ``translate`` are explicit qwen-image capabilities only the DashScope
# provider implements.
IMAGE_GENERATION_MODES = ("generate", "edit", "translate")
EDIT_MIN_REFERENCE_IMAGES = 1


@dataclass(frozen=True, slots=True)
class ImageReferenceCapability:
    """Official reference-image contract for one model family."""

    family: str
    max_reference_images: int
    documentation_url: str


_QWEN_EDIT_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/qwen-image-edit-guide"
)
_QWEN_MODEL_DOCUMENTATION = (
    "https://help.aliyun.com/zh/model-studio/image-model"
)
_OPENAI_IMAGE_DOCUMENTATION = (
    "https://github.com/openai/openai-python/blob/main/"
    "src/openai/types/image_edit_params.py"
)
_GEMINI_IMAGE_DOCUMENTATION = (
    "https://ai.google.dev/gemini-api/docs/image-generation"
)
_ARK_SEEDREAM_DOCUMENTATION = "https://www.volcengine.com/docs/82379/1541523"
_BFL_FLUX_DOCUMENTATION = "https://docs.bfl.ai"
_IDEOGRAM_DOCUMENTATION = (
    "https://developer.ideogram.ai/api-reference/api-reference/generate-v3"
)

# These are input-reference limits, not the number of generated outputs.
# Keep the table closed over model families documented by the two providers
# this module actually implements. An unknown compatible-gateway alias is not
# assigned a guessed generic value: reference use then fails before billing
# with a capability-registration error.
_REFERENCE_CAPABILITIES = (
    (
        re.compile(
            r"^qwen-image-(?:3\.0|2\.0)(?:-pro)?"
            r"(?:-20\d{2}-\d{2}-\d{2})?$",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "qwen-image-2.x/3.x",
            3,
            _QWEN_EDIT_DOCUMENTATION,
        ),
    ),
    (
        re.compile(
            r"^qwen-image-edit(?:-plus|-max)?" + r"(?:-20\d{2}-\d{2}-\d{2})?$",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "qwen-image-edit",
            3,
            _QWEN_EDIT_DOCUMENTATION,
        ),
    ),
    (
        re.compile(r"^qwen-mt-image$", re.IGNORECASE),
        ImageReferenceCapability(
            "qwen-mt-image",
            1,
            "https://help.aliyun.com/zh/model-studio/qwen-mt-image-api",
        ),
    ),
    (
        re.compile(
            r"^(?:qwen-image(?:-plus|-max)?)(?:$|-20\d{2}-\d{2}-\d{2}$)",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "qwen-image-generation-only",
            0,
            _QWEN_MODEL_DOCUMENTATION,
        ),
    ),
    (
        re.compile(
            r"^(?:gpt-image-2|gpt-image-1\.5|gpt-image-1|"
            r"gpt-image-1-mini|chatgpt-image-latest)(?:$|-20\d{2}-\d{2}-\d{2}$)",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "openai-gpt-image",
            16,
            _OPENAI_IMAGE_DOCUMENTATION,
        ),
    ),
    (
        re.compile(r"^dall-e-2$", re.IGNORECASE),
        ImageReferenceCapability(
            "openai-dall-e-2",
            1,
            _OPENAI_IMAGE_DOCUMENTATION,
        ),
    ),
    (
        re.compile(r"^dall-e-3$", re.IGNORECASE),
        ImageReferenceCapability(
            "openai-dall-e-3",
            0,
            _OPENAI_IMAGE_DOCUMENTATION,
        ),
    ),
    # Google Gemini image generation (Nano Banana family). The official
    # guide caps the total reference input at 14 images for the Gemini 3
    # generation (3 Pro: 6 objects + 5 characters + 3 style; 3.1 Flash:
    # 10 objects + 4 characters), while gemini-2.5-flash-image "works
    # best with up to 3 images as input".
    (
        re.compile(
            r"^gemini-3-pro-image(?:-preview)?$",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "gemini-3-pro-image",
            14,
            _GEMINI_IMAGE_DOCUMENTATION,
        ),
    ),
    (
        re.compile(
            r"^gemini-3\.1-flash(?:-lite)?-image(?:-preview)?$",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "gemini-3.1-flash-image",
            14,
            _GEMINI_IMAGE_DOCUMENTATION,
        ),
    ),
    (
        re.compile(r"^gemini-2\.5-flash-image(?:-preview)?$", re.IGNORECASE),
        ImageReferenceCapability(
            "gemini-2.5-flash-image",
            3,
            _GEMINI_IMAGE_DOCUMENTATION,
        ),
    ),
    # Volcengine Ark Doubao-Seedream: 5.0 pro accepts 1-10 reference
    # images, 5.0 lite / 4.5 / 4.0 accept 1-14 (official "model
    # capability" table on the images/generations API reference).
    (
        re.compile(
            r"^doubao-seedream-5[.-]0-pro(?:-\d{6})?$",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "doubao-seedream-5.0-pro",
            10,
            _ARK_SEEDREAM_DOCUMENTATION,
        ),
    ),
    (
        re.compile(
            r"^doubao-seedream-(?:5[.-]0-lite|4[.-]5|4[.-]0)(?:-\d{6})?$",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "doubao-seedream-5.0-lite/4.5/4.0",
            14,
            _ARK_SEEDREAM_DOCUMENTATION,
        ),
    ),
    # BFL FLUX.2 family: up to 8 reference images via the API
    # (input_image .. input_image_8).
    (
        re.compile(
            r"^flux-2-(?:pro|max|flex|pro-preview|klein-9b|klein-4b)$",
            re.IGNORECASE,
        ),
        ImageReferenceCapability(
            "bfl-flux-2",
            8,
            _BFL_FLUX_DOCUMENTATION,
        ),
    ),
    # Ideogram: the v3 generate endpoint accepts exactly 1
    # character_reference_images file; the v4 generate endpoint documents
    # no reference-image field at all (text-to-image only).
    (
        re.compile(r"^ideogram-v3$", re.IGNORECASE),
        ImageReferenceCapability(
            "ideogram-v3",
            1,
            _IDEOGRAM_DOCUMENTATION,
        ),
    ),
    (
        re.compile(r"^ideogram-v4$", re.IGNORECASE),
        ImageReferenceCapability(
            "ideogram-v4",
            0,
            "https://developer.ideogram.ai/api-reference/"
            "api-reference/generate-v4",
        ),
    ),
)


def image_reference_capability(
    model_name: str,
) -> ImageReferenceCapability | None:
    """Resolve an official input-reference contract without guessing."""

    normalized = model_name.strip()
    if not normalized:
        return None
    for pattern, capability in _REFERENCE_CAPABILITIES:
        if pattern.fullmatch(normalized):
            return capability
    return None


def image_reference_limit(model_name: str) -> int | None:
    """Return an official limit, or ``None`` for an unknown model alias."""

    capability = image_reference_capability(model_name)
    return capability.max_reference_images if capability is not None else None


def image_model_prompt_guidance(model_name: str) -> str:
    """Model-specific reference-count rules injected into specialist prompts.

    The static prompts stay model-agnostic; the reference budget depends on
    the configured image model (observed live: qwen-image-3.0 rejected a
    storyboard call carrying 4 reference images with HTTP 400), so the rule
    is rendered from the runtime-resolved model name.
    """

    normalized = model_name.strip() or "未配置"
    capability = image_reference_capability(normalized)
    if capability is None:
        return (
            f"当前图片模型 `{normalized}` 没有匹配到 Creator 内置的官方"
            "能力表。不要传入参考图；如果该名称是兼容网关别名，"
            "需先为它登记官方对应模型的能力，不可使用通用数值猜测。"
        )
    if capability.max_reference_images == 0:
        return f"当前图片模型 `{normalized}` 的官方能力为仅文生图，" "不支持输入参考图。"
    if capability.family.startswith("qwen-image"):
        return (
            f"当前图片生成模型是 `{normalized}`，单次调用最多接受 "
            f"{capability.max_reference_images} 张参考图（0 张=文生图，"
            f"1–{capability.max_reference_images} 张=图生图），超出会被上游以 "
            "400 拒绝；每次调用所传递的参考版本 ID 总数必须不超过 "
            f"{capability.max_reference_images}，超出预算时只保留最关键的参考"
            "（storyboard、角色/场景锚点优先）。"
        )
    return (
        f"当前图片生成模型是 `{normalized}`，官方文档限制单次最多 "
        f"{capability.max_reference_images} 张输入参考图。"
    )


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
        # through httpx even though curl can.  Fall back to the shared
        # download boundary, which retries through the bounded, SSRF-validated
        # curl transport when its own httpx attempt also fails; HTTP status
        # failures remain authoritative and are not retried through a second
        # client.
        logger.warning(
            "Image URL httpx transport failed; retrying with fallback "
            "transport (httpx sync, then bounded curl): %s",
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
    # The durable write (full image + fsync + rename + directory fsync)
    # must not stall the event loop; contextvars carry the Task scope into
    # the worker thread so the file still lands in the right scratch dir.
    return await asyncio.to_thread(
        persist_image_bytes,
        img_bytes,
        model_name,
        "url→file",
    )


def _logged_model_error(message: str, model_name: str) -> ModelError:
    """Log and build the terminal error in one step.

    The message doubles as the persisted task error that the transient
    classifier matches, so it must always carry a detail — an empty one
    once turned a plain network blip into a deterministic wall.
    """

    logger.error(message)
    return ModelError(message, model_name=model_name)


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


def _mask_key(key: str, prefix: int = 10) -> str:
    if not key:
        return "(empty)"
    if len(key) <= prefix:
        return key
    return f"{key[:prefix]}...({len(key)} chars)"


def _image_api_key(env_name: str, default: str = "") -> str:
    """Image credential: explicit value first, else optionally reuse LLM.

    Bailian image generation runs on the same DashScope credential as the
    text model, so when no image-specific key is configured and the
    persisted ``image.reuse_llm_key`` flag (default on) allows it, the text
    key is reused — mirroring the tts/s2v sections.
    """
    configured = _configured_value("api_key", env_name, default)
    logger.info(
        "Image API key lookup | env=%s, configured=%s, default=%s",
        env_name,
        _mask_key(configured),
        _mask_key(default),
    )
    if configured:
        return configured
    section = model_config._get_user_config().get("image", {})
    reuse = not isinstance(section, dict) or section.get(
        "reuse_llm_key",
        True,
    )
    logger.info(
        "Image API key fallback | reuse_llm_key=%s, section_keys=%s",
        reuse,
        list(section.keys()) if isinstance(section, dict) else "(not dict)",
    )
    result = model_config.get_text_api_key() if reuse else ""
    logger.info(
        "Image API key final | result=%s",
        _mask_key(result),
    )
    return result


def _validated_mode(
    mode: str,
    *,
    reference_count: int,
    supported_modes: frozenset[str],
    backend_name: str,
    model_name: str,
) -> str:
    """Normalize and validate the requested image operation mode."""

    active_mode = (mode or "generate").strip().casefold() or "generate"
    if active_mode not in IMAGE_GENERATION_MODES:
        raise ModelError(
            f"Unknown image mode {mode!r}; supported modes: "
            f"{', '.join(IMAGE_GENERATION_MODES)}",
            model_name=model_name,
        )
    if active_mode not in supported_modes:
        raise ModelError(
            f"The {backend_name} image provider does not support "
            f"mode '{active_mode}'; switch creator_image_model to the "
            "DashScope (Bailian) qwen-image provider for edit/translate",
            model_name=model_name,
        )
    reference_limit = image_reference_limit(model_name)
    if active_mode == "edit" and (
        reference_limit is None
        or not EDIT_MIN_REFERENCE_IMAGES <= reference_count <= reference_limit
    ):
        limit_label = (
            str(reference_limit)
            if reference_limit is not None
            else "an officially registered limit"
        )
        raise ModelError(
            f"Image edit mode requires 1-{limit_label} reference images, "
            f"got {reference_count}",
            model_name=model_name,
        )
    if active_mode == "translate" and reference_count != 1:
        raise ModelError(
            "Image translate mode requires exactly 1 reference image, "
            f"got {reference_count}",
            model_name=model_name,
        )
    return active_mode


class BaseImageModel(ABC):
    """Common image-generation envelope shared by every backend.

    Subclasses implement ``_request`` (build & send the provider-specific
    HTTP call) and ``_decode`` (parse the provider response into a saved
    image URL). Everything else — retries, rate-limit backoff, concurrency
    slot, error wrapping — is handled here.
    """

    backend_name: str = "base"
    # Providers opt into extra modes explicitly; the base contract is plain
    # generation so a new backend never silently accepts edit/translate.
    supported_modes: frozenset[str] = frozenset({"generate"})

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
        mode: str = "generate",
        source_lang: str = "",
        target_lang: str = "",
    ) -> dict:
        """Generate an image, persist it, and return a dict.

        Returns:
            {"url": local_url, "source_url": original_url_or_empty}

        ``mode`` selects the qwen-image operation: ``generate`` (default),
        ``edit`` (instruction editing over 1-3 reference images) or
        ``translate`` (in-image text translation; ``source_lang`` /
        ``target_lang`` apply to this mode only).
        """
        missing = [
            name
            for name, value in (
                ("api_key", self.api_key),
                ("base_url", getattr(self, "base_url", "")),
                ("model", self.model_name),
            )
            if not value
        ]
        if missing:
            raise ModelError(
                "Creator image model configuration is incomplete: "
                + ", ".join(missing)
                + ". Configure creator_image_model before retrying.",
                model_name=self.model_name,
            )

        clean_reference_urls = [
            url.strip()
            for url in (reference_image_urls or [])
            if url and url.strip()
        ]
        active_mode = _validated_mode(
            mode,
            reference_count=len(clean_reference_urls),
            supported_modes=self.supported_modes,
            backend_name=self.backend_name,
            model_name=self.model_name,
        )

        logger.info(
            f"Generating image | model={self.model_name}, "
            f"backend={self.backend_name}, mode={active_mode}, "
            f"prompt_length={len(prompt)}, "
            f"references={len(clean_reference_urls)}",
        )

        try:
            if active_mode == "translate":
                async with model_slot("image"):
                    local_url = await self._translate(
                        clean_reference_urls[0],
                        source_lang=(source_lang or "auto").strip() or "auto",
                        target_lang=(target_lang or "en").strip() or "en",
                    )
                    return {"url": local_url, "source_url": ""}
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
                            active_mode,
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
        except httpx.TransportError as e:
            # ReadError/WriteError/ConnectError stringify empty; losing the
            # type name made the persisted error unclassifiable and a plain
            # network blip became a deterministic wall (field run
            # 2026-08-10: an upload burst locked two storyboard nodes).
            raise _logged_model_error(
                "Image generation connection failure: "
                f"{str(e) or type(e).__name__}",
                self.model_name,
            )
        except httpx.HTTPStatusError as e:
            detail = format_http_error_detail(e.response)
            logger.error(
                f"Image generation HTTP error: {e.response.status_code} - {detail[:500]}",
            )
            raise ModelError(
                f"Image generation failed with status {e.response.status_code}: "
                f"{detail[:500]}. Check creator_image_model configuration.",
                model_name=self.model_name,
            )
        except Exception as e:
            raise _logged_model_error(
                f"Image generation failed: {str(e) or type(e).__name__}. "
                "Check creator_image_model configuration.",
                self.model_name,
            )

    async def _translate(
        self,
        image_url: str,
        *,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """In-image text translation; only DashScope implements this."""

        raise ModelError(
            f"The {self.backend_name} image provider does not implement "
            "translate",
            model_name=self.model_name,
        )

    @abstractmethod
    async def _request(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        aspect_ratio: str,
        clean_reference_urls: list[str],
        mode: str = "generate",
    ) -> httpx.Response:
        """Build and send the provider-specific generation request.

        ``mode`` is the validated operation mode, so a provider can enforce
        edit semantics instead of degrading into text-to-image.
        """

    @abstractmethod
    async def _decode(self, data: dict | list) -> str:
        """Parse the provider response, persist the image, return its URL."""
