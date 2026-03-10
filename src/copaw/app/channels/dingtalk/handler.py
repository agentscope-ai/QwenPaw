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
    conversation_type_from_chatbot_message,
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
        try_accept_message: Optional[Callable[[str], bool]] = None,
    ):
        super().__init__()
        self._main_loop = main_loop
        self._enqueue_callback = enqueue_callback
        self._bot_prefix = bot_prefix
        self._download_url_fetcher = download_url_fetcher
        self._try_accept_message = try_accept_message

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
        filename_hint: Optional[str] = None,
    ) -> Optional[Any]:
        """Fetch media by download_code; return Content to append or None."""
        hint = (filename_hint or "").strip() or FILENAME_HINT_BY_MAPPED.get(
            mapped,
            DEFAULT_FILENAME_HINT,
        )
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

    @staticmethod
    def _extract_filename_hint(payload: Dict[str, Any]) -> Optional[str]:
        """Extract filename hint from DingTalk payload variants."""
        for key in ("fileName", "file_name", "filename", "name", "title"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
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
                # Text may be under "text" or "content" (API variation).
                item_text = item.get("text") or item.get("content")
                if item_text is not None:
                    content.append(
                        TextContent(
                            type=ContentType.TEXT,
                            text=(item_text or "").strip(),
                        ),
                    )
                # Picture items may use pictureDownloadCode or downloadCode.
                dl_code = (
                    item.get("downloadCode")
                    or item.get("download_code")
                    or item.get("pictureDownloadCode")
                    or item.get("picture_download_code")
                )
                if not dl_code or not robot_code:
                    continue
                mapped = type_mapping.get(
                    item.get("type", "file"),
                    item.get("type", "file"),
                )
                filename_hint = self._extract_filename_hint(item)
                part_content = self._fetch_download_url_and_content(
                    dl_code,
                    robot_code,
                    mapped,
                    filename_hint=filename_hint,
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
                    filename_hint = self._extract_filename_hint(c)
                    part_content = self._fetch_download_url_and_content(
                        dl_code,
                        robot_code,
                        mapped,
                        filename_hint=filename_hint,
                    )
                    if part_content is not None:
                        content.append(part_content)

        except Exception:
            logger.exception("failed to fetch richText download url(s)")
        return content

    async def process(self, callback: CallbackMessage) -> tuple[int, str]:
        # pylint: disable=too-many-branches,too-many-statements
        try:
            # Raw msgId from channel callback for dedup (not assigned id).
            raw_data = getattr(callback, "data", None) or {}
            raw_msg_id = str(
                raw_data.get("msgId") or raw_data.get("msg_id") or "",
            ).strip()
            logger.info(
                "dingtalk raw callback: msgId=%r keys=%s",
                raw_msg_id or "(empty)",
                list(raw_data.keys()) if isinstance(raw_data, dict) else "?",
            )
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
            # preserved. Do not prepend when top-level text is only a
            # placeholder (e.g. "\\n", "//n") so image+text from richText
            # is not overwritten.
            rich_has_text = any(
                item.type == "text" and (item.text or "").strip()
                for item in content
            )
            text_is_placeholder = not (text or "").strip() or (
                (text or "").strip() in ("\\n", "//n")
            )
            if (
                text
                and content
                and not rich_has_text
                and not text_is_placeholder
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
            conversation_type = conversation_type_from_chatbot_message(
                incoming_message,
            )
            loop = asyncio.get_running_loop()
            reply_future: asyncio.Future[str] = loop.create_future()
            meta: Dict[str, Any] = {
                "incoming_message": incoming_message,
                "reply_future": reply_future,
                "reply_loop": loop,
                "conversation_type": conversation_type,
                "is_group": conversation_type == "group",
            }
            if conversation_id:
                meta["conversation_id"] = conversation_id
            if raw_msg_id:
                meta["message_id"] = raw_msg_id
            sw = getattr(incoming_message, "sessionWebhook", None) or getattr(
                incoming_message,
                "session_webhook",
                None,
            )
            logger.debug(
                "dingtalk request: has_session_webhook=%s sender=%s",
                bool(sw),
                sender,
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

            # Dedup by message_id only.
            if self._try_accept_message and not self._try_accept_message(
                raw_msg_id,
            ):
                logger.info(
                    "dingtalk duplicate ignored: raw_msg_id=%r from=%s",
                    raw_msg_id,
                    sender,
                )
                self.reply_text(" ", incoming_message)
                return dingtalk_stream.AckMessage.STATUS_OK, "ok"

            logger.info(
                "dingtalk accept: raw_msg_id=%r",
                raw_msg_id or "(empty)",
            )
            native = {
                "channel_id": "dingtalk",
                "sender_id": sender,
                "content_parts": parts_to_send,
                "meta": meta,
            }
            if raw_msg_id:
                native["message_id"] = raw_msg_id
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
                # Stream connection still expects a reply frame;
                # send minimal ack so the connection completes and next
                # messages work.
                self.reply_text(" ", incoming_message)
            else:
                out = self._bot_prefix + response_text
                self.reply_text(out, incoming_message)
                logger.info("sent to=%s text=%r", sender, out[:100])
            return dingtalk_stream.AckMessage.STATUS_OK, "ok"

        except Exception:
            logger.exception("process failed")
            return dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION, "error"
