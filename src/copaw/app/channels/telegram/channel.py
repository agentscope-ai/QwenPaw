# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Telegram channel: Bot API with polling; receive/send via chat_id."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Optional, Union

from telegram import BotCommand
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TimedOut,
)

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ....config.config import TelegramConfig as TelegramChannelConfig
from ....constant import WORKING_DIR
from .format_html import markdown_to_telegram_html
from ..utils import file_url_to_local_path
from ..base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
    OutgoingContentPart,
)

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_SEND_CHUNK_SIZE = 4000
TELEGRAM_MAX_FILE_SIZE_BYTES = (
    50 * 1024 * 1024
)  # 50 MB – Telegram bot upload limit

_DEFAULT_MEDIA_DIR = WORKING_DIR / "media" / "telegram"
_TYPING_TIMEOUT_S = 180

_RECONNECT_INITIAL_S = 2.0
_RECONNECT_MAX_S = 30.0
_RECONNECT_FACTOR = 1.8
_POLL_WATCHDOG_INTERVAL_S = 30

_MEDIA_ATTRS: list[tuple[str, type, Any, str]] = [
    ("document", FileContent, ContentType.FILE, "file_url"),
    ("video", VideoContent, ContentType.VIDEO, "video_url"),
    ("voice", AudioContent, ContentType.AUDIO, "data"),
    ("audio", AudioContent, ContentType.AUDIO, "data"),
]


class _FileTooLargeError(Exception):
    """Raised when a local media file exceeds Telegram's upload size limit."""


class _MediaFileUnavailableError(Exception):
    """Raised when a media file cannot be found or resolved."""


async def _download_telegram_file(
    *,
    bot: Any,
    file_id: str,
    media_dir: Path,
    filename_hint: str = "",
) -> Optional[str]:
    """Download a Telegram file to local media_dir; return local path.

    Never exposes the bot token in the returned path.
    """
    try:
        from telegram.error import TelegramError

        tg_file = await bot.get_file(file_id)
    except TelegramError:
        logger.exception("telegram: get_file failed for file_id=%s", file_id)
        return None

    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        suffix = ""
        file_path = (getattr(tg_file, "file_path", None) or "").strip()
        if file_path:
            suffix = Path(file_path).suffix
        if filename_hint and not suffix:
            suffix = Path(filename_hint).suffix
        local_name = f"{uuid.uuid4().hex[:12]}{suffix or '.bin'}"
        local_path = media_dir / local_name
        await tg_file.download_to_drive(str(local_path))
        return str(local_path)
    except Exception:
        logger.exception("telegram: download failed for file_id=%s", file_id)
        return None


async def _resolve_telegram_file_url(
    *,
    bot: Any,
    file_id: str,
    bot_token: str,
) -> str:
    """Resolve the remote URL for a Telegram file.

    Returns the file URL (either Telegram API URL or external URL).
    Never exposes the bot token in the returned URL.
    """
    try:
        from telegram.error import TelegramError

        tg_file = await bot.get_file(file_id)
    except TelegramError:
        logger.exception("telegram: get_file failed for file_id=%s", file_id)
        return ""
    file_path = getattr(tg_file, "file_path", None) or ""
    if not file_path:
        return ""
    if file_path.startswith("http"):
        return file_path
    return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"


async def _build_content_parts_from_message(
    update: Any,
    *,
    bot: Any,
    media_dir: Path,
) -> tuple[list, bool, bool]:
    """Build runtime content_parts from Telegram message.

    Returns (content_parts, has_bot_command, is_bot_mentioned).
    """
    message = getattr(update, "message", None) or getattr(
        update,
        "edited_message",
    )
    if not message:
        return [], False, False

    content_parts: list[Any] = []
    text = (
        getattr(message, "text", None) or getattr(message, "caption") or ""
    ).strip()

    entities = (
        getattr(message, "entities", None)
        or getattr(message, "caption_entities", None)
        or []
    )
    has_bot_command = False
    is_bot_mentioned = False
    bot_username = getattr(bot, "username", None) or ""

    if entities:
        for entity in entities:
            etype = getattr(entity, "type", None)
            if etype == "bot_command":
                has_bot_command = True
            elif etype == "mention" and bot_username:
                offset = getattr(entity, "offset", 0)
                length = getattr(entity, "length", 0)
                mentioned = text[offset : offset + length]
                if mentioned.lower() == f"@{bot_username.lower()}":
                    is_bot_mentioned = True
            elif etype == "text_mention":
                euser = getattr(entity, "user", None)
                if euser and str(
                    getattr(euser, "id", ""),
                ) == str(bot.id):
                    is_bot_mentioned = True

    if is_bot_mentioned and bot_username and text:
        text = re.sub(
            rf"@{re.escape(bot_username)}\b",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    if text:
        content_parts.append(TextContent(type=ContentType.TEXT, text=text))

    photo = getattr(message, "photo", None)
    if photo and len(photo) > 0:
        largest = photo[-1]
        file_id = getattr(largest, "file_id", None)
        if file_id:
            local_path = await _download_telegram_file(
                bot=bot,
                file_id=file_id,
                media_dir=media_dir,
                filename_hint="photo.jpg",
            )
            if local_path:
                file_url = Path(local_path).resolve().as_uri()
                content_parts.append(
                    ImageContent(type=ContentType.IMAGE, image_url=file_url),
                )

    for attr_name, content_cls, content_type, url_field in _MEDIA_ATTRS:
        media_obj = getattr(message, attr_name, None)
        if not media_obj:
            continue
        file_id = getattr(media_obj, "file_id", None)
        if not file_id:
            continue
        file_name = getattr(media_obj, "file_name", None) or attr_name
        local_path = await _download_telegram_file(
            bot=bot,
            file_id=file_id,
            media_dir=media_dir,
            filename_hint=file_name,
        )
        if local_path:
            file_url = Path(local_path).resolve().as_uri()
            content_parts.append(
                content_cls(type=content_type, **{url_field: file_url}),
            )

    return content_parts, has_bot_command, is_bot_mentioned


def _message_meta(update: Any) -> dict:
    """Extract chat_id, user_id, etc. from Telegram update."""
    message = getattr(update, "message", None) or getattr(
        update,
        "edited_message",
    )
    if not message:
        return {}
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    chat_id = str(getattr(chat, "id", "")) if chat else ""
    user_id = str(getattr(user, "id", "")) if user else ""
    username = (getattr(user, "username", None) or "") if user else ""
    chat_type = getattr(chat, "type", "") if chat else ""
    return {
        "chat_id": chat_id,
        "user_id": user_id,
        "username": username,
        "message_id": str(getattr(message, "message_id", "")),
        "is_group": chat_type in ("group", "supergroup", "channel"),
        "message_thread_id": getattr(message, "message_thread_id", None),
    }


class TelegramChannel(BaseChannel):
    """Telegram channel: Bot API polling; session_id = telegram:{chat_id}."""

    channel = "telegram"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        bot_token: str,
        http_proxy: str,
        http_proxy_auth: str,
        bot_prefix: str,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        media_dir: str = "",
        workspace_dir: Path | None = None,
        show_typing: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
        )
        self.enabled = enabled
        self._bot_token = bot_token
        self._http_proxy = http_proxy or ""
        self._http_proxy_auth = http_proxy_auth or ""
        self.bot_prefix = bot_prefix
        self._media_dir = (
            Path(media_dir).expanduser() if media_dir else _DEFAULT_MEDIA_DIR
        )
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )
        self._show_typing = show_typing
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._task: Optional[asyncio.Task] = None
        self._application = None
        if self.enabled and self._bot_token:
            try:
                self._application = self._build_application()
                logger.info(
                    "telegram: channel initialized (polling will start)",
                )
            except Exception:
                logger.exception("telegram: failed to build application")
                self._application = None
        else:
            if self.enabled and not self._bot_token:
                logger.info("telegram: channel disabled (bot_token empty)")
            elif not self.enabled:
                logger.debug(
                    "telegram: channel disabled (enabled=false in config)",
                )

    def _build_application(self):
        from telegram import Update
        from telegram.ext import (
            Application,
            ContextTypes,
            MessageHandler,
            filters,
        )

        def proxy_url() -> Optional[str]:
            if not self._http_proxy:
                return None
            if self._http_proxy_auth:
                if "://" in self._http_proxy:
                    prefix, rest = self._http_proxy.split("://", 1)
                    return f"{prefix}://{self._http_proxy_auth}@{rest}"
                return f"http://{self._http_proxy_auth}@{self._http_proxy}"
            return self._http_proxy

        builder = Application.builder().token(self._bot_token)
        proxy = proxy_url()
        if proxy:
            builder = builder.proxy(proxy).get_updates_proxy(proxy)

        app = builder.build()

        async def handle_message(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
        ) -> None:
            if not update.message and not getattr(
                update,
                "edited_message",
                None,
            ):
                return
            (
                content_parts,
                has_bot_command,
                is_bot_mentioned,
            ) = await _build_content_parts_from_message(
                update,
                bot=context.bot,
                media_dir=self._media_dir,
            )
            if not content_parts:
                logger.debug("telegram: ignore non-content message")
                return
            meta = _message_meta(update)
            if has_bot_command:
                meta["has_bot_command"] = True
            if is_bot_mentioned:
                meta["bot_mentioned"] = True
            chat_id = meta.get("chat_id", "")
            user = getattr(
                update.message or getattr(update, "edited_message"),
                "from_user",
                None,
            )
            sender_id = str(getattr(user, "id", "")) if user else chat_id
            is_group = meta.get("is_group", False)

            allowed, error_msg = self._check_allowlist(
                sender_id,
                is_group,
            )
            if not allowed:
                logger.info(
                    "telegram allowlist blocked: sender=%s is_group=%s",
                    sender_id,
                    is_group,
                )
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=error_msg,
                    )
                except Exception:
                    logger.debug(
                        "telegram reject failed chat_id=%s",
                        chat_id,
                    )
                return

            if not self._check_group_mention(is_group, meta):
                return

            native = {
                "channel_id": self.channel,
                "sender_id": sender_id,
                "content_parts": content_parts,
                "meta": meta,
            }
            if self._enqueue is not None:
                self._start_typing(chat_id)
                self._enqueue(native)
            else:
                logger.warning("telegram: _enqueue not set, message dropped")

        app.add_handler(MessageHandler(filters.ALL, handle_message))
        return app

    def _apply_no_text_debounce(
        self,
        session_id: str,
        content_parts: list[Any],
    ) -> tuple[bool, list[Any]]:
        """Process media-only Telegram messages without waiting for text."""
        has_media = any(
            getattr(part, "type", None)
            not in (ContentType.TEXT, ContentType.REFUSAL)
            for part in content_parts
        )
        if has_media:
            pending = self._pending_content_by_session.pop(session_id, [])
            return True, pending + list(content_parts)
        return super()._apply_no_text_debounce(session_id, content_parts)

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "TelegramChannel":
        import os

        allow_from_env = os.getenv("TELEGRAM_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("TELEGRAM_CHANNEL_ENABLED", "0") == "1",
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            http_proxy=os.getenv("TELEGRAM_HTTP_PROXY", ""),
            http_proxy_auth=os.getenv("TELEGRAM_HTTP_PROXY_AUTH", ""),
            bot_prefix=os.getenv("TELEGRAM_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
            show_typing=os.getenv("TELEGRAM_SHOW_TYPING", "1") == "1",
            dm_policy=os.getenv("TELEGRAM_DM_POLICY", "open"),
            group_policy=os.getenv("TELEGRAM_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("TELEGRAM_DENY_MESSAGE", ""),
            require_mention=os.getenv("TELEGRAM_REQUIRE_MENTION", "0") == "1",
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[TelegramChannelConfig, dict],
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
    ) -> "TelegramChannel":
        if isinstance(config, dict):
            c = config
        else:
            c = config.model_dump()

        def _get_str(key: str) -> str:
            return (c.get(key) or "").strip()

        show_typing = c.get("show_typing")
        if show_typing is None:
            show_typing = True

        return cls(
            process=process,
            enabled=bool(c.get("enabled", False)),
            bot_token=_get_str("bot_token"),
            http_proxy=_get_str("http_proxy"),
            http_proxy_auth=_get_str("http_proxy_auth"),
            bot_prefix=_get_str("bot_prefix"),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            workspace_dir=workspace_dir,
            show_typing=show_typing,
            dm_policy=c.get("dm_policy") or "open",
            group_policy=c.get("group_policy") or "open",
            allow_from=c.get("allow_from") or [],
            deny_message=c.get("deny_message") or "",
            require_mention=c.get("require_mention", False),
        )

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks under Telegram's message length limit."""
        if not text or len(text) <= TELEGRAM_SEND_CHUNK_SIZE:
            return [text] if text else []
        chunks: list[str] = []
        rest = text
        while rest:
            if len(rest) <= TELEGRAM_SEND_CHUNK_SIZE:
                chunks.append(rest)
                break
            chunk = rest[:TELEGRAM_SEND_CHUNK_SIZE]
            last_nl = chunk.rfind("\n")
            if last_nl > TELEGRAM_SEND_CHUNK_SIZE // 2:
                chunk = chunk[: last_nl + 1]
            else:
                last_space = chunk.rfind(" ")
                if last_space > TELEGRAM_SEND_CHUNK_SIZE // 2:
                    chunk = chunk[: last_space + 1]
            chunks.append(chunk)
            rest = rest[len(chunk) :].lstrip("\n ")
        return chunks

    async def _send_chat_action(
        self,
        chat_id: str,
        action: str = "typing",
    ) -> None:
        """Send chat action (typing, uploading_photo, etc.) to Telegram."""
        if not self.enabled or not self._application:
            return
        bot = self._application.bot
        if not bot:
            return
        try:
            await bot.send_chat_action(chat_id=chat_id, action=action)
        except Exception:
            logger.debug(
                "telegram send_chat_action failed for chat_id=%s",
                chat_id,
            )

    def _start_typing(self, chat_id: str) -> None:
        """Start the typing indicator loop for a chat."""
        if not self._show_typing:
            return
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(
            self._typing_loop(chat_id),
        )

    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send 'typing' action every 4s until cancelled."""
        try:
            deadline = asyncio.get_event_loop().time() + _TYPING_TIMEOUT_S
            while self._application:
                await self._send_chat_action(chat_id, "typing")
                await asyncio.sleep(4)
                if asyncio.get_event_loop().time() >= deadline:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if self._typing_tasks.get(chat_id) is asyncio.current_task():
                self._typing_tasks.pop(chat_id, None)

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        """Send text to chat_id (to_handle or meta['chat_id'])."""
        if not self.enabled or not self._application:
            return
        if meta is None:
            meta = {}
        chat_id = meta.get("chat_id") or to_handle
        if not chat_id:
            logger.warning("telegram send: no chat_id in to_handle or meta")
            return
        bot = self._application.bot
        if not bot:
            return
        message_thread_id = meta.get("message_thread_id")
        self._stop_typing(chat_id)
        chunks = self._chunk_text(text)
        for chunk in chunks:
            html_chunk = markdown_to_telegram_html(chunk)
            try:
                kwargs = {
                    "chat_id": chat_id,
                    "text": html_chunk,
                    "parse_mode": ParseMode.HTML,
                }
                if message_thread_id is not None:
                    kwargs["message_thread_id"] = message_thread_id
                await bot.send_message(**kwargs)
            except BadRequest as exc:
                logger.warning(
                    "telegram HTML send failed, trying plain text: %s",
                    exc,
                )
                try:
                    plain_chunk = html.unescape(
                        re.sub(r"<[^>]+>", "", html_chunk),
                    )
                    kwargs = {
                        "chat_id": chat_id,
                        "text": plain_chunk,
                    }
                    if message_thread_id is not None:
                        kwargs["message_thread_id"] = message_thread_id
                    await bot.send_message(**kwargs)
                except Exception:
                    logger.exception("telegram send_message fallback failed")
                    return
            except Exception:
                logger.exception("telegram send_message failed")
                return

    async def send_media(  # pylint: disable=too-many-statements
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        """Send a media part (image, video, audio, file) to chat_id."""
        if not self.enabled or not self._application:
            return
        meta = meta or {}
        chat_id = meta.get("chat_id") or to_handle
        if not chat_id:
            logger.warning(
                "telegram send_media: no chat_id in to_handle or meta",
            )
            return
        bot = self._application.bot
        if not bot:
            return
        message_thread_id = meta.get("message_thread_id")
        self._stop_typing(chat_id)

        part_type = getattr(part, "type", None)
        try:
            if part_type == ContentType.IMAGE:
                image_url = getattr(part, "image_url", None)
                await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=image_url,
                    method_name="send_photo",
                    payload_name="photo",
                    message_thread_id=message_thread_id,
                )
            elif part_type == ContentType.VIDEO:
                video_url = getattr(part, "video_url", None)
                await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=video_url,
                    method_name="send_video",
                    payload_name="video",
                    message_thread_id=message_thread_id,
                )
            elif part_type == ContentType.AUDIO:
                audio_data = getattr(part, "data", None)
                await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=audio_data,
                    method_name="send_audio",
                    payload_name="audio",
                    message_thread_id=message_thread_id,
                )
            elif part_type == ContentType.FILE:
                file_url = getattr(part, "file_url", None)
                await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=file_url,
                    method_name="send_document",
                    payload_name="document",
                    message_thread_id=message_thread_id,
                )
        except _FileTooLargeError as exc:
            logger.warning("telegram send_media: file too large: %s", exc)
            await self.send(to_handle, str(exc), meta)
        except _MediaFileUnavailableError as exc:
            logger.warning("telegram send_media: file unavailable: %s", exc)
            await self.send(to_handle, str(exc), meta)
        except BadRequest as exc:
            logger.warning("telegram send_media: bad request: %s", exc)
            await self.send(
                to_handle,
                f"Telegram rejected the file: {exc}",
                meta,
            )
        except TimedOut as exc:
            logger.warning("telegram send_media: timed out: %s", exc)
            await self.send(
                to_handle,
                "File upload timed out. "
                "The file may be too large (Telegram bot limit: 50 MB).",
                meta,
            )
        except RetryAfter as exc:
            logger.warning("telegram send_media: rate limited: %s", exc)
            await self.send(
                to_handle,
                f"Too many requests. Please try again later. ({exc})",
                meta,
            )
        except Forbidden as exc:
            logger.warning("telegram send_media: forbidden: %s", exc)
            await self.send(
                to_handle,
                "The bot does not have permission to send media in this chat.",
                meta,
            )
        except NetworkError as exc:
            logger.warning("telegram send_media: network error: %s", exc)
            await self.send(
                to_handle,
                "Network error. Failed to send file, please try again later.",
                meta,
            )
        except OSError as exc:
            logger.warning("telegram send_media: OS error: %s", exc)
            error_detail = str(exc) or repr(exc)
            await self.send(
                to_handle,
                f"Failed to read the file, cannot send ({error_detail}).",
                meta,
            )
        except Exception:
            logger.exception("telegram send_media failed")

    async def _send_media_value(
        self,
        *,
        bot: Any,
        chat_id: str,
        value: Any,
        method_name: str,
        payload_name: str,
        message_thread_id: Optional[int],
    ) -> None:
        """Send media from URL or local file path."""
        if not value:
            return
        if isinstance(value, str) and value.startswith("file://"):
            raw_path = file_url_to_local_path(value)
            if not raw_path:
                logger.warning(
                    "telegram: could not resolve file URL: %s",
                    value,
                )
                raise _MediaFileUnavailableError(
                    "Could not resolve media file from URL.",
                )
            local_path = Path(raw_path).resolve()
            allowed_root = (
                (self._workspace_dir / "media").resolve()
                if self._workspace_dir
                else (WORKING_DIR / "media").resolve()
            )
            if not local_path.is_relative_to(allowed_root):
                logger.error(
                    "telegram: blocked media outside allowed directory: %s",
                    local_path,
                )
                raise _MediaFileUnavailableError(
                    f"Media file outside allowed directory: {local_path.name}",
                )
            if not local_path.exists():
                logger.warning(
                    "telegram: media file not found at path: %s",
                    local_path,
                )
                raise _MediaFileUnavailableError(
                    f"Media file not found: {local_path.name}",
                )
            file_size = local_path.stat().st_size
            if file_size > TELEGRAM_MAX_FILE_SIZE_BYTES:
                file_size_mb = file_size / (1024 * 1024)
                raise _FileTooLargeError(
                    f"File too large to send via Telegram: {local_path.name} "
                    f"({file_size_mb:.1f} MB, Telegram bot limit: 50 MB)",
                )
            try:
                with open(local_path, "rb") as media_file:
                    await self._send_media_payload(
                        bot=bot,
                        chat_id=chat_id,
                        method_name=method_name,
                        payload_name=payload_name,
                        payload=media_file,
                        message_thread_id=message_thread_id,
                    )
            except OSError as exc:
                logger.warning(
                    "telegram: failed to open media file: %s: %s",
                    local_path,
                    exc,
                )
                raise
            return
        await self._send_media_payload(
            bot=bot,
            chat_id=chat_id,
            method_name=method_name,
            payload_name=payload_name,
            payload=value,
            message_thread_id=message_thread_id,
        )

    async def _send_media_payload(
        self,
        *,
        bot: Any,
        chat_id: str,
        method_name: str,
        payload_name: str,
        payload: Any,
        message_thread_id: Optional[int],
    ) -> None:
        """Send a prepared Telegram media payload."""
        if not payload:
            return
        kwargs = {
            "chat_id": chat_id,
            payload_name: payload,
        }
        if message_thread_id is not None:
            kwargs["message_thread_id"] = message_thread_id
        await getattr(bot, method_name)(**kwargs)

    async def _polling_cycle(self, app) -> None:
        """Run one polling lifecycle: init → poll → watchdog."""

        def _on_poll_error(exc) -> None:
            app.create_task(
                app.process_error(error=exc, update=None),
            )

        await app.initialize()

        commands = [
            BotCommand(
                command="start",
                description="Start a new conversation",
            ),
            BotCommand(
                command="new",
                description="Start a new conversation (clear memory)",
            ),
            BotCommand(
                command="compact",
                description="Compact conversation memory",
            ),
            BotCommand(
                command="clear",
                description="Clear conversation history",
            ),
            BotCommand(
                command="history",
                description="Show conversation history",
            ),
        ]
        try:
            await app.bot.set_my_commands(commands)
            logger.info(
                "telegram: registered %d bot commands",
                len(commands),
            )
        except Exception:
            logger.warning(
                "telegram: failed to register commands (non-fatal)",
            )

        await app.updater.start_polling(
            bootstrap_retries=-1,
            allowed_updates=["message", "edited_message"],
            error_callback=_on_poll_error,
        )
        await app.start()
        logger.info("telegram: polling started (receiving updates)")

        while getattr(app.updater, "running", False):
            await asyncio.sleep(_POLL_WATCHDOG_INTERVAL_S)

        logger.warning("telegram: updater stopped unexpectedly")

    @staticmethod
    async def _teardown_application(app) -> None:
        """Cleanly shut down a Telegram Application instance."""
        try:
            updater = getattr(app, "updater", None)
            if updater and getattr(updater, "running", False):
                await updater.stop()
            if getattr(app, "running", False):
                await app.stop()
            await app.shutdown()
        except Exception as exc:
            logger.debug("telegram teardown: %s", exc)

    async def _run_polling(self) -> None:
        """Run Telegram polling with automatic reconnection.

        Do not use run_polling() — it calls run_until_complete() and
        fails when the event loop is already running (FastAPI/uvicorn).
        """
        if not self.enabled or not self._bot_token:
            return

        delay = _RECONNECT_INITIAL_S
        while True:
            try:
                self._application = self._build_application()
                await self._polling_cycle(self._application)
                delay = _RECONNECT_INITIAL_S
            except asyncio.CancelledError:
                logger.debug("telegram: polling cancelled")
                raise
            except InvalidToken:
                logger.error(
                    "telegram: invalid bot token — not retrying",
                )
                return
            except Exception:
                logger.exception(
                    "telegram: polling failed (check token, network, "
                    "proxy; in China you may need TELEGRAM_HTTP_PROXY)",
                )
            finally:
                if self._application:
                    await self._teardown_application(
                        self._application,
                    )
                    self._application = None

            logger.info(
                "telegram: reconnecting in %.1fs",
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * _RECONNECT_FACTOR, _RECONNECT_MAX_S)

    async def start(self) -> None:
        if not self.enabled or not self._bot_token:
            logger.debug(
                "telegram: start() skipped (enabled=%s, token=%s)",
                self.enabled,
                "set" if self._bot_token else "empty",
            )
            return
        self._task = asyncio.create_task(
            self._run_polling(),
            name="telegram_polling",
        )
        logger.info("telegram: channel started (polling task created)")

    async def stop(self) -> None:
        if not self.enabled:
            return
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            self._task = None
        for cid in list(self._typing_tasks):
            self._stop_typing(cid)
        if self._application:
            await self._teardown_application(self._application)

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[dict] = None,
    ) -> str:
        """Session by chat_id (one session per chat)."""
        meta = channel_meta or {}
        chat_id = meta.get("chat_id")
        if chat_id:
            return f"telegram:{chat_id}"
        return f"telegram:{sender_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        """Send target is chat_id from meta or session_id suffix."""
        meta = getattr(request, "channel_meta", None) or {}
        chat_id = meta.get("chat_id")
        if chat_id:
            return str(chat_id)
        sid = getattr(request, "session_id", "")
        if sid.startswith("telegram:"):
            return sid.split(":", 1)[-1]
        return getattr(request, "user_id", "") or ""

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Build AgentRequest from Telegram native dict."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        user_id = str(meta.get("user_id") or sender_id)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.user_id = user_id
        request.channel_meta = meta
        return request

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Cron dispatch: use session_id suffix as chat_id."""
        if session_id.startswith("telegram:"):
            return session_id.split(":", 1)[-1]
        return user_id
