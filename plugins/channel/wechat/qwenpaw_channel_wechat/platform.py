# -*- coding: utf-8 -*-
"""Owned iLink clients and tasks; no response buffering or host services."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import hashlib
from itertools import chain
import json
import logging
from pathlib import Path
import time

from qwenpaw.app.channels.utils import (
    file_url_to_local_path,
    materialize_data_url,
    split_text,
)
from qwenpaw.constant import DEFAULT_MEDIA_DIR, WORKING_DIR
from .client import ILinkClient, _DEFAULT_BASE_URL
from .errors import WeChatDeliveryError
from .messages import WeChatMessageParser

logger = logging.getLogger(__name__)


class WeChatPlatform:
    def __init__(self, config, on_message, on_state, on_auth_required=None):
        self._config = dict(config)
        self._on_message, self._on_state = on_message, on_state
        self._on_auth_required = on_auth_required
        workspace = config.get("workspace_dir")
        media = config.get("media_dir")
        self._media_dir = Path(
            media
            or (Path(workspace) / "media" if workspace else DEFAULT_MEDIA_DIR),
        ).expanduser()
        self._roots = [self._media_dir.resolve()]
        if workspace:
            self._roots.append(Path(workspace).expanduser().resolve())
        self._token_file = Path(
            config.get("bot_token_file")
            or Path(WORKING_DIR) / "wechat_bot_token",
        ).expanduser()
        self._context_file = (
            self._token_file.parent / "wechat_context_tokens.json"
        )
        self._contexts = {}
        self._processed = OrderedDict()
        self._text_seen = {}
        self._parser = WeChatMessageParser(self._media_dir)
        self._client = self._poll_client = None
        self._poll_task = self._starting_task = None
        self._stopping = False
        self._typing = {}
        self._typing_users = {}
        self._tickets = {}

    def context_token(self, user):
        return self._contexts.get(user, "")

    def _load_contexts(self):
        try:
            data = json.loads(self._context_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._contexts = {
                    k: v
                    for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, str)
                }
        except (OSError, ValueError):
            pass

    def _save_contexts(self):
        try:
            self._context_file.parent.mkdir(parents=True, exist_ok=True)
            self._context_file.write_text(
                json.dumps(self._contexts, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("WeChat context cache could not be saved")

    async def start(self):
        self._stopping = False
        self._starting_task = asyncio.current_task()
        token = self._config.get("bot_token") or ""
        if not token:
            try:
                token = self._token_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        self._load_contexts()
        self._client = ILinkClient(
            token,
            self._config.get("base_url") or _DEFAULT_BASE_URL,
        )
        try:
            await self._client.start()
            if not token:
                data = await self._client.get_bot_qrcode()
                code = data.get("qrcode", "")
                if not code:
                    raise ValueError("QRCODE_UNAVAILABLE")
                scan_url = data.get("qrcode_img_content", "")
                if not scan_url.startswith("http"):
                    scan_url = f"https://liteapp.weixin.qq.com/q/7GiQu1?qrcode={code}&bot_type=3"
                logger.info("WeChat login: scan %s", scan_url)
                if self._on_auth_required is not None:
                    await self._on_auth_required(scan_url)
                # The legacy helper counts poll intervals, not wall time.
                # Keep its wire behavior but bound this owned login lifetime.
                async with asyncio.timeout(300):
                    token, base = await self._client.wait_for_login(code)
                if not token:
                    raise ValueError("QRCODE_CREDENTIALS_MISSING")
                self._client.bot_token = token
                self._client.base_url = (base or self._client.base_url).rstrip(
                    "/",
                )
                try:
                    self._token_file.parent.mkdir(parents=True, exist_ok=True)
                    self._token_file.write_text(token, encoding="utf-8")
                except OSError:
                    logger.warning("WeChat token could not be saved")
            self._poll_client = ILinkClient(token, self._client.base_url)
            await self._poll_client.start()
            await self._on_state("connected")
            self._poll_task = asyncio.create_task(
                self._poll(),
                name="wechat-poll",
            )
        except BaseException:
            await self._close_clients()
            raise
        finally:
            self._starting_task = None

    async def _close_clients(self):
        # Clear each reference only after its close actually succeeds.
        for name in ("_poll_client", "_client"):
            client = getattr(self, name)
            if client is not None:
                await client.stop()
                setattr(self, name, None)

    async def stop(self):
        self._stopping = True
        task = self._starting_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        for handle in tuple(self._typing):
            await self.finish_response(handle)
        await self._close_clients()

    async def _poll(self):
        cursor, failures = "", 0
        while not self._stopping:
            try:
                data = await self._poll_client.getupdates(cursor)
                failures = 0
                if data.get("get_updates_buf") is not None:
                    cursor = data["get_updates_buf"]
                messages = data.get("msgs") or []
                for message in messages:
                    if self._stopping:
                        return
                    try:
                        await self._message(message)
                    except Exception:
                        logger.warning("WeChat inbound message failed")
                if data.get("ret", -1) not in (0, -1) and not messages:
                    await asyncio.sleep(3)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("WeChat polling failed; retrying")
                await asyncio.sleep(min(5 * 2 ** min(failures, 5), 120))
                failures += 1

    async def _message(self, message):
        if message.get("message_type", 0) != 1:
            return
        sender = message.get("from_user_id", "")
        context = message.get("context_token", "")
        native_id = context or f"{sender}_{message.get('msg_id', '')}"
        if not sender or native_id in self._processed:
            return
        self._processed[native_id] = None
        while len(self._processed) > 2000:
            self._processed.popitem(last=False)
        text = "".join(
            (part.get("text_item") or {}).get("text", "")
            for part in message.get("item_list") or []
            if part.get("type") == 1
        ).strip()
        now = time.monotonic()
        self._text_seen = {
            key: expiry
            for key, expiry in self._text_seen.items()
            if expiry > now
        }
        if text:
            text_key = (sender, hashlib.md5(text.encode()).hexdigest()[:16])
            if text_key in self._text_seen:
                return
            self._text_seen[text_key] = now + 30
        parts = await self._parser.parse(message, self._poll_client)
        if not parts:
            return
        group = message.get("group_id", "")
        if context:
            self._contexts[sender] = context
            self._save_contexts()
        session = f"wechat:group:{group}" if group else f"wechat:{sender}"
        await self._on_message(
            {
                "event_id": hashlib.sha256(native_id.encode()).hexdigest(),
                "sender_id": sender,
                "acl_sender_id": sender,
                "session_id": session,
                "user_id": session if group else sender,
                "content_parts": parts,
                "meta": {
                    "wechat_from_user_id": sender,
                    "wechat_to_user_id": message.get("to_user_id", ""),
                    "wechat_context_token": context,
                    "wechat_group_id": group,
                    "is_group": bool(group),
                },
            },
        )

    def start_typing(self, handle, user, context):
        if handle in self._typing or not user or not context or self._stopping:
            return
        self._typing[handle] = user
        entry = self._typing_users.get(user)
        if entry is None:
            entry = {
                "handles": set(),
                "ticket": "",
                "task": asyncio.create_task(
                    self._type(user, context),
                    name="wechat-typing",
                ),
            }
            self._typing_users[user] = entry
        entry["handles"].add(handle)

    async def _type(self, user, context):
        ticket = ""
        try:
            cached = self._tickets.get(user)
            if cached and cached[1] > time.monotonic():
                ticket = cached[0]
            else:
                data = await self._client.getconfig(user, context)
                ticket = (data.get("typing_ticket") or "").strip()
                if ticket:
                    self._tickets[user] = (ticket, time.monotonic() + 86400)
            if ticket:
                self._typing_users[user]["ticket"] = ticket
                while not self._stopping:
                    await self._client.sendtyping(user, ticket, status=1)
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("WeChat typing indicator failed")

    async def finish_response(self, handle):
        user = self._typing.get(handle)
        if user is None:
            return
        entry = self._typing_users[user]
        if entry["handles"] == {handle}:
            task = entry["task"]
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            if entry["ticket"] and self._client is not None:
                await self._client.sendtyping(user, entry["ticket"], status=2)
            del self._typing_users[user]
        else:
            entry["handles"].discard(handle)
        del self._typing[handle]

    @asynccontextmanager
    async def _local_media(self, value, filename_hint=None):
        async with materialize_data_url(
            value,
            self._media_dir,
            filename_hint=filename_hint,
        ) as materialized:
            if materialized is None:
                raise WeChatDeliveryError("MEDIA_PATH_INVALID")
            local_path = Path(
                file_url_to_local_path(materialized.path) or materialized.path,
            ).expanduser()
            path = local_path.resolve()
            if (
                not any(path.is_relative_to(root) for root in self._roots)
                or not path.is_file()
            ):
                raise WeChatDeliveryError("MEDIA_PATH_INVALID")
            yield path, materialized.filename or local_path.name

    async def send_parts(self, route, parts):
        user, context = route["wechat_from_user_id"], route.get(
            "wechat_context_token",
        ) or self.context_token(route["wechat_from_user_id"])
        if not user or not context:
            raise WeChatDeliveryError("CONTEXT_TOKEN_MISSING")
        sent = False
        try:
            text_types = ("text", "refusal")
            ordered = chain(
                (p for p in parts if p.get("type") not in text_types),
                (p for p in parts if p.get("type") in text_types),
            )
            for part in ordered:
                kind = part.get("type")
                if kind in ("text", "refusal"):
                    text = part.get("text") or part.get("refusal") or ""
                    for chunk in split_text(text):
                        response = await self._client.send_text(
                            user,
                            chunk,
                            context,
                        )
                        self._check_result(response, sent)
                        sent = True
                elif kind in ("image", "file", "video", "audio"):
                    value = part.get(
                        "data" if kind == "audio" else kind + "_url",
                    )
                    if not isinstance(value, str) or not value:
                        raise WeChatDeliveryError(
                            "MEDIA_PATH_INVALID",
                            side_effect_possible=sent,
                        )
                    if kind == "audio" and value.startswith("data:"):
                        raise WeChatDeliveryError(
                            "MEDIA_UNSUPPORTED",
                            side_effect_possible=sent,
                        )
                    async with self._local_media(
                        value,
                        part.get("filename"),
                    ) as (path, filename):
                        if kind == "image":
                            response = await self._client.send_image(
                                user,
                                str(path),
                                context,
                            )
                        elif kind == "video":
                            response = await self._client.send_video(
                                user,
                                str(path),
                                context,
                            )
                        else:
                            response = await self._client.send_file(
                                user,
                                str(path),
                                filename,
                                context,
                            )
                    self._check_result(response, sent)
                    sent = True
                else:
                    raise WeChatDeliveryError(
                        "CONTENT_UNSUPPORTED",
                        side_effect_possible=sent,
                    )
        except WeChatDeliveryError as exc:
            exc.side_effect_possible |= sent
            raise
        except Exception as exc:
            raise WeChatDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        if not sent:
            raise WeChatDeliveryError("CONTENT_EMPTY")

    @staticmethod
    def _check_result(response, sent):
        if not isinstance(response, dict) or not (
            {"ret", "errcode"} & response.keys()
        ):
            raise WeChatDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        if any(
            type(response[key]) is not int
            for key in ("ret", "errcode")
            if key in response
        ):
            raise WeChatDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        if response.get("ret") == -2:
            raise WeChatDeliveryError(
                "CONTEXT_TOKEN_INVALID",
                side_effect_possible=sent,
            )
        if response.get("ret", 0) != 0 or response.get("errcode", 0) != 0:
            raise WeChatDeliveryError(
                "PLATFORM_SEND_FAILED",
                side_effect_possible=sent,
            )
