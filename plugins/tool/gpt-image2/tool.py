# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""GPT Image 2 image generation tool."""

import base64
import logging
import time
from typing import Optional

import httpx
from agentscope.message import ImageBlock, TextBlock
from agentscope.tool import ToolResponse
from qwenpaw.constant import DEFAULT_MEDIA_DIR

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
        ...     quality="hd"
        ... )
    """
    try:
        # Get tool config (API key and endpoint)
        tool_config = _get_tool_config()
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

        async with httpx.AsyncClient(timeout=60.0) as client:
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


def _get_tool_config() -> Optional[dict]:
    """Get tool configuration including API key and endpoint.

    Returns:
        dict or None: Tool config if configured, None otherwise
    """
    try:
        from qwenpaw.plugins.registry import PluginRegistry
        from qwenpaw.app.agent_context import get_current_agent_id

        registry = PluginRegistry()
        if not registry:
            return None

        # Get current agent ID
        agent_id = get_current_agent_id()
        if not agent_id:
            logger.warning("No current agent ID found")
            return None

        # Get tool config for current agent
        tool_config = registry.get_tool_config(
            "generate_image_gpt",
            agent_id,
        )
        if not tool_config:
            return None

        return tool_config
    except Exception as e:
        logger.error(f"Failed to get tool config: {e}")
        return None
