# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,too-many-branches
"""GPT Image 2 image generation tool."""

import base64
import logging
import time
from pathlib import Path
from typing import List

import httpx
from agentscope.message import ImageBlock, TextBlock
from agentscope.tool import ToolResponse
from qwenpaw.constant import DEFAULT_MEDIA_DIR
from qwenpaw.plugins import get_tool_config

logger = logging.getLogger(__name__)


async def generate_image_gpt(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "auto",
) -> ToolResponse:
    """Generate an image using OpenAI GPT Image 2 model.

    This tool uses OpenAI's state-of-the-art GPT Image 2 model to
    generate high-quality images from text descriptions.

    Args:
        prompt (str):
            Text description of the image to generate. Be specific
            and detailed for best results.
        size (str, optional):
            Output image size. Options: "1024x1024", "1024x1792",
            "1792x1024". Defaults to "1024x1024".
        quality (str, optional):
            Image quality level. Options: "low", "medium", "high", "auto".
            - low: Faster generation, lower quality
            - medium: Balanced quality and speed
            - high: Best quality, slower generation
            - auto: Automatically choose based on prompt (default)

    Returns:
        ToolResponse:
            Contains the generated image and metadata.

    Example:
        >>> result = await generate_image_gpt(
        ...     prompt="A serene mountain landscape at sunset",
        ...     size="1792x1024",
        ... )
    """
    try:
        # Get tool config (API key and endpoint)
        tool_config = get_tool_config("generate_image_gpt")
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

        api_key = tool_config.get("api_key")
        if not api_key:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: OpenAI API key not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        # Get endpoint from config, use default if not set
        endpoint = tool_config.get("endpoint")
        if not endpoint or not endpoint.strip():
            endpoint = "https://api.openai.com/v1/images/generations"

        # Get timeout from config, use default if not set
        timeout = tool_config.get("timeout")
        if timeout is None or timeout <= 0:
            timeout = 60.0
        else:
            timeout = float(timeout)

        # Validate parameters
        valid_sizes = {"1024x1024", "1024x1792", "1792x1024"}
        if size not in valid_sizes:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid size '{size}'. "
                            f"Must be one of: {', '.join(valid_sizes)}"
                        ),
                    ),
                ],
            )

        # Validate quality parameter
        # GPT Image 2 supports: low, medium, high, auto
        valid_quality = {"low", "medium", "high", "auto"}
        if quality not in valid_quality:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid quality '{quality}'. "
                            f"Must be one of: "
                            f"{', '.join(sorted(valid_quality))}"
                        ),
                    ),
                ],
            )

        # Call OpenAI API
        logger.info(
            f"Generating image with GPT Image 2: "
            f"size={size}, quality={quality}",
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-image-2",
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "n": 1,
                },
            )

        if response.status_code != 200:
            error_msg = f"OpenAI API error: {response.status_code}"
            try:
                error_data = response.json()
                if "error" in error_data:
                    error_msg += f" - {error_data['error'].get('message')}"
            except Exception:
                pass
            logger.error(error_msg)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: {error_msg}",
                    ),
                ],
            )

        # Parse response
        # GPT Image 2 returns b64_json, not url
        data = response.json()
        b64_json = data["data"][0]["b64_json"]

        logger.info("Image generated successfully (base64)")

        # Save image to local file in DEFAULT_MEDIA_DIR

        media_dir = DEFAULT_MEDIA_DIR / "gpt_image2"
        media_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename using timestamp
        timestamp = int(time.time() * 1000)
        filename = f"gpt_image2_{timestamp}.png"
        image_path = media_dir / filename

        # Decode base64 and save to file
        try:
            image_data = base64.b64decode(b64_json)
            image_path.write_bytes(image_data)
            logger.info(f"Image saved to {image_path}")
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Failed to save image - {str(e)}",
                    ),
                ],
            )

        # Return image with local file path
        return ToolResponse(
            content=[
                ImageBlock(
                    type="image",
                    source={"type": "url", "url": str(image_path)},
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Generated image using GPT Image 2\n"
                        f"Prompt: {prompt}\n"
                        f"Size: {size}, Quality: {quality}\n"
                        f"Saved to: {image_path}"
                    ),
                ),
            ],
        )

    except httpx.TimeoutException:
        logger.error("Image generation timed out")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: Image generation timed out. "
                        "Please try again."
                    ),
                ),
            ],
        )
    except Exception as e:
        logger.error(f"Image generation failed: {e}", exc_info=True)
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Image generation failed - {str(e)}",
                ),
            ],
        )


async def edit_image_gpt(  # pylint: disable=too-many-statements
    prompt: str,
    reference_images: List[str],
    size: str = "1024x1024",
    quality: str = "auto",
) -> ToolResponse:
    """Edit or generate image using reference images with GPT Image 2.

    This tool uses OpenAI's GPT Image 2 model to generate or edit images
    based on one or more reference images and a text prompt.

    Note: gpt-image-2 always processes images at high fidelity and does
    not support the input_fidelity parameter.

    Args:
        prompt (str):
            Text description of the desired image edit or generation.
        reference_images (List[str]):
            List of reference images (1-16 images). Each item can be:
            - Web URL (https://example.com/image.png)
            - Local file path (/path/to/image.png)
            Note: Local files will be converted to base64 automatically.
        size (str, optional):
            Output image size. Options: "1024x1024", "1024x1536",
            "1536x1024", "auto". Defaults to "1024x1024".
        quality (str, optional):
            Image quality level. Options: "low", "medium", "high", "auto".
            Defaults to "auto".

    Returns:
        ToolResponse:
            Contains the generated/edited image and metadata.

    Example:
        >>> result = await edit_image_gpt(
        ...     prompt="Make this photo look like a watercolor painting",
        ...     reference_images=["/path/to/photo.jpg"],
        ...     quality="high"
        ... )
    """
    try:
        # Validate reference_images
        if not reference_images:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: reference_images is required. "
                            "Please provide at least one reference image."
                        ),
                    ),
                ],
            )

        if len(reference_images) > 16:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Too many reference images. "
                            f"Maximum is 16, got {len(reference_images)}."
                        ),
                    ),
                ],
            )

        # Get tool config
        tool_config = get_tool_config("edit_image_gpt")
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

        api_key = tool_config.get("api_key")
        if not api_key:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: OpenAI API key not configured. "
                            "Please set your API key in the tool settings."
                        ),
                    ),
                ],
            )

        # Get endpoint from config, use default if not set
        endpoint = tool_config.get("endpoint")
        if not endpoint or not endpoint.strip():
            endpoint = "https://api.openai.com/v1/images/edits"

        # Get timeout from config
        timeout = tool_config.get("timeout")
        if timeout is None or timeout <= 0:
            timeout = 60.0
        else:
            timeout = float(timeout)

        # Validate parameters
        valid_sizes = {"auto", "1024x1024", "1024x1536", "1536x1024"}
        if size not in valid_sizes:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid size '{size}'. "
                            f"Must be one of: {', '.join(valid_sizes)}"
                        ),
                    ),
                ],
            )

        valid_quality = {"low", "medium", "high", "auto"}
        if quality not in valid_quality:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid quality '{quality}'. "
                            f"Must be one of: "
                            f"{', '.join(sorted(valid_quality))}"
                        ),
                    ),
                ],
            )

        # Process reference images
        try:
            images_payload = []
            for img_path in reference_images:
                img_dict = _process_image_url(img_path)
                images_payload.append(img_dict)
        except FileNotFoundError as e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Reference image not found - {str(e)}",
                    ),
                ],
            )
        except Exception as e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Failed to process reference images - "
                            f"{str(e)}"
                        ),
                    ),
                ],
            )

        # Call OpenAI API
        logger.info(
            f"Editing image with GPT Image 2: {len(reference_images)} "
            f"reference images, size={size}, quality={quality}",
        )

        # Note: gpt-image-2 does not support input_fidelity parameter
        # It always processes images at high fidelity
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-image-2",
                    "images": images_payload,
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "n": 1,
                },
            )

        if response.status_code != 200:
            error_msg = f"OpenAI API error: {response.status_code}"
            try:
                error_data = response.json()
                if "error" in error_data:
                    error_msg += f" - {error_data['error'].get('message')}"
            except Exception:
                pass
            logger.error(error_msg)
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: {error_msg}",
                    ),
                ],
            )

        # Parse response
        data = response.json()
        b64_json = data["data"][0]["b64_json"]

        logger.info("Image edited successfully (base64)")

        # Save image to local file
        media_dir = DEFAULT_MEDIA_DIR / "gpt_image2"
        media_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time() * 1000)
        filename = f"gpt_image2_edit_{timestamp}.png"
        image_path = media_dir / filename

        # Decode base64 and save to file
        try:
            image_data = base64.b64decode(b64_json)
            image_path.write_bytes(image_data)
            logger.info(f"Image saved to {image_path}")
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Failed to save image - {str(e)}",
                    ),
                ],
            )

        # Return image with local file path
        return ToolResponse(
            content=[
                ImageBlock(
                    type="image",
                    source={"type": "url", "url": str(image_path)},
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Edited image using GPT Image 2\n"
                        f"Prompt: {prompt}\n"
                        f"Reference images: {len(reference_images)}\n"
                        f"Size: {size}, Quality: {quality}\n"
                        f"Saved to: {image_path}"
                    ),
                ),
            ],
        )

    except httpx.TimeoutException:
        logger.error("Image editing timed out")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=("Error: Image editing timed out. Please try again."),
                ),
            ],
        )
    except Exception as e:
        logger.error(f"Image editing failed: {e}", exc_info=True)
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Image editing failed - {str(e)}",
                ),
            ],
        )


def _process_image_url(image_path: str) -> dict:
    """Convert image path/URL to API format.

    Args:
        image_path: Web URL or local file path

    Returns:
        dict: {"image_url": "..."} for API payload

    Raises:
        FileNotFoundError: If local file doesn't exist
        ValueError: If file format is not supported
    """
    if image_path.startswith(("http://", "https://")):
        # Web URL - use directly
        return {"image_url": image_path}

    # Local file - convert to base64 data URL
    path_obj = Path(image_path)

    if not path_obj.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    if not path_obj.is_file():
        raise ValueError(f"Not a file: {image_path}")

    # Detect MIME type from extension
    ext = path_obj.suffix.lower()
    mime_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }

    if ext not in mime_type_map:
        raise ValueError(
            f"Unsupported image format: {ext}. "
            f"Supported formats: {', '.join(mime_type_map.keys())}",
        )

    mime_type = mime_type_map[ext]

    # Read and encode image
    with open(path_obj, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    return {"image_url": f"data:{mime_type};base64,{image_data}"}
