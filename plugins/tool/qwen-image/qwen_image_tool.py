# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,too-many-branches
# pylint: disable=too-many-statements,too-many-locals
"""Qwen-Image image generation and editing tools."""

import asyncio
import base64
import logging
import threading
import time
from pathlib import Path
from typing import List

import httpx
from agentscope.message import ImageBlock, TextBlock
from agentscope.tool import ToolResponse
from qwenpaw.constant import DEFAULT_MEDIA_DIR
from qwenpaw.plugins import get_tool_config

logger = logging.getLogger(__name__)

# Thread lock to protect dashscope global base_http_api_url setting
_DASHSCOPE_LOCK = threading.Lock()

_DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1"
_DEFAULT_TIMEOUT = 120.0

_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_VALID_MODELS_GENERATE = {
    "qwen-image-2.0-pro",
    "qwen-image-2.0-pro-2026-04-22",
    "qwen-image-2.0-pro-2026-03-03",
    "qwen-image-2.0",
    "qwen-image-2.0-2026-03-03",
    "qwen-image-max",
    "qwen-image-max-2025-12-30",
    "qwen-image-plus",
    "qwen-image-plus-2026-01-09",
    "qwen-image",
}

_VALID_MODELS_EDIT = {
    "qwen-image-2.0-pro",
    "qwen-image-2.0-pro-2026-04-22",
    "qwen-image-2.0-pro-2026-03-03",
    "qwen-image-2.0",
    "qwen-image-2.0-2026-03-03",
    "qwen-image-edit-max",
    "qwen-image-edit-max-2026-01-16",
    "qwen-image-edit-plus",
    "qwen-image-edit-plus-2025-12-15",
    "qwen-image-edit-plus-2025-10-30",
    "qwen-image-edit",
}


def _resolve_image_url(path_or_url: str) -> str:
    """Resolve an image path or URL to a usable string.

    If the input is an HTTP/HTTPS URL, return it as-is.
    If the input is a local file path, read the file and return
    a base64 data URL.

    Args:
        path_or_url: HTTP/HTTPS URL or local file path.

    Returns:
        str: A URL (original URL or base64 data URL).

    Raises:
        FileNotFoundError: If the local file does not exist.
        ValueError: If the file format is not supported.
    """
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url

    path_obj = Path(path_or_url)
    if not path_obj.exists():
        raise FileNotFoundError(
            f"Image file not found: {path_or_url}",
        )
    if not path_obj.is_file():
        raise ValueError(f"Not a file: {path_or_url}")

    ext = path_obj.suffix.lower()
    if ext not in _IMAGE_MIME_TYPES:
        raise ValueError(
            f"Unsupported image format: {ext}. "
            f"Supported: {', '.join(_IMAGE_MIME_TYPES.keys())}",
        )

    mime_type = _IMAGE_MIME_TYPES[ext]
    with open(path_obj, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{image_data}"


def _extract_config(
    tool_config: dict,
    default_model: str,
) -> tuple[str, str, float, str]:
    """Extract api_key, endpoint, timeout and model from tool config.

    Args:
        tool_config: Tool configuration dict.
        default_model: Fallback model name when not set in config.

    Returns:
        Tuple of (api_key, endpoint, timeout, model).
    """
    api_key = tool_config.get("api_key", "")
    endpoint = tool_config.get("endpoint", "")
    if not endpoint or not endpoint.strip():
        endpoint = _DEFAULT_ENDPOINT

    timeout_raw = tool_config.get("timeout")
    if timeout_raw is None or float(timeout_raw) <= 0:
        timeout = _DEFAULT_TIMEOUT
    else:
        timeout = float(timeout_raw)

    model = tool_config.get("model", "") or default_model

    return api_key, endpoint, timeout, model


async def _download_image(
    image_url: str,
    save_dir: Path,
    prefix: str,
    timeout: float,
) -> Path:
    """Download image from URL and save to local directory.

    Args:
        image_url: Public URL of the image.
        save_dir: Directory to save the image.
        prefix: Filename prefix.
        timeout: HTTP timeout in seconds.

    Returns:
        Path: Local path of the saved image.

    Raises:
        Exception: If download fails.
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000)
    filename = f"{prefix}_{timestamp}.png"
    image_path = save_dir / filename

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", image_url) as response:
            response.raise_for_status()
            chunks = []
            async for chunk in response.aiter_bytes(chunk_size=512 * 1024):
                chunks.append(chunk)
    await asyncio.to_thread(image_path.write_bytes, b"".join(chunks))

    logger.info(f"Image saved to {image_path}")
    return image_path


def _call_multimodal_conversation(
    api_key: str,
    endpoint: str,
    model: str,
    messages: list,
    **kwargs,
):
    """Call DashScope MultiModalConversation with thread-safe setup.

    Args:
        api_key: DashScope API key.
        endpoint: Base HTTP API URL.
        model: Model name.
        messages: Message list for the conversation.
        **kwargs: Additional parameters passed to call().

    Returns:
        SDK response object.
    """
    import dashscope
    from dashscope import MultiModalConversation

    with _DASHSCOPE_LOCK:
        dashscope.base_http_api_url = endpoint
        rsp = MultiModalConversation.call(
            api_key=api_key,
            model=model,
            messages=messages,
            result_format="message",
            stream=False,
            **kwargs,
        )

    return rsp


def _parse_image_urls(response) -> List[str]:
    """Extract image URLs from MultiModalConversation response.

    Args:
        response: SDK response object.

    Returns:
        List of image URL strings.
    """
    urls = []
    choices = getattr(
        getattr(response, "output", None),
        "choices",
        None,
    )
    if not choices:
        return urls
    for choice in choices:
        message = getattr(choice, "message", None)
        if not message:
            continue
        content = getattr(message, "content", None)
        if not content:
            continue
        for item in content:
            if isinstance(item, dict):
                url = item.get("image")
            else:
                url = getattr(item, "image", None)
            if url:
                urls.append(url)
    return urls


async def generate_image_qwen(
    prompt: str,
    size: str = "2048*2048",
    n: int = 1,
    negative_prompt: str = "",
    prompt_extend: bool = True,
) -> ToolResponse:
    """Generate images from a text prompt using Qwen-Image models.

    Uses Alibaba Cloud's Qwen-Image models for high-quality image
    generation. Supports complex text rendering, multi-style artwork,
    and precise semantic adherence.

    The model is selected via the tool's configuration settings.
    Available models: qwen-image-2.0-pro (default), qwen-image-2.0,
    qwen-image-max, qwen-image-plus, and dated snapshot versions.

    Args:
        prompt (str):
            Text description of the image to generate.
            Supports Chinese and English, up to 800 characters
            (qwen-image-plus/max series) or longer (2.0 series).
        size (str, optional):
            Output image size in "width*height" format.
            For qwen-image-2.0 series: total pixels between
            512*512 and 2048*2048.
            Recommended sizes: "2048*2048" (1:1, default),
            "2688*1536" (16:9), "1536*2688" (9:16),
            "2368*1728" (4:3).
            For qwen-image-max/plus: use "1664*928" (16:9),
            "1328*1328" (1:1), "928*1664" (9:16).
        n (int, optional):
            Number of images to generate (1-6 for 2.0 series,
            fixed 1 for max/plus). Default: 1.
        negative_prompt (str, optional):
            Describe what to exclude from the image.
        prompt_extend (bool, optional):
            Enable prompt auto-optimization. Default: True.

    Returns:
        ToolResponse: Contains generated images and metadata.
    """
    try:
        tool_config = get_tool_config("generate_image_qwen")
        if not tool_config:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: Tool not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        api_key, endpoint, timeout, model = _extract_config(
            tool_config,
            default_model="qwen-image-2.0-pro",
        )
        if not api_key:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: DashScope API key not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        if model not in _VALID_MODELS_GENERATE:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid model '{model}'. "
                            f"Valid options: "
                            f"{', '.join(sorted(_VALID_MODELS_GENERATE))}"
                        ),
                    ),
                ],
            )

        if not 1 <= n <= 6:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid n '{n}'. "
                            f"Must be between 1 and 6."
                        ),
                    ),
                ],
            )

        messages = [
            {
                "role": "user",
                "content": [{"text": prompt}],
            },
        ]

        call_kwargs = {
            "watermark": False,
            "prompt_extend": prompt_extend,
            "n": n,
        }
        if size:
            call_kwargs["size"] = size
        if negative_prompt:
            call_kwargs["negative_prompt"] = negative_prompt

        logger.info(
            f"Generating image with Qwen-Image: "
            f"model={model}, size={size}, n={n}",
        )

        rsp = await asyncio.to_thread(
            _call_multimodal_conversation,
            api_key=api_key,
            endpoint=endpoint,
            model=model,
            messages=messages,
            **call_kwargs,
        )

        if rsp.status_code != 200:
            error_msg = (
                f"DashScope API error: {rsp.status_code} - "
                f"{rsp.code}: {rsp.message}"
            )
            logger.error(error_msg)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: {error_msg}",
                    ),
                ],
            )

        image_urls = _parse_image_urls(rsp)
        if not image_urls:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: No images returned from API. "
                            "Please try again."
                        ),
                    ),
                ],
            )

        logger.info(
            f"Qwen-Image generated {len(image_urls)} image(s)",
        )

        save_dir = DEFAULT_MEDIA_DIR / "qwen_image"
        content_blocks = []
        saved_paths = []

        for idx, img_url in enumerate(image_urls):
            prefix = f"qwen_image_gen_{idx}"
            try:
                image_path = await _download_image(
                    img_url,
                    save_dir,
                    prefix,
                    timeout,
                )
                saved_paths.append(str(image_path))
                content_blocks.append(
                    ImageBlock(
                        type="image",
                        source={
                            "type": "url",
                            "url": str(image_path),
                        },
                    ),
                )
            except Exception as e:
                logger.error(
                    f"Failed to download image {idx}: {e}",
                )
                content_blocks.append(
                    ImageBlock(
                        type="image",
                        source={"type": "url", "url": img_url},
                    ),
                )
                saved_paths.append(img_url)

        content_blocks.append(
            TextBlock(
                type="text",
                text=(
                    f"Generated {len(image_urls)} image(s) using "
                    f"Qwen-Image\n"
                    f"Model: {model}\n"
                    f"Prompt: {prompt}\n"
                    f"Size: {size}, Count: {n}\n"
                    f"Saved to: {', '.join(saved_paths)}"
                ),
            ),
        )

        return ToolResponse(content=content_blocks)

    except Exception as e:
        logger.error(
            f"Qwen-Image generation failed: {e}",
            exc_info=True,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(f"Error: Image generation failed - {str(e)}"),
                ),
            ],
        )


async def edit_image_qwen(
    prompt: str,
    reference_images: List[str],
    size: str = "",
    n: int = 1,
    negative_prompt: str = "",
    prompt_extend: bool = True,
) -> ToolResponse:
    """Edit or fuse images using Qwen-Image models.

    Supports single-image editing (modify content, style transfer,
    text rendering) and multi-image fusion (combine elements from
    multiple images).

    The model is selected via the tool's configuration settings.
    Available models: qwen-image-2.0-pro (default), qwen-image-2.0,
    qwen-image-edit-max, qwen-image-edit-plus, qwen-image-edit,
    and dated snapshot versions.

    Args:
        prompt (str):
            Description of the desired edit or fusion.
            When multiple images are provided, use "图一" / "图二"
            (or "image 1" / "image 2" in English) to refer to them.
        reference_images (List[str]):
            List of reference image URLs or local file paths
            (.png/.jpg/.jpeg/.webp). At least 1 image required.
            Each item can be:
            - HTTP/HTTPS URL
            - Local file path (auto-converted to base64)
        size (str, optional):
            Output image size in "width*height" format.
            Leave empty to auto-detect based on input image.
            For qwen-image-2.0 series: total pixels 512*512 to
            2048*2048. Example: "1024*1024", "2048*2048".
        n (int, optional):
            Number of output images (1-6 for 2.0/edit-plus,
            fixed 1 for edit-max/edit). Default: 1.
        negative_prompt (str, optional):
            Describe what to exclude from the output.
        prompt_extend (bool, optional):
            Enable prompt auto-optimization. Default: True.

    Returns:
        ToolResponse: Contains edited images and metadata.
    """
    try:
        if not reference_images:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: reference_images is required. "
                            "Please provide at least one image."
                        ),
                    ),
                ],
            )

        tool_config = get_tool_config("edit_image_qwen")
        if not tool_config:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: Tool not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        api_key, endpoint, timeout, model = _extract_config(
            tool_config,
            default_model="qwen-image-2.0-pro",
        )
        if not api_key:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: DashScope API key not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        if model not in _VALID_MODELS_EDIT:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid model '{model}'. "
                            f"Valid options: "
                            f"{', '.join(sorted(_VALID_MODELS_EDIT))}"
                        ),
                    ),
                ],
            )

        if not 1 <= n <= 6:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid n '{n}'. "
                            f"Must be between 1 and 6."
                        ),
                    ),
                ],
            )

        # Build message content: images first, then prompt text
        content = []
        for img_input in reference_images:
            try:
                resolved = _resolve_image_url(img_input)
            except (FileNotFoundError, ValueError) as e:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=(
                                f"Error: reference_images contains invalid "
                                f"entry '{img_input}' - {str(e)}"
                            ),
                        ),
                    ],
                )
            content.append({"image": resolved})

        content.append({"text": prompt})

        messages = [{"role": "user", "content": content}]

        call_kwargs = {
            "watermark": False,
            "prompt_extend": prompt_extend,
            "n": n,
        }
        if size:
            call_kwargs["size"] = size
        if negative_prompt:
            call_kwargs["negative_prompt"] = negative_prompt

        logger.info(
            f"Editing image with Qwen-Image: "
            f"model={model}, "
            f"reference_images={len(reference_images)}, n={n}",
        )

        rsp = await asyncio.to_thread(
            _call_multimodal_conversation,
            api_key=api_key,
            endpoint=endpoint,
            model=model,
            messages=messages,
            **call_kwargs,
        )

        if rsp.status_code != 200:
            error_msg = (
                f"DashScope API error: {rsp.status_code} - "
                f"{rsp.code}: {rsp.message}"
            )
            logger.error(error_msg)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: {error_msg}",
                    ),
                ],
            )

        image_urls = _parse_image_urls(rsp)
        if not image_urls:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: No images returned from API. "
                            "Please try again."
                        ),
                    ),
                ],
            )

        logger.info(
            f"Qwen-Image edit produced {len(image_urls)} image(s)",
        )

        save_dir = DEFAULT_MEDIA_DIR / "qwen_image"
        content_blocks = []
        saved_paths = []

        for idx, img_url in enumerate(image_urls):
            prefix = f"qwen_image_edit_{idx}"
            try:
                image_path = await _download_image(
                    img_url,
                    save_dir,
                    prefix,
                    timeout,
                )
                saved_paths.append(str(image_path))
                content_blocks.append(
                    ImageBlock(
                        type="image",
                        source={
                            "type": "url",
                            "url": str(image_path),
                        },
                    ),
                )
            except Exception as e:
                logger.error(
                    f"Failed to download image {idx}: {e}",
                )
                content_blocks.append(
                    ImageBlock(
                        type="image",
                        source={"type": "url", "url": img_url},
                    ),
                )
                saved_paths.append(img_url)

        content_blocks.append(
            TextBlock(
                type="text",
                text=(
                    f"Edited {len(image_urls)} image(s) using "
                    f"Qwen-Image\n"
                    f"Model: {model}\n"
                    f"Prompt: {prompt}\n"
                    f"Reference images: {len(reference_images)}\n"
                    f"Saved to: {', '.join(saved_paths)}"
                ),
            ),
        )

        return ToolResponse(content=content_blocks)

    except Exception as e:
        logger.error(
            f"Qwen-Image edit failed: {e}",
            exc_info=True,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Image editing failed - {str(e)}",
                ),
            ],
        )
