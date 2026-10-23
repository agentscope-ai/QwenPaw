# -*- coding: utf-8 -*-
"""Worker-owned Discord Gateway, native parsing and message effects."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import discord

from qwenpaw.app.channels.utils import (
    file_url_to_local_path,
    materialize_data_url,
)
from .formatting import (
    build_stream_display_text,
    chunk_text,
    classify_attachment,
    resolve_session_id,
    route_from_handle,
)

logger = logging.getLogger(__name__)


class DiscordDeliveryError(Exception):
    def __init__(
        self,
        reason_code,
        *,
        side_effect_possible=False,
        retryable=False,
    ):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable


class DiscordPlatform:
    def __init__(self, config, on_event, on_state):
        self.config, self.on_event, self.on_state = config, on_event, on_state
        workspace = config.get("workspace_dir")
        if config.get("media_dir"):
            self._media_dir = Path(config["media_dir"]).expanduser()
        elif workspace:
            self._media_dir = Path(workspace) / "media"
        else:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            self._media_dir = DEFAULT_MEDIA_DIR
        self._client, self._task = None, None
        self._typing_tasks, self._event_tasks = {}, set()
        self._typing_contexts, self._typing_cancel_requests = {}, set()
        self._effect_tasks = set()
        self._processed = OrderedDict()
        self._recent_thread_starts = OrderedDict()
        self._message_locks = {}
        self._epoch, self._stopping, self.connected = 0, False, False

    async def start(self):
        if not self.config.get("bot_token"):
            raise ValueError("DISCORD_TOKEN_REQUIRED")
        self._media_dir.mkdir(parents=True, exist_ok=True)
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.messages = True
        intents.guilds = True
        auth = None
        if self.config.get("http_proxy_auth"):
            user, password = self.config["http_proxy_auth"].split(":", 1)
            auth = aiohttp.BasicAuth(user, password)
        self._client = discord.Client(
            intents=intents,
            proxy=self.config.get("http_proxy") or None,
            proxy_auth=auth,
        )

        @self._client.event
        async def on_ready():
            if not self._stopping:
                self.connected = True
                await self.on_state("connected")

        @self._client.event
        async def on_resumed():
            await on_ready()

        @self._client.event
        async def on_disconnect():
            self.connected = False
            self._epoch += 1
            if not self._stopping:
                await self.on_state("disconnected")

        @self._client.event
        async def on_message(message):
            await self._callback(self._on_message, message)

        @self._client.event
        async def on_thread_create(thread):
            await self._callback(self._on_thread_create, thread)

        self._task = asyncio.create_task(
            self._gateway(),
            name="discord_gateway",
        )

    async def _gateway(self):
        try:
            await self._client.start(self.config["bot_token"], reconnect=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Discord Gateway failed")
            if not self._stopping:
                self.connected = False
                self._epoch += 1
                await self.on_state("failed")

    async def _callback(self, handler, value):
        if (
            self._stopping
            or not self.connected
            or len(self._event_tasks) >= 500
        ):
            return
        task = asyncio.current_task()
        self._event_tasks.add(task)
        epoch = self._epoch
        try:
            await handler(value, epoch)
        finally:
            self._event_tasks.discard(task)

    def _current(self, epoch):
        return not self._stopping and self.connected and epoch == self._epoch

    @asynccontextmanager
    async def _message_lock(self, message_id):
        entry = self._message_locks.setdefault(message_id, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._message_locks.pop(message_id, None)

    async def _on_message(self, message, epoch):
        async with self._message_lock(str(message.id)):
            if not self._current(epoch):
                return
            if message.author == self._client.user:
                return
            if message.author.bot and not self.config.get(
                "accept_bot_messages",
            ):
                return
            msg_id = str(message.id)
            if msg_id in self._processed:
                return
            text = (message.content or "").strip()
            bot = self._client.user
            mentioned = bool(getattr(message, "mention_everyone", False))
            if bot and bot in message.mentions:
                mentioned = True
                import re

                text = re.sub(rf"<@!?{bot.id}>", "", text).strip()
            if not mentioned and message.guild and bot:
                member = message.guild.get_member(bot.id)
                if member:
                    matches = {r.id for r in message.role_mentions} & {
                        r.id for r in member.roles
                    }
                    if matches:
                        mentioned = True
                        import re

                        for role_id in matches:
                            text = re.sub(rf"<@&{role_id}>", "", text).strip()
            parts = [{"type": "text", "text": text}] if text else []
            for attachment in message.attachments:
                local = await self._download_attachment(attachment)
                if not local:
                    continue
                kind = classify_attachment(attachment)
                field = "data" if kind == "audio" else kind + "_url"
                parts.append({"type": kind, field: local})
            group = message.guild is not None
            is_thread = isinstance(message.channel, discord.Thread)
            thread = (
                getattr(message, "thread", None) if not is_thread else None
            )
            flags = getattr(message, "flags", None)
            race = (
                self._recent_thread_starts.get(msg_id)
                if group
                and not is_thread
                and not thread
                and flags
                and getattr(flags, "has_thread", False)
                else None
            )
            channel_id = str(
                message.channel.id
                if is_thread
                else thread.id
                if thread
                else race or message.channel.id,
            )
            meta = {
                "user_id": str(message.author.id),
                "channel_id": channel_id,
                "guild_id": str(message.guild.id) if group else None,
                "message_id": msg_id,
                "is_dm": not group,
                "is_group": group,
                "bot_mentioned": mentioned,
            }
            if is_thread or thread or race:
                meta.update(
                    is_thread=True,
                    thread_id=channel_id,
                    parent_channel_id=(
                        str(message.channel.parent_id)
                        if is_thread and message.channel.parent_id
                        else None
                        if is_thread
                        else str(message.channel.id)
                    ),
                )
            if not self._current(epoch):
                return
            accepted = await self.on_event(
                {
                    "message_id": msg_id,
                    "sender_id": str(message.author),
                    "acl_sender_id": str(message.author.id),
                    "content_parts": parts,
                    "meta": meta,
                },
            )
            if accepted and self._current(epoch):
                self._processed[msg_id] = None
                while len(self._processed) > 500:
                    self._processed.popitem(last=False)

    async def _on_thread_create(self, thread, epoch):
        starter = getattr(thread, "starter_message", None)
        if not starter or not self._current(epoch):
            return
        key, value = str(starter.id), str(thread.id)
        self._recent_thread_starts[key] = value
        while len(self._recent_thread_starts) > 500:
            self._recent_thread_starts.popitem(last=False)
        await asyncio.sleep(30)
        if (
            self._current(epoch)
            and self._recent_thread_starts.get(key) == value
        ):
            self._recent_thread_starts.pop(key, None)

    async def _download_attachment(self, attachment):
        if not self._client or not isinstance(attachment, discord.Attachment):
            return None
        safe = (
            "".join(
                c
                for c in (attachment.filename or "")
                if c.isalnum() or c in "-_."
            )
            or "file"
        )
        path = self._media_dir / f"{attachment.id}_{safe}"
        try:
            await attachment.save(path)
            return str(path)
        except asyncio.CancelledError:
            path.unlink(missing_ok=True)
            raise
        except Exception:
            path.unlink(missing_ok=True)
            logger.exception("Discord attachment download failed")
            return None

    async def resolve_target(self, route):
        if route.get("channel_id"):
            ident = int(route["channel_id"])
            return self._client.get_channel(
                ident,
            ) or await self._client.fetch_channel(ident)
        if route.get("user_id"):
            ident = int(route["user_id"])
            user = self._client.get_user(
                ident,
            ) or await self._client.fetch_user(ident)
            return user.dm_channel or await user.create_dm()
        raise DiscordDeliveryError("OUTBOUND_TARGET_UNKNOWN")

    @asynccontextmanager
    async def _effect(self):
        if self._stopping or not self.connected:
            raise DiscordDeliveryError("NOT_CONNECTED")
        task = asyncio.current_task()
        self._effect_tasks.add(task)
        try:
            yield
        finally:
            self._effect_tasks.discard(task)

    @staticmethod
    async def _request(call):
        try:
            return await call
        except discord.HTTPException as exc:
            rejected = 400 <= exc.status < 500
            raise DiscordDeliveryError(
                "DISCORD_REJECTED" if rejected else "DISCORD_RESULT_UNKNOWN",
                side_effect_possible=not rejected,
                retryable=exc.status == 429,
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise DiscordDeliveryError(
                "DISCORD_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc

    @staticmethod
    def _receipt(target, message):
        if not getattr(message, "id", None):
            raise DiscordDeliveryError(
                "DISCORD_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        return {"channel_id": str(target.id), "message_id": str(message.id)}

    async def send_parts(self, route, parts):
        async with self._effect():
            target = await self.resolve_target(route)
            sent = []
            try:
                texts, media = [], []
                for part in parts:
                    if part["type"] in {"image", "video", "audio", "file"}:
                        media.append(part)
                    else:
                        texts.append(
                            part.get("text") or part.get("refusal") or "",
                        )
                text = "\n".join(texts)
                if text:
                    for chunk in chunk_text(text):
                        sent.append(await self._request(target.send(chunk)))
                for part in media:
                    message = await self._send_media(target, part)
                    if message is not None:
                        sent.append(message)
            except DiscordDeliveryError as exc:
                if sent and not exc.side_effect_possible:
                    raise DiscordDeliveryError(
                        exc.reason_code,
                        side_effect_possible=True,
                    ) from exc
                raise
            return {
                "channel_id": str(target.id),
                "message_id": ",".join(
                    self._receipt(target, msg)["message_id"] for msg in sent
                ),
            }

    def _authorize_path(self, path):
        roots = [self._media_dir.resolve()]
        if self.config.get("workspace_dir"):
            roots.append(Path(self.config["workspace_dir"]).resolve())
        if not any(path.resolve().is_relative_to(root) for root in roots):
            raise DiscordDeliveryError("MEDIA_PATH_UNAUTHORIZED")

    async def _send_file(self, target, path, filename=None):
        attachment = discord.File(str(path), filename=filename)
        try:
            return await self._request(target.send(file=attachment))
        finally:
            attachment.close()

    async def _send_media(self, target, part):
        url = (
            part.get("image_url")
            or part.get("video_url")
            or part.get("data")
            or part.get("file_url")
        )
        if not url:
            return None
        if url.startswith("data:"):
            async with materialize_data_url(
                url,
                self._media_dir,
                filename_hint=part.get("filename") or "image",
            ) as media:
                if media is None:
                    return None
                return await self._send_file(
                    target,
                    media.path,
                    media.filename,
                )
        if url.startswith("file://"):
            local = file_url_to_local_path(url)
            if not local:
                return None
            path = Path(local)
            self._authorize_path(path)
            return await self._send_file(target, path)
        if url.startswith(("http://", "https://")):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    data = await response.read()
            parsed = Path(urlparse(url).path)
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=parsed.suffix,
                dir=self._media_dir,
            ) as temp:
                temp.write(data)
            path = Path(temp.name)
            try:
                return await self._send_file(
                    target,
                    path,
                    parsed.name or f"file{parsed.suffix}",
                )
            finally:
                path.unlink(missing_ok=True)
        return None

    async def start_stream(self, route, text):
        async with self._effect():
            target = await self.resolve_target(route)
            return self._receipt(
                target,
                await self._request(target.send(text)),
            )

    async def update_stream(self, resource, text, final=False):
        async with self._effect():
            target = await self.resolve_target(resource)
            message = target.get_partial_message(int(resource["message_id"]))
            if final and len(text) > 2000:
                await self._request(message.delete())
                try:
                    replacement = (
                        {"user_id": resource["replacement_user_id"]}
                        if resource.get("replacement_user_id")
                        else resource
                    )
                    receipt = await self.send_parts(
                        replacement,
                        [{"type": "text", "text": text}],
                    )
                except DiscordDeliveryError as exc:
                    raise DiscordDeliveryError(
                        exc.reason_code,
                        side_effect_possible=True,
                    ) from exc
                return receipt
            display = text
            if not final and len(display) > 2000:
                display = "..." + display[-1996:]
            await self._request(message.edit(content=display))
            return {
                "channel_id": resource["channel_id"],
                "message_id": resource["message_id"],
            }

    async def start_typing(self, handle, route):
        if handle in self._typing_tasks:
            return
        target = await self.resolve_target(route)
        entered = asyncio.get_running_loop().create_future()
        context = target.typing()
        self._typing_contexts[handle] = context

        async def keepalive():
            try:
                async with context:
                    entered.set_result(None)
                    while not self._stopping and self.connected:
                        await asyncio.sleep(60)
            except BaseException as exc:
                if not entered.done():
                    entered.set_exception(exc)
                raise

        task = asyncio.create_task(keepalive(), name="discord_typing")
        self._typing_tasks[handle] = task
        try:
            await entered
        except BaseException:
            await self.stop_typing(handle)
            raise

    async def stop_typing(self, handle):
        task = self._typing_tasks.get(handle)
        if task:
            if handle not in self._typing_cancel_requests:
                self._typing_cancel_requests.add(handle)
                task.cancel()
            # Caller cancellation must not interrupt an already cancelling
            # SDK HTTP request. Keep both tasks owned until a retry observes
            # their quiescence; the process owner's existing deadline applies.
            outcomes = await asyncio.gather(
                asyncio.shield(task),
                return_exceptions=True,
            )
            context = self._typing_contexts.get(handle)
            native = getattr(context, "task", None)
            if native is not None:
                # discord.py __aexit__ requests cancellation but does not await
                # this renewal task. Never issue a second cancellation while
                # its HTTP cleanup is unwinding.
                outcomes.extend(
                    await asyncio.gather(
                        asyncio.shield(native),
                        return_exceptions=True,
                    ),
                )
            self._typing_tasks.pop(handle, None)
            self._typing_contexts.pop(handle, None)
            self._typing_cancel_requests.discard(handle)
            for outcome in outcomes:
                if isinstance(outcome, BaseException) and not isinstance(
                    outcome,
                    asyncio.CancelledError,
                ):
                    logger.warning("Discord typing exit failed: %s", outcome)
                    raise outcome

    async def stop(self):
        self._stopping = True
        self.connected = False
        self._epoch += 1
        for task in tuple(self._event_tasks | self._effect_tasks):
            if task is not asyncio.current_task():
                task.cancel()
        pending = tuple(
            task
            for task in self._event_tasks | self._effect_tasks
            if task is not asyncio.current_task()
        )
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for handle in tuple(self._typing_tasks):
            await self.stop_typing(handle)
        if self._task:
            self._task.cancel()
        if self._client:
            # Keep both references if close fails; the owner retries this stop.
            await self._client.close()
        if self._task:
            results = await asyncio.gather(self._task, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException) and not isinstance(
                    result,
                    asyncio.CancelledError,
                ):
                    raise result
            self._task = None
        self._client = None
        self._recent_thread_starts.clear()
