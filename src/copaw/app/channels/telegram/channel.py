# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Telegram channel: Bot API with polling; receive/send via chat_id."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Union

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ....config.config import TelegramConfig as TelegramChannelConfig
from ..base import BaseChannel, OnReplySent, ProcessHandler

logger = logging.getLogger(__name__)

# Telegram Bot API limit for one message (characters).
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
# Chunk slightly under to avoid encoding/entity edge cases.
TELEGRAM_SEND_CHUNK_SIZE = 4000


async def _resolve_telegram_file_url(
    *,
    bot: Any,
    file_id: str,
    bot_token: str,
) -> Optional[str]:
    """Resolve Telegram file_id into a downloadable URL."""
    try:
        tg_file = await bot.get_file(file_id)
    except Exception:
        logger.exception("telegram: get_file failed for file_id=%s", file_id)
        return None

    file_path = (getattr(tg_file, "file_path", None) or "").strip()
    if not file_path:
        return None
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    return f"https://api.telegram.org/file/bot{bot_token}/{file_path.lstrip('/')}"


async def _build_content_parts_from_message(
    update: Any,
    *,
    bot: Any,
    bot_token: str,
) -> list:
    """Build runtime content_parts from Telegram message (text, photo, doc, etc.)."""
    message = getattr(update, "message", None) or getattr(update, "edited_message")
    if not message:
        return [TextContent(type=ContentType.TEXT, text="")]

    content_parts = []
    text = (getattr(message, "text", None) or getattr(message, "caption") or "").strip()
    if text:
        content_parts.append(TextContent(type=ContentType.TEXT, text=text))

    # Photo: list of PhotoSize, take largest
    photo = getattr(message, "photo", None)
    if photo and len(photo) > 0:
        largest = photo[-1]
        file_id = getattr(largest, "file_id", None)
        if file_id:
            file_url = await _resolve_telegram_file_url(
                bot=bot,
                file_id=file_id,
                bot_token=bot_token,
            )
            content_parts.append(
                ImageContent(
                    type=ContentType.IMAGE,
                    image_url=file_url or f"tg://file_id/{file_id}",
                ),
            )

    # Document, audio, video, voice
    doc = getattr(message, "document", None)
    if doc:
        file_id = getattr(doc, "file_id", None)
        if file_id:
            file_url = await _resolve_telegram_file_url(
                bot=bot,
                file_id=file_id,
                bot_token=bot_token,
            )
            content_parts.append(
                FileContent(
                    type=ContentType.FILE,
                    file_url=file_url or f"tg://file_id/{file_id}",
                ),
            )

    video = getattr(message, "video", None)
    if video:
        file_id = getattr(video, "file_id", None)
        if file_id:
            file_url = await _resolve_telegram_file_url(
                bot=bot,
                file_id=file_id,
                bot_token=bot_token,
            )
            content_parts.append(
                VideoContent(
                    type=ContentType.VIDEO,
                    video_url=file_url or f"tg://file_id/{file_id}",
                ),
            )

    voice = getattr(message, "voice", None)
    if voice:
        file_id = getattr(voice, "file_id", None)
        if file_id:
            file_url = await _resolve_telegram_file_url(
                bot=bot,
                file_id=file_id,
                bot_token=bot_token,
            )
            content_parts.append(
                AudioContent(
                    type=ContentType.AUDIO,
                    data=file_url or f"tg://file_id/{file_id}",
                ),
            )

    audio = getattr(message, "audio", None)
    if audio:
        file_id = getattr(audio, "file_id", None)
        if file_id:
            file_url = await _resolve_telegram_file_url(
                bot=bot,
                file_id=file_id,
                bot_token=bot_token,
            )
            content_parts.append(
                AudioContent(
                    type=ContentType.AUDIO,
                    data=file_url or f"tg://file_id/{file_id}",
                ),
            )

    if not content_parts:
        content_parts.append(TextContent(type=ContentType.TEXT, text=""))

    return content_parts


def _message_meta(update: Any) -> dict:
    """Extract chat_id, user_id, etc. from Telegram update."""
    message = getattr(update, "message", None) or getattr(update, "edited_message")
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
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )
        self.enabled = enabled
        self._bot_token = bot_token
        self._http_proxy = http_proxy or ""
        self._http_proxy_auth = http_proxy_auth or ""
        self.bot_prefix = bot_prefix
        self._task: Optional[asyncio.Task] = None
        self._application = None
        if self.enabled and self._bot_token:
            try:
                self._application = self._build_application()
                logger.info(
                    "telegram: channel initialized (enabled=True, token set, polling will start on start())"
                )
            except Exception:
                logger.exception(
                    "telegram: failed to build application (check bot_token and proxy)"
                )
                self._application = None
        else:
            if self.enabled and not self._bot_token:
                logger.info(
                    "telegram: channel disabled for this run (bot_token empty; set in config or TELEGRAM_BOT_TOKEN)"
                )
            elif not self.enabled:
                logger.debug("telegram: channel disabled (enabled=false in config)")

    def _build_application(self):
        from telegram import Update
        from telegram.ext import Application, ContextTypes, MessageHandler, filters

        def proxy_url() -> Optional[str]:
            if not self._http_proxy:
                return None
            if self._http_proxy_auth:
                if "://" in self._http_proxy:
                    prefix, rest = self._http_proxy.split("://", 1)
                    return f"{prefix}://{self._http_proxy_auth}@{rest}"
                return f"http://{self._http_proxy_auth}@{self._http_proxy}"
            return self._http_proxy

        builder = (
            Application.builder()
            .token(self._bot_token)
        )
        proxy = proxy_url()
        if proxy:
            builder = builder.proxy(proxy).get_updates_proxy(proxy)

        app = builder.build()

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message and not getattr(update, "edited_message", None):
                return
            content_parts = await _build_content_parts_from_message(
                update,
                bot=context.bot,
                bot_token=self._bot_token,
            )
            meta = _message_meta(update)
            chat_id = meta.get("chat_id", "")
            user = getattr(update.message or getattr(update, "edited_message"), "from_user", None)
            sender_id = str(getattr(user, "id", "")) if user else chat_id
            native = {
                "channel_id": self.channel,
                "sender_id": sender_id,
                "content_parts": content_parts,
                "meta": meta,
            }
            if self._enqueue is not None:
                self._enqueue(native)
            else:
                logger.warning("telegram: _enqueue not set, message dropped")

        app.add_handler(MessageHandler(filters.ALL, handle_message))
        return app

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "TelegramChannel":
        import os
        return cls(
            process=process,
            enabled=os.getenv("TELEGRAM_CHANNEL_ENABLED", "0") == "1",
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            http_proxy=os.getenv("TELEGRAM_HTTP_PROXY", ""),
            http_proxy_auth=os.getenv("TELEGRAM_HTTP_PROXY_AUTH", ""),
            bot_prefix=os.getenv("TELEGRAM_BOT_PREFIX", "[Bot] "),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[TelegramChannelConfig, dict],
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ) -> "TelegramChannel":
        if isinstance(config, dict):
            return cls(
                process=process,
                enabled=bool(config.get("enabled", False)),
                bot_token=(config.get("bot_token") or "").strip(),
                http_proxy=(config.get("http_proxy") or "").strip(),
                http_proxy_auth=(config.get("http_proxy_auth") or "").strip(),
                bot_prefix=(config.get("bot_prefix") or "[Bot] ").strip(),
                on_reply_sent=on_reply_sent,
                show_tool_details=show_tool_details,
            )
        return cls(
            process=process,
            enabled=config.enabled,
            bot_token=config.bot_token or "",
            http_proxy=config.http_proxy or "",
            http_proxy_auth=config.http_proxy_auth or "",
            bot_prefix=config.bot_prefix or "[Bot] ",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
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

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        """Send text to chat_id (to_handle or meta['chat_id']). Splits long messages."""
        if not self.enabled or not self._application:
            return
        meta = meta or {}
        chat_id = meta.get("chat_id") or to_handle
        if not chat_id:
            logger.warning("telegram send: no chat_id in to_handle or meta")
            return
        bot = self._application.bot
        if not bot:
            return
        chunks = self._chunk_text(text)
        for chunk in chunks:
            try:
                await bot.send_message(chat_id=chat_id, text=chunk)
            except Exception:
                logger.exception("telegram send_message failed")
                return

    async def _run_polling(self) -> None:
        """Run Telegram bot in existing event loop (FastAPI/uvicorn).
        Do not use run_polling() - it calls run_until_complete() and fails when
        the event loop is already running.
        """
        if not self.enabled or not self._application or not self._bot_token:
            return
        try:
            from telegram.error import TelegramError

            def _on_poll_error(exc: TelegramError) -> None:
                self._application.create_task(
                    self._application.process_error(error=exc, update=None),
                )

            await self._application.initialize()
            await self._application.updater.start_polling(
                allowed_updates=["message", "edited_message"],
                error_callback=_on_poll_error,
            )
            await self._application.start()
            logger.info("telegram: polling started (receiving updates)")
            await asyncio.Future()  # never completes until cancelled
        except asyncio.CancelledError:
            logger.debug("telegram: polling cancelled")
            raise
        except Exception:
            logger.exception(
                "telegram: polling error (check token, network, proxy; "
                "in China you may need TELEGRAM_HTTP_PROXY)"
            )
            raise

    async def start(self) -> None:
        if not self.enabled or not self._application:
            logger.debug(
                "telegram: start() skipped (enabled=%s, application=%s)",
                self.enabled,
                "built" if self._application else "not built",
            )
            return
        self._task = asyncio.create_task(self._run_polling(), name="telegram_polling")
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
        if self._application:
            try:
                updater = getattr(self._application, "updater", None)
                if updater and getattr(updater, "running", False):
                    await updater.stop()
                if getattr(self._application, "running", False):
                    await self._application.stop()
                await self._application.shutdown()
            except Exception as exc:
                logger.debug("telegram stop: %s", exc)

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
