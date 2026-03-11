# -*- coding: utf-8 -*-
"""WeCom channel message handlers."""

import logging
import re
from typing import TYPE_CHECKING

from wecom_aibot_sdk.types import WsFrame

from ..base import ContentType, TextContent
from .constants import CHAT_TYPE_GROUP, WELCOME_MESSAGE

if TYPE_CHECKING:
    from .channel import WecomChannel

logger = logging.getLogger(__name__)


async def handle_text(
    channel: "WecomChannel",
    frame: WsFrame,
) -> None:
    """Handle text message.

    Args:
        channel: WecomChannel instance.
        frame: Raw WsFrame from SDK.
    """
    body = frame.get("body", {})
    text = body.get("text", {}).get("content", "")
    chattype = body.get("chattype", "")

    # Strip @bot mention in group chats
    if chattype == CHAT_TYPE_GROUP:
        text = re.sub(r"@\S+", "", text).strip()

    if not text:
        logger.info("[WeCom] Skipping empty text message")
        return

    parts = [TextContent(type=ContentType.TEXT, text=text)]
    await channel.dispatch_message(frame, parts)


async def handle_image(
    channel: "WecomChannel",
    frame: WsFrame,
) -> None:
    """Handle image message.

    Args:
        channel: WecomChannel instance.
        frame: Raw WsFrame from SDK.
    """
    body = frame.get("body", {})
    image = body.get("image", {})
    url = image.get("url", "")
    aes_key = image.get("aeskey", "")

    if not url:
        logger.warning("[WeCom] Image message missing URL, skipping")
        return

    if not aes_key:
        logger.warning("[WeCom] Image message missing aeskey, skipping")
        return

    img = await channel.download_image(url, aes_key)
    if not img:
        logger.warning("[WeCom] Image processing failed, skipping")
        return

    await channel.dispatch_message(frame, [img])


async def handle_mixed(
    channel: "WecomChannel",
    frame: WsFrame,
) -> None:
    """Handle mixed (text + image) message.

    Args:
        channel: WecomChannel instance.
        frame: Raw WsFrame from SDK.
    """
    body = frame.get("body", {})
    text_parts = []
    content_parts = []

    for item in body.get("mixed", {}).get("msg_item", []):
        item_type = item.get("msgtype")
        if item_type == "text":
            t = item.get("text", {}).get("content", "")
            if t:
                text_parts.append(t)
        elif item_type == "image":
            img_data = item.get("image", {})
            url = img_data.get("url", "")
            aes_key = img_data.get("aeskey", "")
            if url and aes_key:
                img = await channel.download_image(url, aes_key)
                if img:
                    content_parts.append(img)
            elif url and not aes_key:
                logger.warning(
                    "[WeCom] Image in mixed message missing aeskey",
                )

    if text_parts:
        content_parts.insert(
            0,
            TextContent(
                type=ContentType.TEXT,
                text="\n".join(text_parts),
            ),
        )

    if not content_parts:
        logger.info("[WeCom] Mixed message has no valid content, skipping")
        return

    await channel.dispatch_message(frame, content_parts)


async def handle_voice(
    channel: "WecomChannel",
    frame: WsFrame,
) -> None:
    """Handle voice message (already transcribed to text).

    Args:
        channel: WecomChannel instance.
        frame: Raw WsFrame from SDK.
    """
    body = frame.get("body", {})
    text = body.get("voice", {}).get("content", "")
    if not text:
        logger.info("[WeCom] Voice message has no transcribed text, skipping")
        return

    parts = [TextContent(type=ContentType.TEXT, text=text)]
    await channel.dispatch_message(frame, parts)


async def handle_file(
    channel: "WecomChannel",  # pylint: disable=unused-argument
    frame: WsFrame,
) -> None:
    """Handle file message (log only, not yet processed).

    Args:
        channel: WecomChannel instance (unused).
        frame: Raw WsFrame from SDK.
    """
    body = frame.get("body", {})
    file_info = body.get("file", {})
    logger.info(
        "[WeCom] Received file message, filename: %s (not yet handled)",
        file_info.get("name", "unknown"),
    )


async def send_welcome(
    channel: "WecomChannel",
    frame: WsFrame,
) -> None:
    """Send welcome message on enter_chat event.

    Must be called within 5 seconds of the enter_chat event.

    Args:
        channel: WecomChannel instance.
        frame: Raw WsFrame from SDK.
    """
    if not channel.client:
        return
    try:
        await channel.client.reply_welcome(
            frame,
            {
                "msgtype": "text",
                "text": {"content": WELCOME_MESSAGE},
            },
        )
        logger.info("[WeCom] Welcome message sent")
    except Exception as exc:
        logger.error(
            "[WeCom] Failed to send welcome message: %s",
            exc,
            exc_info=True,
        )
