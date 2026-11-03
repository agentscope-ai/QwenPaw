# -*- coding: utf-8 -*-
"""Native PTB algorithms, media and response-owned effects."""

from __future__ import annotations
import asyncio
from collections import OrderedDict
import html
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse
import uuid
import httpx
from telegram import Audio, BotCommand, Document, InputFile, PhotoSize, Video
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    EndPointNotFound,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TimedOut,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest
from qwenpaw.schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)
from qwenpaw.app.channels.utils import (
    MediaDataError,
    data_url_filename,
    file_url_to_local_path,
    parse_data_url_async,
)
from qwenpaw.channel_protocol.models import ContentSource
from .format_html import markdown_to_telegram_html
from .errors import TelegramDeliveryError

logger = logging.getLogger(__name__)
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_SEND_CHUNK_SIZE = 4000
TELEGRAM_RICH_MESSAGE_MAX_BYTES = 32768
TELEGRAM_RICH_TABLE_MAX_COLUMNS = 20
TELEGRAM_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
_GET_UPDATES_READ_TIMEOUT_S = 20
_POLLING_CONFLICT_RETRY_MAX_S = 31
_STREAM_EDIT_INTERVAL_S = 1.5
_STREAM_PLACEHOLDER = "⏳"
_MEDIA_ATTRS = [
    ("document", FileContent, ContentType.FILE, "file_url"),
    ("video", VideoContent, ContentType.VIDEO, "video_url"),
    ("voice", AudioContent, ContentType.AUDIO, "data"),
    ("audio", AudioContent, ContentType.AUDIO, "data"),
]


class _FileTooLargeError(Exception):
    pass


class _MediaFileUnavailableError(Exception):
    pass


def _can_send_rich_message(text: str) -> bool:
    """Check size and table candidates; leave Markdown parsing to Telegram."""
    if (
        len(text) > TELEGRAM_RICH_MESSAGE_MAX_BYTES
        or "|" not in text
        or "\n" not in text
        or len(text.encode("utf-8")) > TELEGRAM_RICH_MESSAGE_MAX_BYTES
    ):
        return False

    fence = ""
    previous = ""
    has_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if fence:
            if stripped.startswith(fence) and not stripped.strip(fence[0]):
                fence = ""
            continue
        if stripped.startswith(("```", "~~~")):
            marker = stripped[0]
            fence = marker * (len(stripped) - len(stripped.lstrip(marker)))
            previous = ""
            continue

        # Only recognize delimiter rows; do not parse inline Markdown.
        if "|" in previous and "|" in stripped:
            cells = stripped.removeprefix("|").removesuffix("|").split("|")
            if all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells):
                if len(cells) > TELEGRAM_RICH_TABLE_MAX_COLUMNS:
                    return False
                has_table = True
        previous = stripped
    return has_table


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
        if file_path and not file_path.startswith(("http://", "https://")):
            source = Path(file_path).resolve()
            if not source.is_relative_to(media_dir.parent.resolve()):
                raise TelegramDeliveryError("MEDIA_PATH_UNAUTHORIZED")
        elif file_path:
            allowed = urlparse(bot.base_file_url)
            actual = urlparse(file_path)
            if (actual.scheme, actual.netloc) != (
                allowed.scheme,
                allowed.netloc,
            ):
                raise TelegramDeliveryError("MEDIA_URL_UNAUTHORIZED")
        if file_path:
            suffix = Path(file_path).suffix
        if filename_hint and not suffix:
            suffix = Path(filename_hint).suffix
        local_name = f"{uuid.uuid4().hex[:12]}{suffix or '.bin'}"
        local_path = media_dir / local_name
        await tg_file.download_to_drive(str(local_path))
        return str(local_path)
    except TelegramDeliveryError:
        logger.warning("Telegram rejected an unauthorized inbound media path")
        return None
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
    raw_text = (
        getattr(message, "text", None) or getattr(message, "caption") or ""
    )
    text = raw_text.strip()

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
                start, end = offset * 2, (offset + length) * 2
                mentioned = raw_text.encode("utf-16-le")[start:end].decode(
                    "utf-16-le",
                    errors="replace",
                )
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


def _chunk_text(text: str) -> list[str]:
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
        consumed = len(chunk)
        rest = rest[consumed:].lstrip("\n ")
    return chunks


def _utf16_units(text):
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def _api_chunks(text):
    """Retain legacy boundaries while respecting Bot API UTF-16 limits."""
    for chunk in _chunk_text(text):
        start, units = 0, 0
        for index, char in enumerate(chunk):
            size = 2 if ord(char) > 0xFFFF else 1
            if units + size > TELEGRAM_SEND_CHUNK_SIZE:
                yield chunk[start:index]
                start, units = index, 0
            units += size
        yield chunk[start:]


def _api_tail(text, max_units):
    units = 0
    for index in range(len(text) - 1, -1, -1):
        units += 2 if ord(text[index]) > 0xFFFF else 1
        if units > max_units:
            start = index + 1
            return text[start:]
    return text


class _ObservedResponseStream(httpx.AsyncByteStream):
    """Delegate bytes and expose only public stream cleanup boundaries."""

    def __init__(self, stream, on_cleanup):
        self._stream, self._on_cleanup = stream, on_cleanup

    async def __aiter__(self):
        try:
            async for chunk in self._stream:
                yield chunk
        finally:
            self._on_cleanup()

    async def aclose(self):
        self._on_cleanup()
        await self._stream.aclose()


class TelegramRequest(HTTPXRequest):
    """Observe real native request task lifetime without replacing PTB."""

    def __init__(self, on_poll_success, **kwargs):
        self._on_poll_success = on_poll_success
        self.inflight = set()
        self._http_tasks = set()
        self._cleanup_started = set()
        self._cancel_requested = set()
        self._retiring = False
        self._shutdown_error = None
        super().__init__(**kwargs)

    def _build_client(self):
        client = super()._build_client()
        client.event_hooks["response"].append(self._observe_response)
        return client

    async def _observe_response(self, response):
        task = asyncio.current_task()
        if task not in self._http_tasks:
            return

        def cleanup_started():
            self._cleanup_started.add(task)

        if response.is_stream_consumed:
            cleanup_started()
        else:
            response.stream = _ObservedResponseStream(
                response.stream,
                cleanup_started,
            )
        # HTTPX also reads before returning a non-streaming request. Its next
        # read uses the cached content; headers alone never mark cleanup.
        await response.aread()

    def retire(self):
        self._retiring = True
        for task in tuple(self._http_tasks):
            self._cancel_read(task)

    def _cancel_read(self, task):
        if (
            not task.done()
            and task not in self._cleanup_started
            and task not in self._cancel_requested
        ):
            self._cancel_requested.add(task)
            task.cancel()

    async def do_request(self, url, method, request_data=None, **kwargs):
        is_poll = str(url).endswith("/getUpdates")
        parameters = request_data.parameters if request_data else {}
        if self._retiring and is_poll and parameters.get("timeout", 0):
            raise asyncio.CancelledError
        task = asyncio.current_task()
        child = asyncio.create_task(
            super().do_request(
                url,
                method,
                request_data=request_data,
                **kwargs,
            ),
        )
        self._http_tasks.add(child)
        self.inflight.update((task, child))
        try:
            try:
                result = await asyncio.shield(child)
            except asyncio.CancelledError:
                self._cancel_read(child)
                # A second caller cancellation must not interrupt the HTTP
                # child's finally/close. Keep ownership until its real exit.
                while not child.done():
                    try:
                        await asyncio.shield(child)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not child.cancelled():
                    child.exception()
                raise
            if is_poll and result[0] == 200:
                value = json.loads(result[1])
                if value.get("ok") and isinstance(value.get("result"), list):
                    self._on_poll_success()
            return result
        finally:
            self.inflight.discard(task)
            self.inflight.discard(child)
            self._http_tasks.discard(child)
            self._cleanup_started.discard(child)
            self._cancel_requested.discard(child)

    async def shutdown(self):
        if self._shutdown_error is not None:
            raise self._shutdown_error
        task = asyncio.current_task()
        self.inflight.add(task)
        try:
            await super().shutdown()
        except Exception as exc:
            # HTTPX marks a client closed before awaiting transport.aclose;
            # a second native shutdown may otherwise conceal that failure.
            self._shutdown_error = exc
            raise
        finally:
            self.inflight.discard(task)


def _format_rejection(error):
    return isinstance(error, EndPointNotFound) or (
        isinstance(error, BadRequest)
        and any(
            word in str(error).lower()
            for word in (
                "can't parse entities",
                "cannot parse entities",
                "unsupported rich",
                "unknown method",
                "method not found",
            )
        )
    )


def _rich_rejection(error):
    return _format_rejection(error) or (
        isinstance(error, BadRequest)
        and str(error).strip().lower() == "unsupported"
    )


def _native_media_reference(value, payload_name):
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise TelegramDeliveryError("MEDIA_URL_UNAUTHORIZED")
    try:
        Path(value).lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise TelegramDeliveryError("MEDIA_URL_UNAUTHORIZED") from exc
    else:
        raise TelegramDeliveryError("MEDIA_URL_UNAUTHORIZED")
    constructor, required = {
        "photo": (PhotoSize, {"width": 0, "height": 0}),
        "video": (Video, {"width": 0, "height": 0, "duration": 0}),
        "audio": (Audio, {"duration": 0}),
        "document": (Document, {}),
    }[payload_name]
    # This is only an SDK file_id reference. Empty/zero constructor fields
    # are placeholders, not platform metadata; Bot transmits only file_id.
    # A native object also prevents PTB reopening a newly appeared local file.
    return constructor(file_id=value, file_unique_id="", **required)


class TelegramPlatform:
    def __init__(self, config, on_event, on_state, on_callback):
        from .cards.tool_guard import CardCache
        from .cards.dispatcher import TelegramCardHandler

        self.config = dict(config)
        self.on_event, self.on_state = on_event, on_state
        self.on_callback = on_callback
        self._bot_token = config.get("bot_token") or ""
        self._base_url = (config.get("base_url") or "").strip().rstrip("/")
        self._http_proxy = config.get("http_proxy") or ""
        self._http_proxy_auth = config.get("http_proxy_auth") or ""
        workspace = config.get("workspace_dir")
        media = config.get("media_dir")
        if not media and not workspace:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            media = str(DEFAULT_MEDIA_DIR / "telegram")
        self._media_dir = Path(media or Path(workspace) / "media").expanduser()
        self._roots = [self._media_dir.resolve()]
        if workspace:
            self._roots.append(Path(workspace).expanduser().resolve())
        self._application = None
        self._requests = []
        self._task = None
        self._stop_task = None
        self._cleanup_task = None
        self._stopping = False
        self._polling_error_task = None
        self._tasks = set()
        self._typing_tasks = {}
        self._typing_stopping = set()
        self._last_stop_error = None
        self._polling_conflict_count = 0
        self._polling_network_error_count = 0
        self._reconnect_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._reconnect_reason = None
        self._reconnect_delay = 2.0
        self._seen_updates = OrderedDict()
        self._cards = CardCache()
        self._card_handler = TelegramCardHandler(self)
        self._staged_cards = {}
        self._identity = None

    def _poll_success(self):
        if not self._stopping and self._reconnect_reason is None:
            self._polling_conflict_count = 0
            self._polling_network_error_count = 0

    def _plan_polling_reconnect(self, reason):
        if reason == "conflict":
            self._polling_conflict_count += 1
            self._polling_network_error_count = 0
            attempt = self._polling_conflict_count
            return attempt, min(5 * 1.8 ** (attempt - 1), 31.0)
        self._polling_network_error_count += 1
        self._polling_conflict_count = 0
        attempt = self._polling_network_error_count
        return attempt, min(5 * 2 ** (attempt - 1), 60.0)

    def _own_task(self, task):
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task):
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _build_application(self):
        proxy = self._http_proxy.strip() or None
        if proxy:
            if "://" not in proxy:
                proxy = "http://" + proxy
            if self._http_proxy_auth and "@" not in proxy:
                scheme, rest = proxy.split("://", 1)
                proxy = scheme + "://" + self._http_proxy_auth + "@" + rest
        requests = [
            TelegramRequest(self._poll_success, proxy=proxy),
            TelegramRequest(
                self._poll_success,
                proxy=proxy,
                read_timeout=_GET_UPDATES_READ_TIMEOUT_S,
                connect_timeout=10,
            ),
        ]
        self._requests = requests
        builder = Application.builder().token(self._bot_token)
        builder = builder.request(requests[0]).get_updates_request(requests[1])
        bot_url, file_url = _telegram_base_urls(self._base_url)
        if bot_url:
            builder = builder.base_url(bot_url).base_file_url(file_url)
        app = builder.build()
        app.add_handler(MessageHandler(filters.ALL, self._handle_message))
        app.add_handler(CallbackQueryHandler(self._native_callback))
        return app

    async def _handle_message(self, update, context):
        if self._stopping or update.update_id in self._seen_updates:
            return
        parts, command, mentioned = await _build_content_parts_from_message(
            update,
            bot=context.bot,
            media_dir=self._media_dir,
        )
        if not parts:
            return
        meta = _message_meta(update)
        if not meta.get("chat_id"):
            return
        meta.update(has_bot_command=command, bot_mentioned=mentioned)
        sender = meta["user_id"] or meta["chat_id"]
        value = {
            "event_id": "update:" + str(update.update_id),
            "sender_id": sender,
            "acl_sender_id": sender,
            "user_id": sender,
            "session_id": "telegram:" + meta["chat_id"],
            "meta": meta,
            "content_parts": [
                {
                    key: val
                    for key, val in p.model_dump(mode="json").items()
                    if key
                    in {
                        "type",
                        "text",
                        "image_url",
                        "video_url",
                        "file_url",
                        "data",
                        "filename",
                        "format",
                    }
                    and val is not None
                }
                for p in parts
            ],
        }
        accepted = await self.on_event(value)
        if accepted:
            self._seen_updates[update.update_id] = None
            while len(self._seen_updates) > 500:
                self._seen_updates.popitem(last=False)

    async def _native_callback(self, update, context):
        if not self._stopping and update.callback_query is not None:
            await self._card_handler.handle_callback_query(
                update.callback_query,
            )

    async def _request_polling_reconnect(self, app, reason):
        if self._stopping or self._reconnect_reason is not None:
            return
        self._reconnect_reason = reason
        _, self._reconnect_delay = self._plan_polling_reconnect(reason)
        self._reconnect_event.set()

    async def _polling_cycle(self, app):
        self._reconnect_reason = None
        self._reconnect_event.clear()

        def on_error(error):
            reason = None
            if error.__class__.__name__ == "Conflict":
                reason = "conflict"
            elif isinstance(error, (NetworkError, OSError, ConnectionError)):
                reason = "network"
            if reason is not None and (
                self._polling_error_task is None
                or self._polling_error_task.done()
            ):
                self._polling_error_task = self._own_task(
                    app.create_task(
                        self._request_polling_reconnect(app, reason),
                    ),
                )
            self._own_task(
                app.create_task(app.process_error(error=error, update=None)),
            )

        await app.initialize()
        commands = [
            ("start", "Start a new conversation"),
            ("new", "Start a new conversation (clear memory)"),
            ("compact", "Compact conversation memory"),
            ("clear", "Clear conversation history"),
            ("history", "Show conversation history"),
            ("model", "Show or switch AI model"),
            ("stop", "Stop the current task"),
        ]
        try:
            await app.bot.set_my_commands(
                [BotCommand(*row) for row in commands],
            )
        except Exception:
            logger.warning("Telegram command publication failed")
        await app.updater.start_polling(
            bootstrap_retries=0,
            allowed_updates=["message", "edited_message", "callback_query"],
            error_callback=on_error,
        )
        await app.start()
        await self.on_state("connected")
        self._connected_event.set()
        await self._reconnect_event.wait()

    async def _settle_requests(self):
        while True:
            tasks = {
                task
                for request in self._requests
                for task in request.inflight
                if task is not asyncio.current_task()
            }
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _teardown_application(self, app):
        for request in self._requests:
            request.retire()
        if app.updater.running:
            await app.updater.stop()
        await self._settle_requests()
        if app.running:
            await app.stop()
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        await app.shutdown()
        # Application.shutdown may return early after partial initialize.
        # Each owned PTB request still delegates its actual client shutdown.
        await asyncio.gather(
            *(request.shutdown() for request in self._requests),
        )
        await self._settle_requests()

    async def _teardown(self, app):
        if self._cleanup_task is not None and self._cleanup_task.done():
            if self._cleanup_task.cancelled():
                raise RuntimeError("TELEGRAM_CLEANUP_CANCELLED")
            error = self._cleanup_task.exception()
            if error is not None:
                self._last_stop_error = repr(error)
                self._cleanup_task = None
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(
                self._teardown_application(app),
            )
        await asyncio.shield(self._cleanup_task)
        self._cleanup_task = None
        self._application = None
        self._requests = []

    async def _run_polling(self):
        delay = 2.0
        while not self._stopping:
            app = self._build_application()
            self._application = app
            try:
                await self._polling_cycle(app)
                delay = self._reconnect_delay
            except InvalidToken:
                await self.on_state("failed")
                raise
            except asyncio.CancelledError:
                raise
            except Exception:
                await self.on_state("disconnected")
                logger.exception("Telegram polling connection failed")
            finally:
                await self._teardown(app)
            if not self._stopping:
                await self.on_state("connecting")
                await asyncio.sleep(delay)
                delay = min(delay * 1.8, 30.0)

    async def start(self):
        if not self._bot_token:
            raise TelegramDeliveryError("BOT_TOKEN_MISSING")
        self._stopping = False
        self._task = asyncio.create_task(self._run_polling())
        ready = asyncio.create_task(self._connected_event.wait())
        try:
            done, _ = await asyncio.wait(
                {ready, self._task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._task in done:
                await self._task
                raise TelegramDeliveryError("NOT_CONNECTED")
        finally:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)

    async def _stop_owned(self):
        self._stopping = True
        self._reconnect_event.set()
        for handle in list(self._typing_tasks):
            await self.stop_typing(handle)
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self._last_stop_error = repr(exc)
        if self._application is not None:
            await self._teardown(self._application)
        self._task = None

    async def stop(self):
        if (
            self._stop_task is not None
            and self._stop_task.done()
            and not self._stop_task.cancelled()
            and self._stop_task.exception() is not None
        ):
            self._last_stop_error = repr(self._stop_task.exception())
            self._stop_task = None
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_owned())
        await asyncio.shield(self._stop_task)

    @property
    def bot(self):
        if self._application is None or self._stopping:
            raise TelegramDeliveryError("NOT_CONNECTED")
        return self._application.bot

    @staticmethod
    def _kwargs(route):
        chat = route["chat_id"]
        if not chat or "/" in chat or "\\" in chat:
            raise TelegramDeliveryError("OUTBOUND_TARGET_UNKNOWN")
        result = {
            "chat_id": int(chat) if re.fullmatch(r"-?\d+", chat) else chat,
        }
        thread = route.get("message_thread_id")
        if thread:
            if not str(thread).isdigit() or int(thread) < 1:
                raise TelegramDeliveryError("OUTBOUND_TARGET_UNKNOWN")
            result["message_thread_id"] = int(thread)
        return result

    @staticmethod
    def _receipt(route, messages):
        return {
            **route,
            "message_ids": json.dumps([int(x) for x in messages]),
        }

    @staticmethod
    def _message_id(value):
        ident = (
            value.get("message_id")
            if isinstance(value, dict)
            else value.message_id
        )
        if type(ident) is not int:
            raise TelegramDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        return ident

    async def _effect(self, awaitable):
        try:
            return await awaitable
        except asyncio.CancelledError:
            raise
        except (BadRequest, Forbidden, RetryAfter) as exc:
            raise TelegramDeliveryError("PLATFORM_REJECTED") from exc
        except Exception as exc:
            raise TelegramDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc

    async def _send_text(self, route, text):
        bot = self.bot
        kwargs = self._kwargs(route)
        if _can_send_rich_message(text):
            try:
                value = await bot.do_api_request(
                    "sendRichMessage",
                    api_kwargs={**kwargs, "rich_message": {"markdown": text}},
                )
                return [self._message_id(value)]
            except (BadRequest, EndPointNotFound) as exc:
                if not _rich_rejection(exc):
                    raise TelegramDeliveryError("PLATFORM_REJECTED") from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise TelegramDeliveryError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                ) from exc
        sent = []
        for chunk in _api_chunks(text):
            rendered = markdown_to_telegram_html(chunk)
            try:
                value = await bot.send_message(
                    **kwargs,
                    text=rendered,
                    parse_mode=ParseMode.HTML,
                )
            except BadRequest as exc:
                if sent or not _format_rejection(exc):
                    raise TelegramDeliveryError(
                        "PLATFORM_REJECTED",
                        side_effect_possible=bool(sent),
                    ) from exc
                plain = html.unescape(re.sub(r"<[^>]+>", "", rendered))
                value = await self._effect(
                    bot.send_message(**kwargs, text=plain),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise TelegramDeliveryError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                ) from exc
            sent.append(self._message_id(value))
        return sent

    def _authorize_path(self, path):
        if not any(
            path.resolve().is_relative_to(root) for root in self._roots
        ):
            raise TelegramDeliveryError("MEDIA_PATH_UNAUTHORIZED")

    async def _send_media_value(
        self,
        *,
        bot,
        chat_id,
        value,
        method_name,
        payload_name,
        message_thread_id,
        filename_hint=None,
    ):
        kwargs = {"chat_id": chat_id}
        if message_thread_id is not None:
            kwargs["message_thread_id"] = message_thread_id
        if value.startswith("data:"):
            try:
                media = await parse_data_url_async(value)
            except MediaDataError as exc:
                raise _MediaFileUnavailableError(
                    "Could not decode media data URL.",
                ) from exc
            if media is None:
                raise _MediaFileUnavailableError(
                    "Could not decode media data URL.",
                )
            if len(media.data) > TELEGRAM_MAX_FILE_SIZE_BYTES:
                raise _FileTooLargeError(
                    "File too large to send via Telegram "
                    "(Telegram bot limit: 50 MB)",
                )
            payload = InputFile(
                media.data,
                filename=data_url_filename(
                    filename_hint or payload_name,
                    media.suffix,
                ),
            )
            return await self._effect(
                getattr(bot, method_name)(**kwargs, **{payload_name: payload}),
            )
        if value.startswith("file://"):
            local = file_url_to_local_path(value)
            if not local:
                raise _MediaFileUnavailableError(
                    "Could not resolve media file from URL.",
                )
            path = Path(local).resolve()
            self._authorize_path(path)
            if not path.is_file():
                raise _MediaFileUnavailableError(
                    f"Media file not found: {path.name}",
                )
            size = path.stat().st_size
            if size > TELEGRAM_MAX_FILE_SIZE_BYTES:
                raise _FileTooLargeError(
                    f"File too large to send via Telegram: {path.name} "
                    f"({size / (1024 * 1024):.1f} MB, "
                    "Telegram bot limit: 50 MB)",
                )
            with path.open("rb") as file:
                return await self._effect(
                    getattr(bot, method_name)(
                        **kwargs,
                        **{payload_name: file},
                    ),
                )
        if urlparse(value).scheme not in {"http", "https"}:
            value = _native_media_reference(value, payload_name)
        return await self._effect(
            getattr(bot, method_name)(**kwargs, **{payload_name: value}),
        )

    async def send_parts(self, route, parts, source=None):
        text = "\n".join(p["text"] for p in parts if p["type"] == "text")
        media = [p for p in parts if p["type"] != "text"]
        if source is ContentSource.CONTENT_PARTS:
            for part in media:
                kind = part["type"]
                locator = "data" if kind == "audio" else kind + "_url"
                text += (
                    "\n[Audio]"
                    if kind == "audio"
                    else f"\n[{kind.title()}: {part[locator]}]"
                )
            text = text.strip()
        sent = []
        try:
            if text:
                sent.extend(await self._send_text(route, text))
            for part in media:
                kind = part["type"]
                endpoint, locator, payload = {
                    "image": ("send_photo", "image_url", "photo"),
                    "video": ("send_video", "video_url", "video"),
                    "audio": ("send_audio", "data", "audio"),
                    "file": ("send_document", "file_url", "document"),
                }[kind]
                kwargs = self._kwargs(route)
                value = await self._send_media_value(
                    bot=self.bot,
                    chat_id=kwargs["chat_id"],
                    value=part[locator],
                    method_name=endpoint,
                    payload_name=payload,
                    message_thread_id=kwargs.get("message_thread_id"),
                    filename_hint=part.get("filename"),
                )
                sent.append(self._message_id(value))
        except (
            _FileTooLargeError,
            _MediaFileUnavailableError,
            OSError,
        ) as exc:
            try:
                await self._send_text(route, str(exc))
            except TelegramDeliveryError as notice_error:
                if sent:
                    raise TelegramDeliveryError(
                        notice_error.reason_code,
                        side_effect_possible=True,
                        retryable=notice_error.retryable,
                    ) from notice_error
                raise
            raise TelegramDeliveryError(
                "MEDIA_UNAVAILABLE",
                side_effect_possible=True,
            ) from exc
        except TelegramDeliveryError as exc:
            if sent:
                raise TelegramDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                ) from exc
            raise
        return self._receipt(route, sent)

    async def start_typing(self, handle, route):
        if (
            self.config.get("show_typing", True) is False
            or handle in self._typing_tasks
        ):
            return

        async def typing():
            deadline = time.monotonic() + 180
            while not self._stopping and time.monotonic() < deadline:
                try:
                    await self.bot.send_chat_action(
                        **self._kwargs(route),
                        action="typing",
                    )
                except Exception:
                    logger.debug("Telegram typing notification failed")
                await asyncio.sleep(4)

        self._typing_tasks[handle] = asyncio.create_task(typing())

    async def stop_typing(self, handle):
        task = self._typing_tasks.get(handle)
        if task is not None:
            if handle not in self._typing_stopping:
                self._typing_stopping.add(handle)
                task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    raise
            self._typing_tasks.pop(handle, None)
            self._typing_stopping.discard(handle)

    async def start_stream(self, route, stream_type):
        text = "💭 ⏳" if stream_type == "reasoning" else _STREAM_PLACEHOLDER
        value = await self._effect(
            self.bot.send_message(**self._kwargs(route), text=text),
        )
        return {
            **self._receipt(route, [self._message_id(value)]),
            "stream_type": stream_type,
            "last_edit": "0",
            "final": "false",
        }

    async def update_stream(self, resource, text, *, final=False):
        last = float(resource.get("last_edit", "0"))
        if not final:
            await asyncio.sleep(
                max(0, _STREAM_EDIT_INTERVAL_S - (time.monotonic() - last)),
            )
        ids = json.loads(resource["message_ids"])
        if len(ids) != 1:
            raise TelegramDeliveryError("OUTBOUND_TARGET_UNKNOWN")
        if final and _utf16_units(text) > TELEGRAM_SEND_CHUNK_SIZE:
            await self.delete_stream(resource)
            try:
                ids = await self._send_text(resource, text)
            except TelegramDeliveryError as exc:
                raise TelegramDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                    retryable=exc.retryable,
                ) from exc
        else:
            display = text or _STREAM_PLACEHOLDER
            if (
                not final
                and _utf16_units(display) > TELEGRAM_MAX_MESSAGE_LENGTH
            ):
                display = "..." + _api_tail(
                    display,
                    TELEGRAM_MAX_MESSAGE_LENGTH - 4,
                )
            kwargs = {
                "chat_id": self._kwargs(resource)["chat_id"],
                "message_id": ids[0],
            }
            if final and _can_send_rich_message(display):
                try:
                    await self.bot.do_api_request(
                        "editMessageText",
                        api_kwargs={
                            **kwargs,
                            "rich_message": {"markdown": display},
                        },
                    )
                    return {
                        **resource,
                        "final": "true",
                        "last_edit": str(time.monotonic()),
                    }
                except (BadRequest, EndPointNotFound) as exc:
                    if not _rich_rejection(exc):
                        raise TelegramDeliveryError(
                            "PLATFORM_REJECTED",
                        ) from exc
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    raise TelegramDeliveryError(
                        "PLATFORM_RESULT_UNKNOWN",
                        side_effect_possible=True,
                    ) from exc
            try:
                await self.bot.edit_message_text(
                    **kwargs,
                    text=(
                        markdown_to_telegram_html(display)
                        if final
                        else display
                    ),
                    **({"parse_mode": ParseMode.HTML} if final else {}),
                )
            except BadRequest as exc:
                if "not modified" not in str(exc).lower():
                    if final and _format_rejection(exc):
                        await self._effect(
                            self.bot.edit_message_text(
                                **kwargs,
                                text=html.unescape(
                                    re.sub(
                                        r"<[^>]+>",
                                        "",
                                        markdown_to_telegram_html(display),
                                    ),
                                ),
                            ),
                        )
                    else:
                        raise TelegramDeliveryError(
                            "PLATFORM_REJECTED",
                        ) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise TelegramDeliveryError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                ) from exc
        return {
            **resource,
            "message_ids": json.dumps(ids),
            "final": "true" if final else "false",
            "last_edit": str(time.monotonic()),
        }

    async def delete_stream(self, resource):
        chat = self._kwargs(resource)["chat_id"]
        for ident in json.loads(resource["message_ids"]):
            await self._effect(
                self.bot.delete_message(chat_id=chat, message_id=ident),
            )

    async def send_approval(self, route, params, identity):
        from .cards.tool_guard import (
            ApprovalCardBinding,
            build_approval_keyboard,
            build_approval_text,
        )

        approval = params.approval
        for value in (
            "tga:" + approval.request_id,
            "tgd:" + approval.request_id,
        ):
            if len(value.encode()) > 64:
                raise TelegramDeliveryError("APPROVAL_CALLBACK_TOO_LARGE")
        body = "".join(
            p["text"] for p in params.content_parts if p["type"] == "text"
        )
        kwargs = self._kwargs(route)
        value = await self._effect(
            self.bot.send_message(
                **kwargs,
                text=build_approval_text(body),
                reply_markup=build_approval_keyboard(approval.request_id),
            ),
        )
        ident = self._message_id(value)
        self._identity = identity
        binding = ApprovalCardBinding(
            approval.request_id,
            approval.tool_name,
            body,
            route["chat_id"],
            ident,
            kwargs.get("message_thread_id"),
            route["session_id"],
            route["root_session_id"],
            route["user_id"],
            params.to_handle,
            params.delivery_id,
            identity.instance_id,
            identity.generation,
        )
        self._staged_cards[params.delivery_id] = (
            binding,
            approval.severity.value,
        )
        return self._receipt(route, [ident])

    def complete_card_delivery(self, delivery_id, acknowledged):
        staged = self._staged_cards.pop(delivery_id, None)
        if staged is None or not acknowledged:
            return
        binding, severity = staged
        self._cards._cache_request_context(
            binding.request_id,
            binding.tool_name,
            severity,
            binding.body_text,
            {
                "session_id": binding.session_id,
                "root_session_id": binding.root_session_id,
                "chat_id": binding.chat_id,
                "user_id": binding.user_id,
                "message_thread_id": binding.message_thread_id,
            },
        )
        self._cards._get_request_context(binding.request_id)[
            "binding"
        ] = binding

    async def _handle_callback(self, query):
        from .cards.tool_guard import ApprovalCardBinding, _parse_callback_data

        parsed = _parse_callback_data(query.data or "")
        if parsed is None:
            return
        cached = self._cards._get_request_context(parsed["request_id"])
        binding = cached.get("binding") if cached else None
        message, actor = query.message, query.from_user
        valid = (
            isinstance(binding, ApprovalCardBinding)
            and message is not None
            and actor is not None
            and actor.id is not None
            and self._identity is not None
            and binding.instance_id == self._identity.instance_id
            and binding.generation == self._identity.generation
            and str(message.chat.id) == binding.chat_id
            and message.message_id == binding.message_id
            and message.message_thread_id == binding.message_thread_id
        )
        if not valid:
            await query.answer(
                text="This approval button has expired.",
                show_alert=True,
            )
            return
        if binding.request_id in self._cards._processed_requests:
            try:
                await query.answer(text="Already processed.", show_alert=False)
            except Exception:
                logger.debug("Telegram processed callback toast failed")
            return
        try:
            await query.answer(
                text="Received. Waiting for authorization.",
                show_alert=False,
            )
        except Exception:
            logger.debug("Telegram neutral callback acknowledgment failed")
        actor_id = str(actor.id)
        meta = {
            "chat_id": binding.chat_id,
            "user_id": binding.user_id,
            "message_thread_id": binding.message_thread_id,
            "root_session_id": binding.root_session_id,
            "is_group": message.chat.type != "private",
            "username": actor.username or actor.first_name or actor_id,
            "operator_display": (
                "@" + actor.username
                if actor.username
                else actor.first_name or actor_id
            ),
            "bot_mentioned": True,
            "has_bot_command": True,
        }
        await self.on_callback(
            {
                "event_id": "callback:" + query.id,
                "event_kind": "callback",
                "sender_id": binding.user_id,
                "acl_sender_id": actor_id,
                "user_id": binding.user_id,
                "session_id": binding.session_id,
                "meta": meta,
                "approval_binding_id": binding.request_id,
                "approval_actor_id": actor_id,
                "content_parts": [
                    {
                        "type": "text",
                        "text": (
                            f"/approval {parsed['action']} "
                            f"{binding.request_id}"
                        ),
                    },
                ],
            },
        )

    async def resolve_approval(self, route, params):
        from .cards.tool_guard import build_resolved_text

        result = params.approval_resolution
        request_id = route.get("approval_binding_id")
        cached = (
            self._cards._get_request_context(request_id)
            if request_id
            else None
        )
        binding = cached.get("binding") if cached else None
        if (
            binding is None
            or result.request_id != request_id
            or result.actor_user_id != route.get("approval_actor_id")
            or result.outcome.value not in {"approved", "denied"}
        ):
            return await self.send_parts(
                route,
                params.content_parts,
                ContentSource.DIRECT,
            )
        if (
            binding.chat_id != route["chat_id"]
            or str(binding.message_thread_id or "")
            != route.get("message_thread_id", "")
            or binding.instance_id != params.instance_id
            or binding.generation != params.generation
        ):
            raise TelegramDeliveryError("APPROVAL_BINDING_INVALID")
        action = "approve" if result.outcome.value == "approved" else "deny"
        text = build_resolved_text(
            result.tool_name,
            action,
            route.get("operator_display") or result.actor_user_id,
            binding.body_text,
        )
        kwargs = {
            "chat_id": int(binding.chat_id),
            "message_id": binding.message_id,
            "text": text,
            "reply_markup": {"inline_keyboard": []},
        }
        if not binding.body_text:
            kwargs["parse_mode"] = ParseMode.MARKDOWN_V2

        async def edit_resolved():
            try:
                await self.bot.edit_message_text(**kwargs)
            except BadRequest as exc:
                if not str(exc).lower().startswith("message is not modified"):
                    raise

        await self._effect(edit_resolved())
        self._cards._mark_processed(request_id, action)
        return self._receipt(route, [binding.message_id])
