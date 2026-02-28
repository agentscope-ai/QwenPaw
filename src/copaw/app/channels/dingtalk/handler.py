# -*- coding: utf-8 -*-
"""DingTalk Stream callback handler: message -> native dict -> reply."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

import dingtalk_stream
from dingtalk_stream import CallbackMessage, ChatbotMessage
from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
)

from ..base import ContentType

from .constants import SENT_VIA_WEBHOOK
from .content_utils import (
    conversation_id_from_chatbot_message,
    dingtalk_content_from_type,
    get_type_mapping,
    sender_from_chatbot_message,
    session_param_from_webhook_url,
)

logger = logging.getLogger(__name__)

# Download filename hint by type (e.g. voice -> .amr).
FILENAME_HINT_BY_MAPPED = {
    "audio": "audio.amr",
    "image": "image.png",
    "video": "video.mp4",
}
DEFAULT_FILENAME_HINT = "file.bin"


class DingTalkChannelHandler(dingtalk_stream.ChatbotHandler):
    """Internal handler: convert DingTalk message to native dict, enqueue via
    manager (thread-safe), await reply_future, then reply."""

    def __init__(
        self,
        main_loop: asyncio.AbstractEventLoop,
        enqueue_callback: Optional[Callable[[Any], None]],
        bot_prefix: str,
        download_url_fetcher,
    ):
        super().__init__()
        self._main_loop = main_loop
        self._enqueue_callback = enqueue_callback
        self._bot_prefix = bot_prefix
        self._download_url_fetcher = download_url_fetcher

    def _emit_native_threadsafe(self, native: dict) -> None:
        if self._enqueue_callback:
            self._main_loop.call_soon_threadsafe(
                self._enqueue_callback,
                native,
            )

    def _fetch_download_url_and_content(
        self,
        download_code: str,
        robot_code: str,
        mapped: str,
    ) -> Optional[Any]:
        """Fetch media by download_code; return Content to append or None."""
        hint = FILENAME_HINT_BY_MAPPED.get(mapped, DEFAULT_FILENAME_HINT)
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._download_url_fetcher(
                    download_code=download_code,
                    robot_code=robot_code,
                    filename_hint=hint,
                ),
                self._main_loop,
            )
            download_url = fut.result(timeout=15)
            return dingtalk_content_from_type(mapped, download_url)
        except Exception:
            return None

    def _parse_rich_content(
        self,
        incoming_message: Any,
    ) -> List[Any]:
        """Parse richText from incoming_message into runtime Content list."""
        content: List[Any] = []
        type_mapping = get_type_mapping()
        try:
            robot_code = getattr(
                incoming_message,
                "robot_code",
                None,
            ) or getattr(incoming_message, "robotCode", None)
            msg_dict = incoming_message.to_dict()
            c = msg_dict.get("content") or {}
            raw = c.get("richText")
            raw = raw or c.get("rich_text")
            rich_list = raw if isinstance(raw, list) else []
            for item in rich_list:
                if not isinstance(item, dict):
                    continue
                if item.get("text") is not None:
                    content.append(
                        TextContent(
                            type=ContentType.TEXT,
                            text=item.get("text") or "",
                        ),
                    )
                dl_code = item.get("downloadCode")
                if not dl_code or not robot_code:
                    continue
                mapped = type_mapping.get(
                    item.get("type", "file"),
                    item.get("type", "file"),
                )
                part_content = self._fetch_download_url_and_content(
                    dl_code,
                    robot_code,
                    mapped,
                )
                if part_content is not None:
                    content.append(part_content)

            # -------- 2) single downloadCode (pure picture/file) --------
            if not content:
                dl_code = c.get("downloadCode") or c.get("download_code")
                if dl_code and robot_code:
                    msgtype = (
                        (
                            msg_dict.get(
                                "msgtype",
                            )
                            or ""
                        )
                        .lower()
                        .strip()
                    )
                    mapped = type_mapping.get(
                        msgtype,
                        msgtype or "file",
                    )
                    if mapped not in ("image", "file", "video", "audio"):
                        mapped = "file"
                    part_content = self._fetch_download_url_and_content(
                        dl_code,
                        robot_code,
                        mapped,
                    )
                    if part_content is not None:
                        content.append(part_content)

        except Exception:
            logger.exception("failed to fetch richText download url(s)")
        return content

    async def process(self, callback: CallbackMessage) -> tuple[int, str]:
        try:
            incoming_message = ChatbotMessage.from_dict(callback.data)

            logger.debug(
                "Dingtalk message received: %s",
                incoming_message.to_dict(),
            )
            content_parts: List[Any] = []
            text = ""
            if incoming_message.text:
                text = (incoming_message.text.content or "").strip()
            if text:
                content_parts.append(
                    TextContent(type=ContentType.TEXT, text=text),
                )
            # Always parse rich content so images/files are not dropped
            # when the message also contains text.
            content = self._parse_rich_content(incoming_message)
            # If text was extracted separately and rich content has no
            # text items, prepend the text so both text and media are
            # preserved in the content list.
            if (
                text
                and content
                and not any(
                    item.type == "text" and item.text for item in content
                )
            ):
                content.insert(
                    0,
                    TextContent(type=ContentType.TEXT, text=text),
                )
            # Use rich content (text + media with local paths) when present.
            parts_to_send = content if content else content_parts

            sender, skip = sender_from_chatbot_message(incoming_message)
            if skip:
                return dingtalk_stream.AckMessage.STATUS_OK, "ok"

            conversation_id = conversation_id_from_chatbot_message(
                incoming_message,
            )
            loop = asyncio.get_running_loop()
            reply_future: asyncio.Future[str] = loop.create_future()
            meta: Dict[str, Any] = {
                "incoming_message": incoming_message,
                "reply_future": reply_future,
                "reply_loop": loop,
            }
            if conversation_id:
                meta["conversation_id"] = conversation_id
            sw = getattr(incoming_message, "sessionWebhook", None) or getattr(
                incoming_message,
                "session_webhook",
                None,
            )
            if sw:
                meta["session_webhook"] = sw
                sw_exp = getattr(
                    incoming_message,
                    "sessionWebhookExpiredTime",
                    None,
                ) or getattr(
                    incoming_message,
                    "session_webhook_expired_time",
                    None,
                )
                logger.info(
                    "dingtalk recv: session_webhook present "
                    "session_from_url=%s "
                    "expired_time=%s",
                    session_param_from_webhook_url(sw),
                    sw_exp,
                )
            else:
                logger.debug(
                    "dingtalk recv: no sessionWebhook on incoming_message",
                )

            native = {
                "channel_id": "dingtalk",
                "sender_id": sender,
                "content_parts": parts_to_send,
                "meta": meta,
            }
            if sw:
                native["session_webhook"] = sw
            logger.info(
                "dingtalk emit: native has_sw=%s meta_sw=%s",
                bool(native.get("session_webhook")),
                bool((native.get("meta") or {}).get("session_webhook")),
            )
            logger.info("recv from=%s text=%s", sender, text[:100])
            self._emit_native_threadsafe(native)

            response_text = await reply_future
            if response_text == SENT_VIA_WEBHOOK:
                logger.info(
                    "sent to=%s via sessionWebhook (multi-message)",
                    sender,
                )
            else:
                out = self._bot_prefix + response_text
                self.reply_text(out, incoming_message)
                logger.info("sent to=%s text=%r", sender, out[:100])
            return dingtalk_stream.AckMessage.STATUS_OK, "ok"

        except Exception:
            logger.exception("process failed")
            return dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION, "error"
