# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""GPT Image 2 image generation tool."""

import logging
from typing import Optional
import httpx

from agentscope.message import ImageBlock, TextBlock
from agentscope.tool import ToolResponse

logger = logging.getLogger(__name__)


async def generate_image_gpt(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "standard",
    style: str = "natural",
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
            Image quality level. Options: "standard", "hd".
            Defaults to "standard".
        style (str, optional):
            Image style. Options: "natural", "vivid".
            Defaults to "natural".

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
        # Get API key from tool config
        api_key = _get_api_key()
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

        valid_quality = {"standard", "hd"}
        if quality not in valid_quality:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid quality '{quality}'. "
                            f"Must be one of: {', '.join(valid_quality)}"
                        ),
                    ),
                ],
            )

        valid_style = {"natural", "vivid"}
        if style not in valid_style:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Invalid style '{style}'. "
                            f"Must be one of: {', '.join(valid_style)}"
                        ),
                    ),
                ],
            )

        # Call OpenAI API
        logger.info(
            f"Generating image with GPT Image 2: "
            f"size={size}, quality={quality}, style={style}",
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-image-2",
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "style": style,
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
        image_url = data["data"][0]["url"]

        logger.info(f"Image generated successfully: {image_url}")

        # Return image with metadata
        return ToolResponse(
            content=[
                ImageBlock(
                    type="image",
                    source={"type": "url", "url": image_url},
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Generated image using GPT Image 2\n"
                        f"Prompt: {prompt}\n"
                        f"Size: {size}, Quality: {quality}, "
                        f"Style: {style}"
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


def _get_api_key() -> Optional[str]:
    """Get OpenAI API key from tool config.

    Returns:
        str or None: API key if configured, None otherwise
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

        return tool_config.get("api_key")
    except Exception as e:
        logger.error(f"Failed to get API key: {e}")
        return None
