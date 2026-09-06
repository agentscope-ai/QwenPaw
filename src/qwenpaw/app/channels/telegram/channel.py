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
from typing import Any, Dict, Optional, Union

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

from qwenpaw.schemas import (
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
from ..renderer import ChannelDisplayConfig
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
_POLLING_STATUS_CHECK_INTERVAL_S = 15
_POLLING_NETWORK_RETRY_BASE_S = 5.0
_POLLING_NETWORK_RETRY_MAX_S = 60.0
# Worst-case client-side lifetime of an in-flight getUpdates request; the
# conflict backoff cap must exceed it so a stale poll is surely gone.
_GET_UPDATES_READ_TIMEOUT_S = 20
# Conflict backoff: start small (most conflicts are transient self-overlaps),
# escalate up to a cap above the worst-case old-connection lifetime.
_POLLING_CONFLICT_RETRY_BASE_S = 5.0
_POLLING_CONFLICT_RETRY_MAX_S = _GET_UPDATES_READ_TIMEOUT_S + 1.0
# Grace period after shutdown for the HTTP session to fully close.
_TEARDOWN_SETTLE_S = 0.5

_MEDIA_ATTRS: list[tuple[str, type, Any, str]] = [
    ("document", FileContent, ContentType.FILE, "file_url"),
    ("video", VideoContent, ContentType.VIDEO, "video_url"),
    ("voice", AudioContent, ContentType.AUDIO, "data"),
    ("audio", AudioContent, ContentType.AUDIO, "data"),
]

# Streaming: minimum interval between editMessageText calls (seconds).
# Telegram rate-limits edits to ~1 msg/s per chat; use 1.5s for safety.
_STREAM_EDIT_INTERVAL_S = 1.5
_STREAM_PLACEHOLDER = "⏳"

# Issue #7586: request-local cleanup tracking keys inside
# send_meta["_tg_stream"]. All lists hold Telegram message_ids (int).
# - "intermediate_ids": reasoning / tool call / tool result messages
# - "final_ids": final answer messages (single edit or chunked sends)
# Invariant: an id in final_ids is never deleted, even if it also
# appears in intermediate_ids.
_TG_COLLECT_KIND_KEY = "_tg_collect"
_TG_KIND_INTERMEDIATE = "intermediate"
_TG_KIND_FINAL = "final"

# MessageType values (as plain strings to avoid importing schemas here)
# for Issue #7586 cleanup classification. Exact-match only — never
# substring/fuzzy matching.
#
# intermediate (deleted on successful completion):
#   reasoning, plugin_call, plugin_call_output, function_call,
#   function_call_output, mcp_tool_call, mcp_tool_call_output, progress
# final / keep (never deleted):
#   message, result
# unknown / future enum values: KEEP (fail-safe — a message we cannot
# classify must never be deleted).
_TG_INTERMEDIATE_MESSAGE_TYPES = frozenset(
    {
        "reasoning",
        "plugin_call",
        "plugin_call_output",
        "function_call",
        "function_call_output",
        "mcp_tool_call",
        "mcp_tool_call_output",
        "progress",
    },
)
_TG_FINAL_MESSAGE_TYPES = frozenset(
    {
        "message",
        "result",
    },
)


class _FileTooLargeError(Exception):
    """Raised when a local media file exceeds Telegram's upload size limit."""


class _MediaFileUnavailableError(Exception):
    """Raised when a media file cannot be found or resolved."""


class _PollingReconnectRequested(Exception):
    """Raised when polling should be reconnected by the outer loop."""

    def __init__(self, reason: str, *, attempt: int, delay: float):
        super().__init__(reason)
        self.reason = reason
        self.attempt = attempt
        self.delay = delay


def _telegram_base_urls(base_url: str) -> tuple[str, str]:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return "", ""
    return f"{root}/bot", f"{root}/file/bot"


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
    base_url: str = "",
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
    _, base_file_url = _telegram_base_urls(base_url)
    base_file_url = base_file_url or "https://api.telegram.org/file/bot"
    return f"{base_file_url}{bot_token}/{file_path}"


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
    _STREAM_DELTA_MIN_INTERVAL_S = _STREAM_EDIT_INTERVAL_S
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
        media_dir: str = "",
        workspace_dir: Path | None = None,
        show_typing: bool = True,
        display_config: ChannelDisplayConfig | None = None,
        no_text_debounce: bool = True,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
        streaming_enabled: bool = False,
        access_control_dm: bool = False,
        access_control_group: bool = False,
        base_url: str = "",
        cleanup_intermediate: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            display_config=display_config,
            no_text_debounce=no_text_debounce,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
            streaming_enabled=streaming_enabled,
            access_control_dm=access_control_dm,
            access_control_group=access_control_group,
        )
        self.enabled = enabled
        self._bot_token = bot_token
        self._base_url = (base_url or "").strip().rstrip("/")
        self._http_proxy = http_proxy or ""
        self._http_proxy_auth = http_proxy_auth or ""
        self.bot_prefix = bot_prefix
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )
        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = _DEFAULT_MEDIA_DIR
        self._show_typing = show_typing
        # Issue #7586: optional cleanup of intermediate messages after the
        # final answer. Default False to preserve 2.2.x behavior.
        self._cleanup_intermediate = bool(cleanup_intermediate)
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._is_processing: dict[str, bool] = {}
        self._task: Optional[asyncio.Task] = None
        self._application = None
        self._polling_error_task: Optional[asyncio.Task] = None
        self._pending_reconnect_reason: Optional[str] = None
        self._pending_reconnect_attempt = 0
        self._pending_reconnect_delay_s = _RECONNECT_INITIAL_S
        self._polling_network_error_count = 0
        self._polling_conflict_count = 0
        # Set when a reconnect is requested so the polling watchdog exits
        # immediately instead of waiting out its status-check interval.
        self._reconnect_event = asyncio.Event()

        # Interactive card handler (tool-guard approval cards).
        from .cards.dispatcher import TelegramCardHandler

        self._card_handler = TelegramCardHandler(self)

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
            CallbackQueryHandler,
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
        base_url, base_file_url = _telegram_base_urls(self._base_url)
        if base_url:
            builder = builder.base_url(base_url).base_file_url(base_file_url)
        builder = builder.get_updates_read_timeout(_GET_UPDATES_READ_TIMEOUT_S)
        builder = builder.get_updates_connect_timeout(10)
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

            if not self._check_group_mention(is_group, meta):
                return

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

        # Inline keyboard callback handler (tool-guard approval buttons).
        async def handle_callback_query(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,  # noqa: ARG001
        ) -> None:
            del context  # required by PTB handler signature
            query = update.callback_query
            if query is None:
                return
            await self._card_handler.handle_callback_query(query)

        app.add_handler(CallbackQueryHandler(handle_callback_query))
        return app

    @staticmethod
    def _looks_like_polling_conflict(error: Exception) -> bool:
        """Return True for Telegram getUpdates conflict errors."""
        text = str(error).lower()
        return (
            error.__class__.__name__.lower() == "conflict"
            or "terminated by other getupdates request" in text
            or "another bot instance is running" in text
        )

    @staticmethod
    def _looks_like_network_error(error: Exception) -> bool:
        """Return True for transient polling transport errors."""
        if isinstance(error, (NetworkError, TimedOut, OSError)):
            return True
        return error.__class__.__name__.lower() == "connectionerror"

    def _plan_polling_reconnect(
        self,
        reason: str,
    ) -> tuple[int, float]:
        """Update retry state and return ``(attempt, delay_s)``."""
        if reason == "conflict":
            self._polling_conflict_count += 1
            self._polling_network_error_count = 0
            attempt = self._polling_conflict_count
            delay = min(
                _POLLING_CONFLICT_RETRY_BASE_S
                * (_RECONNECT_FACTOR ** (attempt - 1)),
                _POLLING_CONFLICT_RETRY_MAX_S,
            )
            return attempt, delay

        self._polling_network_error_count += 1
        self._polling_conflict_count = 0
        attempt = self._polling_network_error_count
        delay = min(
            _POLLING_NETWORK_RETRY_BASE_S * (2 ** (attempt - 1)),
            _POLLING_NETWORK_RETRY_MAX_S,
        )
        return attempt, delay

    def _reset_polling_reconnect_state(self) -> None:
        """Reset conflict/network retry counters after a clean reconnect."""
        self._polling_network_error_count = 0
        self._polling_conflict_count = 0

    async def _request_polling_reconnect(
        self,
        app: Any,
        *,
        reason: str,
        error: Exception,
    ) -> None:
        """Stop polling so the outer reconnect loop can rebuild it cleanly."""
        if self._pending_reconnect_reason:
            return
        attempt, delay = self._plan_polling_reconnect(reason)
        self._pending_reconnect_reason = reason
        self._pending_reconnect_attempt = attempt
        self._pending_reconnect_delay_s = delay
        logger.warning(
            "telegram: polling %s, requesting reconnect "
            "(attempt %d, next delay %.1fs): %s",
            reason,
            attempt,
            delay,
            error,
        )
        updater = getattr(app, "updater", None)
        if updater and getattr(updater, "running", False):
            try:
                await updater.stop()
            except Exception as stop_err:
                logger.debug(
                    "telegram: failed stopping updater after %s: %s",
                    reason,
                    stop_err,
                )
        # Wake the polling watchdog so the cycle exits without waiting out
        # its status-check interval.
        self._reconnect_event.set()

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
            base_url=os.getenv("TELEGRAM_BASE_URL", ""),
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
            cleanup_intermediate=os.getenv(
                "TELEGRAM_CLEANUP_INTERMEDIATE",
                "0",
            )
            == "1",
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[TelegramChannelConfig, dict],
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        no_text_debounce: bool = True,
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
            base_url=_get_str("base_url"),
            http_proxy=_get_str("http_proxy"),
            http_proxy_auth=_get_str("http_proxy_auth"),
            bot_prefix=_get_str("bot_prefix"),
            on_reply_sent=on_reply_sent,
            display_config=display_config
            or ChannelDisplayConfig.from_config(config),
            no_text_debounce=no_text_debounce,
            workspace_dir=workspace_dir,
            show_typing=show_typing,
            dm_policy=c.get("dm_policy") or "open",
            group_policy=c.get("group_policy") or "open",
            allow_from=c.get("allow_from") or [],
            deny_message=c.get("deny_message") or "",
            require_mention=c.get("require_mention", False),
            streaming_enabled=bool(c.get("streaming_enabled", False)),
            access_control_dm=bool(
                c.get("access_control_dm", False),
            ),
            access_control_group=bool(
                c.get("access_control_group", False),
            ),
            cleanup_intermediate=bool(
                c.get("cleanup_intermediate", False),
            ),
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
        """Send text to chat_id (to_handle or meta['chat_id']).

        When ``cleanup_intermediate`` is enabled and the caller set
        ``meta["_tg_collect"]`` to ``"intermediate"``/``"final"`` (Issue
        #7586), every successfully sent chunk message_id is recorded
        into the request-local ledger. Callers that don't set the marker
        (proactive sends, error notices, model-fallback notices) stay
        untracked and are never deleted. Return type stays ``None`` for
        backward compatibility.
        """
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
        if self._is_processing.get(to_handle, False):
            self._start_typing(chat_id)
        collect_kind = (
            meta.get(_TG_COLLECT_KIND_KEY)
            if isinstance(meta, dict) and self._cleanup_intermediate
            else None
        )
        if collect_kind not in (_TG_KIND_INTERMEDIATE, _TG_KIND_FINAL):
            collect_kind = None
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
                sent = await bot.send_message(**kwargs)
                if collect_kind is not None:
                    mid = getattr(sent, "message_id", None)
                    if mid is not None:
                        self._track_tg_message(meta, mid, collect_kind)
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
                    sent = await bot.send_message(**kwargs)
                    if collect_kind is not None:
                        mid = getattr(sent, "message_id", None)
                        if mid is not None:
                            self._track_tg_message(meta, mid, collect_kind)
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
        if self._is_processing.get(to_handle, False):
            self._start_typing(chat_id)

        # Issue #7586: media messages share the same round-kind marker as
        # text (set by on_event_message_completed / on_event_content /
        # on_streaming_end). Error fallback texts below must stay untracked.
        collect_kind = (
            meta.get(_TG_COLLECT_KIND_KEY)
            if isinstance(meta, dict) and self._cleanup_intermediate
            else None
        )
        if collect_kind not in (_TG_KIND_INTERMEDIATE, _TG_KIND_FINAL):
            collect_kind = None

        def _untracked_meta() -> dict:
            if not isinstance(meta, dict):
                return {}
            return {k: v for k, v in meta.items() if k != _TG_COLLECT_KIND_KEY}

        part_type = getattr(part, "type", None)
        try:
            if part_type == ContentType.IMAGE:
                image_url = getattr(part, "image_url", None)
                sent_mid = await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=image_url,
                    method_name="send_photo",
                    payload_name="photo",
                    message_thread_id=message_thread_id,
                )
                if collect_kind is not None and sent_mid is not None:
                    self._track_tg_message(meta, sent_mid, collect_kind)
            elif part_type == ContentType.VIDEO:
                video_url = getattr(part, "video_url", None)
                sent_mid = await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=video_url,
                    method_name="send_video",
                    payload_name="video",
                    message_thread_id=message_thread_id,
                )
                if collect_kind is not None and sent_mid is not None:
                    self._track_tg_message(meta, sent_mid, collect_kind)
            elif part_type == ContentType.AUDIO:
                audio_data = getattr(part, "data", None)
                sent_mid = await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=audio_data,
                    method_name="send_audio",
                    payload_name="audio",
                    message_thread_id=message_thread_id,
                )
                if collect_kind is not None and sent_mid is not None:
                    self._track_tg_message(meta, sent_mid, collect_kind)
            elif part_type == ContentType.FILE:
                file_url = getattr(part, "file_url", None)
                sent_mid = await self._send_media_value(
                    bot=bot,
                    chat_id=chat_id,
                    value=file_url,
                    method_name="send_document",
                    payload_name="document",
                    message_thread_id=message_thread_id,
                )
                if collect_kind is not None and sent_mid is not None:
                    self._track_tg_message(meta, sent_mid, collect_kind)
        except _FileTooLargeError as exc:
            logger.warning("telegram send_media: file too large: %s", exc)
            await self.send(to_handle, str(exc), _untracked_meta())
        except _MediaFileUnavailableError as exc:
            logger.warning("telegram send_media: file unavailable: %s", exc)
            await self.send(to_handle, str(exc), _untracked_meta())
        except BadRequest as exc:
            logger.warning("telegram send_media: bad request: %s", exc)
            await self.send(
                to_handle,
                f"Telegram rejected the file: {exc}",
                _untracked_meta(),
            )
        except TimedOut as exc:
            logger.warning("telegram send_media: timed out: %s", exc)
            await self.send(
                to_handle,
                "File upload timed out. "
                "The file may be too large (Telegram bot limit: 50 MB).",
                _untracked_meta(),
            )
        except RetryAfter as exc:
            logger.warning("telegram send_media: rate limited: %s", exc)
            await self.send(
                to_handle,
                f"Too many requests. Please try again later. ({exc})",
                _untracked_meta(),
            )
        except Forbidden as exc:
            logger.warning("telegram send_media: forbidden: %s", exc)
            await self.send(
                to_handle,
                "The bot does not have permission to send media in this chat.",
                _untracked_meta(),
            )
        except NetworkError as exc:
            logger.warning("telegram send_media: network error: %s", exc)
            await self.send(
                to_handle,
                "Network error. Failed to send file, please try again later.",
                _untracked_meta(),
            )
        except OSError as exc:
            logger.warning("telegram send_media: OS error: %s", exc)
            error_detail = str(exc) or repr(exc)
            await self.send(
                to_handle,
                f"Failed to read the file, cannot send ({error_detail}).",
                _untracked_meta(),
            )
        except Exception:
            logger.exception("telegram send_media failed")

    # ------------------------------------------------------------------
    # Streaming hooks — edit-in-place via Telegram editMessageText
    # ------------------------------------------------------------------

    def _get_stream_state(self, send_meta: Dict[str, Any]) -> Dict[str, Any]:
        """Get or create the per-request streaming state dict in send_meta.

        Besides the live ``message_ids`` placeholders, the state keeps
        two request-local ledgers for Issue #7586:

        - ``intermediate_ids``: reasoning / tool messages to delete
        - ``final_ids``: final answer messages to preserve
        """
        state = send_meta.get("_tg_stream")
        if state is None:
            state = {
                "message_ids": {},
                "intermediate_ids": [],
                "final_ids": [],
            }
            send_meta["_tg_stream"] = state
            return state
        # Backward compat: states created before #7586 only have
        # message_ids.
        state.setdefault("message_ids", {})
        state.setdefault("intermediate_ids", [])
        state.setdefault("final_ids", [])
        return state

    def _track_tg_message(
        self,
        send_meta: Optional[Dict[str, Any]],
        message_id: Any,
        kind: str,
    ) -> None:
        """Record one Telegram message_id as intermediate or final.

        No-op unless cleanup is enabled. ``send_meta`` is the same
        request-local dict threaded through the whole round, so concurrent
        requests never share ledgers.
        """
        if not self._cleanup_intermediate:
            return
        if not isinstance(send_meta, dict):
            return
        if kind not in (_TG_KIND_INTERMEDIATE, _TG_KIND_FINAL):
            return
        try:
            mid = int(message_id)
        except (TypeError, ValueError):
            return
        state = self._get_stream_state(send_meta)
        key = (
            "intermediate_ids"
            if kind == _TG_KIND_INTERMEDIATE
            else "final_ids"
        )
        ledger = state.get(key)
        if not isinstance(ledger, list):
            ledger = []
            state[key] = ledger
        if mid not in ledger:
            ledger.append(mid)

    def _track_tg_messages(
        self,
        send_meta: Optional[Dict[str, Any]],
        message_ids: Any,
        kind: str,
    ) -> None:
        if not message_ids:
            return
        if isinstance(message_ids, (list, tuple, set)):
            for mid in message_ids:
                self._track_tg_message(send_meta, mid, kind)
        else:
            self._track_tg_message(send_meta, message_ids, kind)

    @staticmethod
    def _classify_completed_event_kind(event: Any) -> str:
        """Classify a completed message event without guessing from text.

        Exact-match against the explicit whitelists above
        (``event.type`` as MessageType value or plain string):

        - intermediate: reasoning, the six tool call/output types, progress
        - final/keep: message, result
        - unknown / future / missing: KEEP (final) — fail-safe, we would
          rather leak an unclassifiable message than delete user content.
        """
        raw = getattr(event, "type", None)
        type_str = ""
        if raw is not None:
            type_str = raw.value if hasattr(raw, "value") else str(raw)
            type_str = (type_str or "").strip().lower()
        if type_str in _TG_INTERMEDIATE_MESSAGE_TYPES:
            return _TG_KIND_INTERMEDIATE
        # Both the explicit final whitelist and anything unrecognized
        # (including "") resolve to KEEP.
        return _TG_KIND_FINAL

    @staticmethod
    def _is_trackable_content_preview(event: Any) -> bool:
        """Whether an ``on_event_content`` event may produce a send.

        Mirrors the base-class send gate (``DATA`` + ``InProgress``) so
        the intermediate marker is only set when a tool-preview message
        can actually be emitted. ``Completed`` DATA, unknown content
        types and future statuses stay unmarked → always kept.
        """
        raw_type = getattr(event, "type", None)
        if raw_type is None:
            return False
        type_str = (
            raw_type.value if hasattr(raw_type, "value") else str(raw_type)
        )
        if (type_str or "").strip().lower() != "data":
            return False
        raw_status = getattr(event, "status", None)
        if raw_status is None:
            return False
        status_str = (
            raw_status.value
            if hasattr(raw_status, "value")
            else str(raw_status)
        )
        return (status_str or "").strip().lower() == "in_progress"

    async def _cleanup_intermediate_messages(
        self,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Best-effort delete of this round's intermediate messages.

        Only called on successful completion. Never raises: cleanup
        failures must not fail the final answer.
        """
        try:
            if not self._cleanup_intermediate:
                return
            if not isinstance(send_meta, dict):
                return
            state = send_meta.get("_tg_stream")
            if not isinstance(state, dict):
                return
            intermediate = state.get("intermediate_ids") or []
            final = state.get("final_ids") or []
            if not intermediate:
                return
            final_set = set()
            for mid in final:
                try:
                    final_set.add(int(mid))
                except (TypeError, ValueError):
                    continue
            chat_id = send_meta.get("chat_id") or to_handle
            if not chat_id:
                return
            seen: set[int] = set()
            for raw_mid in intermediate:
                try:
                    mid = int(raw_mid)
                except (TypeError, ValueError):
                    continue
                if mid in seen or mid in final_set:
                    continue
                seen.add(mid)
                try:
                    await self._delete_message(chat_id, mid)
                except Exception:
                    # _delete_message is already best-effort; keep going.
                    continue
        except Exception:
            logger.debug(
                "telegram: intermediate cleanup failed (non-fatal)",
                exc_info=True,
            )

    async def _send_placeholder(
        self,
        chat_id: str,
        message_thread_id: Optional[int],
        stream_type: str,
    ) -> Optional[int]:
        """Send a placeholder message and return its message_id."""
        if not self._application:
            return None
        bot = self._application.bot
        if not bot:
            return None
        prefix = "💭 " if stream_type == "reasoning" else ""
        try:
            kwargs: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": f"{prefix}{_STREAM_PLACEHOLDER}",
            }
            if message_thread_id is not None:
                kwargs["message_thread_id"] = message_thread_id
            msg = await bot.send_message(**kwargs)
            return msg.message_id
        except Exception:
            logger.debug(
                "telegram: failed to send streaming placeholder to %s",
                chat_id,
            )
            return None

    async def _edit_stream_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        *,
        use_html: bool = False,
    ) -> bool:
        """Edit an existing message; return True on success."""
        bot = (
            getattr(self._application, "bot", None)
            if self._application
            else None
        )
        if not bot:
            return False
        # Telegram rejects empty text
        if not text.strip():
            text = _STREAM_PLACEHOLDER
        try:
            kwargs: Dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
            }
            if use_html:
                kwargs["parse_mode"] = ParseMode.HTML
            await bot.edit_message_text(**kwargs)
            return True
        except BadRequest as exc:
            # "Message is not modified" is benign (text unchanged)
            if "not modified" in str(exc).lower():
                return True
            if use_html:
                # Fallback: strip HTML tags and retry as plain text
                logger.debug(
                    "telegram: HTML edit failed, retrying plain: %s",
                    exc,
                )
                plain_text = html.unescape(re.sub(r"<[^>]+>", "", text))
                return await self._edit_stream_message(
                    chat_id,
                    message_id,
                    plain_text,
                    use_html=False,
                )
            logger.debug("telegram: edit_message_text failed: %s", exc)
            return False
        except Exception:
            logger.debug(
                "telegram: edit_message_text error chat=%s msg=%s",
                chat_id,
                message_id,
            )
            return False

    async def _delete_message(self, chat_id: str, message_id: int) -> None:
        """Delete a Telegram message (best effort)."""
        if not self._application:
            return
        bot = self._application.bot
        if not bot:
            return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.debug(
                "telegram: delete_message failed chat=%s msg=%s",
                chat_id,
                message_id,
            )

    async def on_streaming_start(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Send a placeholder message for the new streaming segment."""
        chat_id = send_meta.get("chat_id") or to_handle
        if not chat_id:
            return
        message_thread_id = send_meta.get("message_thread_id")
        state = self._get_stream_state(send_meta)
        msg_id = await self._send_placeholder(
            chat_id,
            message_thread_id,
            stream_type,
        )
        if msg_id:
            state["message_ids"][stream_type] = msg_id

    async def on_streaming_delta(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Plain-text edit to show incremental progress."""
        state = self._get_stream_state(send_meta)
        msg_id = state["message_ids"].get(stream_type)
        if not msg_id:
            return
        chat_id = send_meta.get("chat_id") or to_handle
        if not chat_id:
            return
        prefix = "💭 " if stream_type == "reasoning" else ""
        display_text = (
            f"{prefix}{accumulated_text}" if prefix else accumulated_text
        )
        # If text exceeds Telegram limit, show only the tail portion
        if len(display_text) > TELEGRAM_MAX_MESSAGE_LENGTH:
            display_text = (
                "..." + display_text[-(TELEGRAM_MAX_MESSAGE_LENGTH - 4) :]
            )
        await self._edit_stream_message(
            chat_id,
            msg_id,
            display_text,
            use_html=False,
        )

    async def on_streaming_end(
        self,
        request: Any,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Final edit with full Markdown→HTML rendering.

        If the final text exceeds Telegram's 4096-char limit, delete the
        placeholder and fall back to the normal chunked send path.

        Issue #7586: when cleanup is enabled, the finished placeholder id
        (single-message path) or the chunked send ids (long path) are
        recorded as intermediate (reasoning) or final (message). Reasoning
        is never deleted here — cleanup happens once at successful
        process completion so users can still watch it while answering.
        """
        state = self._get_stream_state(send_meta)
        msg_id = state["message_ids"].pop(stream_type, None)
        chat_id = send_meta.get("chat_id") or to_handle
        if not chat_id:
            return
        prefix = "💭 " if stream_type == "reasoning" else ""
        final_text = (
            f"{prefix}{accumulated_text}" if prefix else accumulated_text
        )
        stream_kind = (
            _TG_KIND_INTERMEDIATE
            if stream_type == "reasoning"
            else _TG_KIND_FINAL
        )

        # If placeholder was never sent (e.g. API error), fall back to
        # normal send so the reply is not silently lost.
        if not msg_id:
            if self._cleanup_intermediate and final_text.strip():
                send_meta[_TG_COLLECT_KIND_KEY] = stream_kind
                try:
                    await self.send(to_handle, final_text, send_meta)
                finally:
                    send_meta.pop(_TG_COLLECT_KIND_KEY, None)
            else:
                await self.send(to_handle, final_text, send_meta)
            return
        if len(final_text) <= TELEGRAM_SEND_CHUNK_SIZE:
            # Text fits in a single message — edit in place.
            html_text = markdown_to_telegram_html(final_text)
            success = await self._edit_stream_message(
                chat_id,
                msg_id,
                html_text,
                use_html=True,
            )
            if not success:
                await self._edit_stream_message(
                    chat_id,
                    msg_id,
                    final_text,
                    use_html=False,
                )
            # Record after the final edit (even if the edit failed, the
            # placeholder message itself still exists and belongs to
            # this round's ledger).
            if self._cleanup_intermediate:
                self._track_tg_message(send_meta, msg_id, stream_kind)
        else:
            # Text too long for a single edit — delete placeholder and
            # use the normal chunked send path (same as non-streaming).
            await self._delete_message(chat_id, msg_id)
            if self._cleanup_intermediate:
                send_meta[_TG_COLLECT_KIND_KEY] = stream_kind
                try:
                    await self.send(to_handle, final_text, send_meta)
                finally:
                    send_meta.pop(_TG_COLLECT_KIND_KEY, None)
            else:
                await self.send(to_handle, final_text, send_meta)

    # ------------------------------------------------------------------
    # Event hooks
    # ------------------------------------------------------------------

    async def on_event_content(
        self,
        request,
        to_handle: str,
        event,
        send_meta: dict,
    ) -> bool:
        """Track DATA/InProgress tool previews as intermediate (Issue #7586).

        The marker is only set for events that can actually emit a send
        (DATA + InProgress). Completed DATA, unknown/future content and
        anything the base class would not send stay unmarked → kept.
        Fail-safe: rather leak than delete unclassifiable content.
        """
        if not self._cleanup_intermediate:
            return await super().on_event_content(
                request,
                to_handle,
                event,
                send_meta,
            )
        if not self._is_trackable_content_preview(event):
            return await super().on_event_content(
                request,
                to_handle,
                event,
                send_meta,
            )
        send_meta[_TG_COLLECT_KIND_KEY] = _TG_KIND_INTERMEDIATE
        try:
            return await super().on_event_content(
                request,
                to_handle,
                event,
                send_meta,
            )
        finally:
            if isinstance(send_meta, dict):
                send_meta.pop(_TG_COLLECT_KIND_KEY, None)

    async def on_event_message_completed(
        self,
        request,
        to_handle: str,
        event,
        send_meta: dict,
    ) -> None:
        """Render card-flagged events via the card handler; else default.

        Issue #7586: card events (e.g. tool-guard approval) return early
        and stay untracked so approval UX is never deleted. All other
        completed messages are classified from ``event.type`` (never from
        emoji/text) and their ``send()``/``send_media()`` outputs are
        recorded as intermediate (tool/reasoning) or final (message).
        """
        if await self._card_handler.try_send_card_for_event(
            to_handle,
            event,
            send_meta,
        ):
            # Re-start typing after sending, in case more tool calls follow.
            if self._is_processing.get(to_handle, False):
                self._start_typing(to_handle)
            return
        if not self._cleanup_intermediate:
            await super().on_event_message_completed(
                request,
                to_handle,
                event,
                send_meta,
            )
        else:
            kind = self._classify_completed_event_kind(event)
            if isinstance(send_meta, dict):
                send_meta[_TG_COLLECT_KIND_KEY] = kind
            try:
                await super().on_event_message_completed(
                    request,
                    to_handle,
                    event,
                    send_meta,
                )
            finally:
                if isinstance(send_meta, dict):
                    send_meta.pop(_TG_COLLECT_KIND_KEY, None)
        # Re-start typing after sending, in case more tool calls follow.
        if self._is_processing.get(to_handle, False):
            self._start_typing(to_handle)

    async def _before_consume_process(
        self,
        request: Any,
    ) -> None:
        """Start typing indicator when processing actually begins.

        Called after the no-text debounce check passes, so the typing
        indicator only starts for messages that will be processed — not
        for file-only messages buffered while waiting for text input.
        """
        to_handle = self.get_to_handle_from_request(request)
        self._is_processing[to_handle] = True
        self._start_typing(to_handle)

    async def _on_process_completed(
        self,
        request,
        to_handle: str,
        send_meta: dict,
    ) -> None:
        """All events done — cleanup intermediates, clear flag, stop typing.

        Issue #7586: on success only, best-effort delete this round's
        intermediate messages (reasoning / tool calls / results) while
        preserving every final answer id. Cleanup failures never fail
        the round; typing/processing state is always cleared. Error and
        cancellation paths deliberately do no cleanup (field preserved).
        """
        try:
            if self._cleanup_intermediate:
                await self._cleanup_intermediate_messages(
                    to_handle,
                    send_meta,
                )
        finally:
            self._is_processing.pop(to_handle, None)
            self._stop_typing(to_handle)

    async def _on_consume_error(
        self,
        request,
        to_handle: str,
        err_text: str,
    ) -> None:
        """Error or cancellation — clear processing flag and stop typing."""
        self._is_processing.pop(to_handle, None)
        self._stop_typing(to_handle)
        await super()._on_consume_error(request, to_handle, err_text)

    async def _consume_with_tracker(
        self,
        request,
        payload,
    ) -> None:
        """Wrap parent to ensure typing cleanup on cancellation."""
        to_handle = self.get_to_handle_from_request(request)
        try:
            await super()._consume_with_tracker(request, payload)
        except asyncio.CancelledError:
            self._is_processing.pop(to_handle, None)
            self._stop_typing(to_handle)
            raise

    async def _send_media_value(
        self,
        *,
        bot: Any,
        chat_id: str,
        value: Any,
        method_name: str,
        payload_name: str,
        message_thread_id: Optional[int],
    ) -> Optional[int]:
        """Send media from URL or local file path; return message_id."""
        if not value:
            return None
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
                    return await self._send_media_payload(
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
            return None
        return await self._send_media_payload(
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
    ) -> Optional[int]:
        """Send a prepared Telegram media payload; return message_id."""
        if not payload:
            return None
        kwargs = {
            "chat_id": chat_id,
            payload_name: payload,
        }
        if message_thread_id is not None:
            kwargs["message_thread_id"] = message_thread_id
        sent = await getattr(bot, method_name)(**kwargs)
        mid = getattr(sent, "message_id", None)
        try:
            return int(mid) if mid is not None else None
        except (TypeError, ValueError):
            return None

    async def _polling_cycle(self, app) -> None:
        """Run one polling lifecycle: init → poll → watchdog."""

        self._pending_reconnect_reason = None
        self._pending_reconnect_attempt = 0
        self._pending_reconnect_delay_s = _RECONNECT_INITIAL_S
        self._polling_error_task = None
        self._reconnect_event.clear()

        def _on_poll_error(exc) -> None:
            if (
                self._polling_error_task
                and not self._polling_error_task.done()
            ):
                return
            if self._looks_like_polling_conflict(exc):
                self._polling_error_task = app.create_task(
                    self._request_polling_reconnect(
                        app,
                        reason="conflict",
                        error=exc,
                    ),
                )
            elif self._looks_like_network_error(exc):
                self._polling_error_task = app.create_task(
                    self._request_polling_reconnect(
                        app,
                        reason="network error",
                        error=exc,
                    ),
                )
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
            BotCommand(
                command="model",
                description="Show or switch AI model",
            ),
            BotCommand(
                command="stop",
                description="Stop the current task",
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
            bootstrap_retries=0,
            allowed_updates=["message", "edited_message", "callback_query"],
            error_callback=_on_poll_error,
        )
        await app.start()
        self._reset_polling_reconnect_state()
        logger.info("telegram: polling started (receiving updates)")

        while getattr(app.updater, "running", False):
            try:
                await asyncio.wait_for(
                    self._reconnect_event.wait(),
                    timeout=_POLLING_STATUS_CHECK_INTERVAL_S,
                )
            except asyncio.TimeoutError:
                continue
            else:
                break

        if self._polling_error_task:
            try:
                await self._polling_error_task
            except Exception:
                logger.debug(
                    "telegram: polling error task failed",
                    exc_info=True,
                )
            finally:
                self._polling_error_task = None

        if self._pending_reconnect_reason:
            reason = self._pending_reconnect_reason
            attempt = self._pending_reconnect_attempt
            delay = self._pending_reconnect_delay_s
            self._pending_reconnect_reason = None
            self._pending_reconnect_attempt = 0
            self._pending_reconnect_delay_s = _RECONNECT_INITIAL_S
            raise _PollingReconnectRequested(
                reason,
                attempt=attempt,
                delay=delay,
            )

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
            # Give the closed HTTP session and Telegram's server side a brief
            # moment to release the old getUpdates connection.
            await asyncio.sleep(_TEARDOWN_SETTLE_S)
        except Exception as exc:
            # CancelledError is BaseException, so it propagates and is not
            # swallowed here (keeps stop()'s cancellation working).
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
            except _PollingReconnectRequested as exc:
                logger.warning(
                    "telegram: polling reconnect requested (%s, attempt %d); "
                    "reconnecting in %.1fs",
                    exc.reason,
                    exc.attempt,
                    exc.delay,
                )
                delay = exc.delay
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

    async def health_check(self) -> Dict[str, Any]:
        """Check Telegram polling task status."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "Telegram channel is disabled.",
            }
        if not self._bot_token:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "Telegram bot token is not configured.",
            }
        task_alive = self._task is not None and not self._task.done()
        if not task_alive:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "Telegram polling task is not running.",
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": "Telegram polling task is running.",
        }

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
        self._is_processing.clear()
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
