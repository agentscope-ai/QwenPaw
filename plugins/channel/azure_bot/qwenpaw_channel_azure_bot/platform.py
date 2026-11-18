# -*- coding: utf-8 -*-
"""Owned Bot Framework HTTP listener, credentials, media and native effects."""

import asyncio
import base64
import json
import mimetypes
from pathlib import Path
import time
from urllib.parse import quote, unquote, urlsplit
import uuid

import aiohttp
from aiohttp import web
import msal

from .auth import AzureBotTokenValidator
from .attachments import (
    PublicAttachmentResolver,
    attachment_url,
    attachment_uses_token,
)
from .constants import DOWNLOAD_MAX_BYTES, FILE_TOO_LARGE, UPLOAD_MAX_BYTES
from .state import AzureBotStateStore


class AzureBotDeliveryError(RuntimeError):
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


def _group(activity):
    conversation = activity.get("conversation") or {}
    slack = (
        (activity.get("channelData") or {}).get("SlackMessage") or {}
    ).get(
        "event",
    ) or {}
    return (
        conversation.get("conversationType") in ("channel", "groupChat")
        or conversation.get("isGroup") is True
        or slack.get("channel_type") in ("channel", "group")
    )


def _service_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError("AZURE_SERVICE_URL_INVALID")
    return value.rstrip("/")


class AzureBotPlatform:
    def __init__(
        self,
        config,
        on_message,
        on_endpoint,
        on_state,
        on_diagnostic,
    ):
        self.config = config
        self.on_message, self.on_endpoint = on_message, on_endpoint
        self.on_state, self.on_diagnostic = on_state, on_diagnostic
        self.host = config.get("http_host") or "0.0.0.0"
        self.port = config.get("http_port") or 3978
        self.store = AzureBotStateStore(config)
        self.media_dir = (
            Path(config.get("media_dir") or self.store.workspace / "media")
            .expanduser()
            .resolve()
        )
        self.session = self.validator = self.runner = self.site = None
        self._attachment_session = self._attachment_resolver = None
        self.watchdog = None
        self.connected = self.accepting = False
        self._tasks = set()
        self._token_lock = asyncio.Lock()
        self._ref_lock = asyncio.Lock()
        self._token, self._token_expires = "", 0.0
        self._msal_app = None
        self._stopping = False

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        # Keep failed tasks until stop observes their error, not just until
        # their coroutine exits. Successful tasks no longer own resources.
        def settled(done):
            if not done.cancelled() and done.exception() is None:
                self._tasks.discard(done)

        task.add_done_callback(settled)
        return task

    async def _owned(self, coroutine):
        task = self._spawn(coroutine)
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._tasks.discard(task)

    async def _thread(self, operation, *args):
        return await self._owned(asyncio.to_thread(operation, *args))

    async def start(self):
        if not self.config.get("app_id") or not self.config.get(
            "app_password",
        ):
            raise ValueError("AZURE_CREDENTIALS_REQUIRED")
        self.store.begin()
        self.session = aiohttp.ClientSession()
        self.validator = AzureBotTokenValidator(
            self.config["app_id"],
            self.session,
        )
        app = web.Application()
        app.router.add_post("/api/messages", self._handle_messages)
        self.runner = web.AppRunner(app, shutdown_timeout=5)
        await self.runner.setup()
        await self._listen()
        self.watchdog = asyncio.create_task(self._watchdog())

    async def _listen(self):
        site = web.TCPSite(self.runner, self.host, self.port)
        self.site = site
        try:
            await site.start()
        except OSError:
            await site.stop()
            self.site = None
            await self.on_endpoint("degraded", False)
            await self.on_state("connecting")
            return
        self.site = site
        # Actual bound port (including ephemeral binding) belongs in the ACK.
        sockets = site._server.sockets
        if sockets:
            self.port = sockets[0].getsockname()[1]
        await self.on_endpoint("ready", False)
        self.accepting = self.connected = True
        await self.on_state("connected")

    async def _watchdog(self):
        while not self._stopping:
            await asyncio.sleep(10)
            if self._stopping:
                return
            try:
                if self.site is not None:
                    host = (
                        "127.0.0.1"
                        if self.host in ("0.0.0.0", "")
                        else "::1"
                        if self.host == "::"
                        else self.host
                    )
                    _, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, self.port),
                        3,
                    )
                    writer.close()
                    await writer.wait_closed()
                else:
                    await self._listen()
            except (OSError, asyncio.TimeoutError):
                self.accepting = self.connected = False
                await self.on_endpoint("degraded", False)
                await self.on_state("connecting")
                if self.site is not None:
                    await self.site.stop()
                    self.site = None
            except Exception:
                self.accepting = self.connected = False
                await self.on_state("failed")
                await self.on_diagnostic("AZURE_ENDPOINT_UPDATE_FAILED")
                raise

    async def stop(self):
        self._stopping = True
        self.accepting = self.connected = False
        if self.site is not None:
            await self.site.stop()
            self.site = None
        if self.watchdog is not None:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
            self.watchdog = None
        deadline = asyncio.get_running_loop().time() + 5
        while self._tasks:
            done, pending = await asyncio.wait(
                self._tasks,
                timeout=max(0, deadline - asyncio.get_running_loop().time()),
            )
            self._tasks.difference_update(done)
            for task in done:
                if not task.cancelled():
                    task.result()
            if pending:
                raise RuntimeError("AZURE_TASKS_STILL_OWNED")
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
        if self.session is not None:
            await self.session.close()
            self.session = None
        if self._attachment_session is not None:
            await self._attachment_session.close()
            self._attachment_session = None
        if self._attachment_resolver is not None:
            await self._attachment_resolver.close()
            self._attachment_resolver = None
        await self.on_endpoint("stopped", True)
        self.store.close()

    async def _handle_messages(self, request):
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            if not self.accepting:
                return web.Response(status=503)
            authentication = await self.validator.authenticate(
                request.headers.get("Authorization", ""),
            )
            if authentication is None:
                return web.Response(status=401)
            # Authentication above intentionally precedes any body read.
            try:
                activity = json.loads(await request.read())
                if not isinstance(activity, dict):
                    raise ValueError("invalid activity")
            except (ValueError, UnicodeError):
                return web.Response(status=400)
            if not self.validator.validates_activity(authentication, activity):
                return web.Response(status=403)
            try:
                _service_url(activity["serviceUrl"])
            except ValueError:
                return web.Response(status=403)
            if not self.accepting:
                return web.Response(status=503)
            if activity.get("type") == "message":
                accepted = await self._message(activity)
                return web.Response(status=200 if accepted else 503)
            # Conversation updates retain proactive references; invoke retains
            # the native acknowledgement without inventing an approval click.
            await self._remember(activity)
            if activity.get("type") == "invoke":
                return web.json_response({"status": 200})
            return web.Response(status=200)
        finally:
            self._tasks.discard(task)

    def _route(self, activity):
        sender = activity.get("from") or {}
        sender_id = sender.get("aadObjectId") or sender.get("id") or ""
        name = sender.get("name") or ""
        conversation = activity.get("conversation") or {}
        channel = activity.get("channelId") or "bot"
        conv_id = conversation.get("id") or ""
        session = f"azure_{channel}#{conv_id[-10:]}"
        display = f"{name or channel}#{sender_id[-6:]}"
        group = _group(activity)
        route = {
            "service_url": activity.get("serviceUrl", ""),
            "conversation_id": conv_id,
            "azure_channel_id": channel,
            "bot_channel_id": (activity.get("recipient") or {}).get("id")
            or self.config["app_id"],
            "is_group": group,
        }
        target = session if group else f"{session}:{display}"
        return sender_id, name, session, display, target, route

    async def _remember(self, activity):
        *_, target, route = self._route(activity)
        if route["conversation_id"]:

            async def persist():
                async with self._ref_lock:
                    await self._thread(self.store.remember, target, route)

            # Cancellation must not release the serialization lock while the
            # filesystem thread still owns the write.
            await self._owned(persist())
        return route

    async def _message(self, activity):
        sender, name, session, display, target, route = self._route(activity)
        if not sender or not route["conversation_id"]:
            return True
        bot_ids = {self.config["app_id"], route["bot_channel_id"]}
        mentions = [
            entity
            for entity in activity.get("entities", [])
            if isinstance(entity, dict)
            and entity.get("type") == "mention"
            and (entity.get("mentioned") or {}).get("id") in bot_ids
        ]
        if (
            route["is_group"]
            and self.config.get("require_mention")
            and not mentions
        ):
            return True
        text = activity.get("text") or ""
        for mention in mentions:
            if mention.get("text"):
                text = text.replace(mention["text"], "")
        parts = (
            [{"type": "text", "text": text.strip()}] if text.strip() else []
        )
        attachments = activity.get("attachments") or []
        if attachments:
            for attachment in attachments:
                part = await self._attachment(
                    attachment,
                    "",
                    route["service_url"],
                )
                if part:
                    parts.append(part)
        await self._remember(activity)
        if not parts:
            return True
        user = (
            "group"
            if route["is_group"] and self.config.get("share_session_in_group")
            else display
        )
        event_id = activity.get("id") or uuid.uuid4().hex
        return await self.on_message(
            {
                "event_id": (
                    f"{route['azure_channel_id']}:"
                    f"{route['conversation_id']}:{event_id}"
                ),
                "sender_id": user,
                "acl_sender_id": sender,
                "sender_name": name,
                "session_id": session,
                "route": route,
                "content_parts": parts,
                "meta": {
                    **route,
                    "user_name": name,
                    "activity_id": activity.get("id", ""),
                    "bot_mentioned": bool(mentions),
                    "is_dm": not route["is_group"],
                },
            },
        )

    async def _attachment(self, attachment, token, service_url=""):
        url = attachment.get("contentUrl")
        if not url:
            return None
        name = attachment.get("name") or "file"
        local = url
        if not (isinstance(url, str) and url.startswith("data:")):
            try:
                url = attachment_url(url)
                headers = {"Accept-Encoding": "identity"}
                if attachment_uses_token(url, service_url):
                    token = token or await self._get_bot_token()
                    headers["Authorization"] = f"Bearer {token}"
                if self._attachment_session is None:
                    self._attachment_resolver = PublicAttachmentResolver()
                    self._attachment_session = aiohttp.ClientSession(
                        connector=aiohttp.TCPConnector(
                            resolver=self._attachment_resolver,
                        ),
                        cookie_jar=aiohttp.DummyCookieJar(),
                    )
                async with self._attachment_session.get(
                    url,
                    headers=headers,
                    allow_redirects=False,
                    auto_decompress=False,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        raise ValueError("AZURE_ATTACHMENT_DOWNLOAD_FAILED")
                    if any(
                        encoding.strip().lower() != "identity"
                        for encoding in response.headers.getall(
                            "Content-Encoding",
                            [],
                        )
                    ) or (
                        response.content_length is not None
                        and response.content_length > DOWNLOAD_MAX_BYTES
                    ):
                        raise ValueError("AZURE_ATTACHMENT_DOWNLOAD_FAILED")
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(
                        64 * 1024,
                    ):
                        if len(data) + len(chunk) > DOWNLOAD_MAX_BYTES:
                            raise ValueError(
                                "AZURE_ATTACHMENT_DOWNLOAD_FAILED",
                            )
                        data.extend(chunk)
                    if not data:
                        raise ValueError("AZURE_ATTACHMENT_DOWNLOAD_FAILED")
                    safe = (
                        "".join(c for c in name if c.isalnum() or c in "-_.")
                        or "file"
                    )
                    self.media_dir.mkdir(parents=True, exist_ok=True)
                    path = self.media_dir / (uuid.uuid4().hex + "-" + safe)
                    await self._thread(path.write_bytes, data)
                    local = str(path)
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                OSError,
                ValueError,
            ):
                await self.on_diagnostic("AZURE_ATTACHMENT_DOWNLOAD_FAILED")
                return None
        mime = attachment.get("contentType", "")
        if mime.startswith("image/"):
            return {"type": "image", "image_url": local}
        if mime.startswith("video/"):
            return {"type": "video", "video_url": local}
        if any(
            mime.startswith(v)
            for v in ("audio/ogg", "audio/wav", "audio/webm", "audio/amr")
        ):
            return {
                "type": "audio",
                "data": local,
                "format": mime.split("/")[-1],
            }
        return {"type": "file", "file_url": local, "filename": name}

    async def _get_bot_token(self):
        return await self._owned(self._token_for_request())

    async def _token_for_request(self):
        async with self._token_lock:
            if self._stopping:
                raise AzureBotDeliveryError("NOT_CONNECTED")
            if self._token and self._token_expires > time.time() + 60:
                return self._token
            tenant = self.config.get("tenant_id") or "botframework.com"
            if any(c in tenant for c in "/\\?#@"):
                raise AzureBotDeliveryError("AZURE_TENANT_INVALID")

            def acquire():
                if self._msal_app is None:
                    self._msal_app = msal.ConfidentialClientApplication(
                        self.config["app_id"],
                        authority="https://login.microsoftonline.com/"
                        + tenant,
                        client_credential=self.config["app_password"],
                    )
                return self._msal_app.acquire_token_for_client(
                    scopes=["https://api.botframework.com/.default"],
                )

            try:
                result = await self._thread(acquire)
            except Exception as exc:
                raise AzureBotDeliveryError("AZURE_TOKEN_UNAVAILABLE") from exc
            if not isinstance(result, dict) or not result.get("access_token"):
                raise AzureBotDeliveryError("AZURE_TOKEN_UNAVAILABLE")
            self._token = result["access_token"]
            self._token_expires = time.time() + int(
                result.get("expires_in", 3600),
            )
            return self._token

    def resolve_target(self, target, meta):
        return self.store.resolve(target, meta)

    async def _post(self, url, payload, token):
        try:
            async with self.session.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status not in (200, 201, 202):
                    raise AzureBotDeliveryError(
                        "PLATFORM_SEND_REFUSED",
                        side_effect_possible=response.status >= 500,
                    )
                data = await response.read()
                return json.loads(data) if data else {}
        except AzureBotDeliveryError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise AzureBotDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc

    async def _outbound_attachment(self, part, base, token):
        kind = part["type"]
        field, mime, name = {
            "image": ("image_url", "image/png", "image.png"),
            "video": ("video_url", "video/mp4", "video.mp4"),
            "audio": ("data", "audio/mpeg", "audio.mp3"),
            "file": ("file_url", "application/octet-stream", "file"),
        }[kind]
        value = part[field]
        name = part.get("filename") or name
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https", "data"):
            return {
                "contentType": mime,
                "contentUrl": value,
                "name": name,
            }, False
        path = (
            Path(unquote(parsed.path) if parsed.scheme == "file" else value)
            .expanduser()
            .resolve()
        )
        if not any(
            path.is_relative_to(root)
            for root in (self.store.workspace, self.media_dir)
        ):
            raise AzureBotDeliveryError("MEDIA_PATH_OUTSIDE_WORKSPACE")
        raw = await self._thread(path.read_bytes)
        if len(raw) > UPLOAD_MAX_BYTES:
            lang = self.config.get("language") or "zh"
            lang = "zh" if lang.startswith("zh") else lang
            return {
                "_text": FILE_TOO_LARGE.get(lang, FILE_TOO_LARGE["en"]).format(
                    name=path.name,
                    size_kb=round(len(raw) / 1024),
                ),
            }, False
        mime = mimetypes.guess_type(path.name)[0] or mime
        encoded = base64.b64encode(raw).decode()
        try:
            result = await self._post(
                base + "/attachments",
                {"type": mime, "name": path.name, "originalBase64": encoded},
                token,
            )
        except AzureBotDeliveryError as exc:
            if exc.side_effect_possible:
                raise
            # A definitive HTTP rejection has no upload effect to duplicate.
            return {
                "contentType": mime,
                "contentUrl": f"data:{mime};base64,{encoded}",
                "name": path.name,
            }, False
        if not isinstance(result, dict) or not result.get("id"):
            raise AzureBotDeliveryError(
                "UPLOAD_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        service = base.split("/v3/conversations/", 1)[0]
        return {
            "contentType": mime,
            "contentUrl": service
            + "/v3/attachments/"
            + quote(str(result["id"]), safe="")
            + "/views/original",
            "name": path.name,
        }, True

    async def send_parts(self, route, parts, source):
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            return await self._send_parts(route, parts, source)
        finally:
            self._tasks.discard(task)

    async def _send_parts(self, route, parts, source):
        if not self.connected or self._stopping:
            raise AzureBotDeliveryError("NOT_CONNECTED")
        token = await self._get_bot_token()
        base = (
            _service_url(route["service_url"])
            + "/v3/conversations/"
            + quote(route["conversation_id"], safe="")
        )
        parts = list(parts)
        if getattr(source, "value", source) == "content_parts":
            body = "\n".join(
                p.get("text", "") for p in parts if p["type"] == "text"
            )
            media = [p for p in parts if p["type"] != "text"]
            for part in media:
                kind = part["type"]
                field = {
                    "image": "image_url",
                    "video": "video_url",
                    "file": "file_url",
                }.get(kind)
                if field and part.get(field):
                    body += f"\n[{kind.title()}: {part[field]}]"
                elif kind == "audio":
                    body += "\n[Audio]"
            parts = (
                [{"type": "text", "text": body.strip()}]
                if body.strip()
                else []
            ) + media
        receipts, effect = [], False
        try:
            for part in parts:
                payload = {
                    "type": "message",
                    "from": {"id": route["bot_channel_id"]},
                }
                if part["type"] in ("text", "refusal"):
                    payload["text"] = (
                        part.get("text") or part.get("refusal") or ""
                    )
                else:
                    attachment, uploaded = await self._outbound_attachment(
                        part,
                        base,
                        token,
                    )
                    effect |= uploaded
                    if "_text" in attachment:
                        payload["text"] = attachment["_text"]
                    else:
                        payload["attachments"] = [attachment]
                receipt = await self._post(
                    base + "/activities",
                    payload,
                    token,
                )
                effect = True
                receipts.append(
                    receipt.get("id", "") if isinstance(receipt, dict) else "",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, AzureBotDeliveryError):
                if effect:
                    exc.side_effect_possible = True
                raise
            raise AzureBotDeliveryError(
                "PLATFORM_PARTIAL_SEND" if effect else "MEDIA_PREPARE_FAILED",
                side_effect_possible=effect,
            ) from exc
        return {"activity_ids": json.dumps(receipts)}
