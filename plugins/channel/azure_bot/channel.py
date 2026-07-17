# -*- coding: utf-8 -*-
# pylint: disable=too-many-instance-attributes
"""Azure Bot Service channel: Bot Framework webhook + REST API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import aiohttp
from aiohttp import web

from qwenpaw.app.channels.base import (
    BaseChannel,
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    OnReplySent,
    ProcessHandler,
    TextContent,
    VideoContent,
)
from .auth import AzureBotTokenValidator
from .constants import (
    AZURE_BOT_DEFAULT_PORT,
    AZURE_BOT_FRAMEWORK_SCOPE,
    AZURE_BOT_WATCHDOG_INTERVAL_S,
)

logger = logging.getLogger(__name__)

# Type alias for config
AzureBotChannelConfig = Any


class AzureBotChannel(BaseChannel):
    """Azure Bot Service channel via Bot Framework webhook.

    Runs an independent aiohttp HTTP server on a dedicated port
    (default 3978) to receive Activity payloads from Azure Bot
    Service. Sends replies via the Bot Framework REST API.

    Supports Teams, Slack, Web Chat, and other Azure Bot channels.
    """

    channel = "azure_bot"
    uses_manager_queue = True

    # Max file size for Upload API (bytes). The API enforces
    # 262144 bytes on the JSON body; base64 + JSON overhead
    # makes the safe raw file limit ~180KB.
    _UPLOAD_MAX_FILE_SIZE = 180_000

    _FILE_TOO_LARGE_I18N = {
        "zh": ("⚠️ 文件「{name}」（{size_kb}KB）" "超过附件大小限制（180KB），无法发送。"),
        "en": (
            '⚠️ File "{name}" ({size_kb}KB) exceeds '
            "the attachment size limit (180KB) "
            "and cannot be sent."
        ),
        "id": (
            '⚠️ File "{name}" ({size_kb}KB) melebihi '
            "batas ukuran lampiran (180KB) "
            "dan tidak dapat dikirim."
        ),
        "ru": ("⚠️ Файл «{name}» ({size_kb}KB) " "превышает лимит (180KB)."),
    }

    def _file_too_large_msg(
        self,
        name: str,
        size_bytes: int,
    ) -> str:
        """Build i18n file-too-large message."""
        lang = self._language
        if lang.startswith("zh"):
            lang = "zh"
        if lang not in self._FILE_TOO_LARGE_I18N:
            lang = "en"
        size_kb = round(size_bytes / 1024)
        return self._FILE_TOO_LARGE_I18N[lang].format(
            name=name,
            size_kb=size_kb,
        )

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        app_id: str,
        app_password: str,
        tenant_id: str,
        http_host: str = "0.0.0.0",
        http_port: int = AZURE_BOT_DEFAULT_PORT,
        bot_prefix: str = "",
        media_dir: str = "",
        workspace_dir: Optional[Path] = None,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        no_text_debounce: bool = True,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[List[str]] = None,
        deny_message: str = "",
        require_mention: bool = False,
        share_session_in_group: bool = False,
        access_control_dm: bool = False,
        access_control_group: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            no_text_debounce=no_text_debounce,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
            access_control_dm=access_control_dm,
            access_control_group=access_control_group,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self._app_id = app_id
        self._app_password = app_password
        self._tenant_id = tenant_id
        self._http_host = http_host
        self._http_port = http_port
        self._share_session_in_group = share_session_in_group

        # HTTP server state (aiohttp, like OneBot)
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        # JWT validator for inbound requests
        self._token_validator = AzureBotTokenValidator(
            app_id=app_id,
            tenant_id=tenant_id,
        )

        # Outbound HTTP session for REST API calls
        self._http_session: Optional[aiohttp.ClientSession] = None

        # MSAL token cache for outbound calls
        self._msal_app: Any = None
        self._bot_token: Optional[str] = None
        self._bot_token_expires_at: float = 0.0

        # Conversation references for proactive messaging
        self._conversation_refs: Dict[str, Dict[str, Any]] = {}

        # Bot's own channel ID (learned from incoming activities)
        self._bot_channel_id: Optional[str] = None

        # Workspace dir for persistence
        self._workspace_dir: Optional[Path] = (
            Path(workspace_dir) if workspace_dir else None
        )

        # Media directory for downloaded attachments
        if media_dir:
            self._media_dir = Path(media_dir).expanduser()
        elif self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        else:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            self._media_dir = DEFAULT_MEDIA_DIR

        # Watchdog
        self._watchdog_task: Optional[asyncio.Task] = None
        self._stopping: bool = False

        # Background refs persistence (non-blocking, serialized writes)
        self._save_lock: asyncio.Lock = asyncio.Lock()
        self._save_tasks: set = set()

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "AzureBotChannel":
        allow_from_env = os.getenv(
            "AZURE_BOT_ALLOW_FROM",
            "",
        )
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=(
                os.getenv(
                    "AZURE_BOT_CHANNEL_ENABLED",
                    "0",
                )
                == "1"
            ),
            app_id=os.getenv("AZURE_BOT_APP_ID", ""),
            app_password=os.getenv(
                "AZURE_BOT_APP_PASSWORD",
                "",
            ),
            tenant_id=os.getenv(
                "AZURE_BOT_TENANT_ID",
                "",
            ),
            http_host=os.getenv(
                "AZURE_BOT_HTTP_HOST",
                "0.0.0.0",
            ),
            http_port=int(
                os.getenv(
                    "AZURE_BOT_HTTP_PORT",
                    str(AZURE_BOT_DEFAULT_PORT),
                ),
            ),
            bot_prefix=os.getenv(
                "AZURE_BOT_BOT_PREFIX",
                "",
            ),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv(
                "AZURE_BOT_DM_POLICY",
                "open",
            ),
            group_policy=os.getenv(
                "AZURE_BOT_GROUP_POLICY",
                "open",
            ),
            allow_from=allow_from,
            deny_message=os.getenv(
                "AZURE_BOT_DENY_MESSAGE",
                "",
            ),
            require_mention=(
                os.getenv(
                    "AZURE_BOT_REQUIRE_MENTION",
                    "0",
                )
                == "1"
            ),
            share_session_in_group=(
                os.getenv(
                    "AZURE_BOT_SHARE_SESSION_IN_GROUP",
                    "0",
                )
                == "1"
            ),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: AzureBotChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        no_text_debounce: bool = True,
        filter_thinking: bool = False,
        workspace_dir: Optional[Path] = None,
    ) -> "AzureBotChannel":
        return cls(
            process=process,
            enabled=getattr(config, "enabled", False),
            app_id=getattr(config, "app_id", "") or "",
            app_password=getattr(config, "app_password", "") or "",
            tenant_id=getattr(config, "tenant_id", "") or "",
            http_host=getattr(config, "http_host", "") or "0.0.0.0",
            http_port=(
                getattr(config, "http_port", None) or AZURE_BOT_DEFAULT_PORT
            ),
            bot_prefix=getattr(config, "bot_prefix", "") or "",
            media_dir=getattr(config, "media_dir", "") or "",
            workspace_dir=workspace_dir,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            no_text_debounce=no_text_debounce,
            filter_thinking=filter_thinking,
            dm_policy=getattr(config, "dm_policy", "") or "open",
            group_policy=getattr(config, "group_policy", "") or "open",
            allow_from=getattr(config, "allow_from", None) or [],
            deny_message=getattr(config, "deny_message", "") or "",
            require_mention=getattr(config, "require_mention", False),
            share_session_in_group=bool(
                getattr(
                    config,
                    "share_session_in_group",
                    False,
                ),
            ),
            access_control_dm=bool(
                getattr(
                    config,
                    "access_control_dm",
                    False,
                ),
            ),
            access_control_group=bool(
                getattr(
                    config,
                    "access_control_group",
                    False,
                ),
            ),
        )

    # ------------------------------------------------------------------
    # Lifecycle: start / stop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("azure_bot channel disabled")
            return
        if not self._app_id or not self._app_password:
            logger.warning(
                "azure_bot: app_id or app_password not "
                "configured, channel will not start",
            )
            return

        self._stopping = False
        self._http_session = aiohttp.ClientSession()
        await asyncio.to_thread(self._load_refs_from_disk)
        await self._start_http_server()
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(),
        )
        logger.info(
            "azure_bot channel started on %s:%s",
            self._http_host,
            self._http_port,
        )

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stopping = True
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        await self._stop_http_server()
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
        # Drain pending background refs saves so the last write is
        # not lost on shutdown. A generous timeout is a safety valve so a
        # pathological disk stall cannot hang shutdown indefinitely.
        if self._save_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *list(self._save_tasks),
                        return_exceptions=True,
                    ),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "azure_bot: pending refs save timed out on stop",
                )
        logger.info("azure_bot channel stopped")

    # ------------------------------------------------------------------
    # HTTP server management (like OneBot pattern)
    # ------------------------------------------------------------------

    async def _start_http_server(self) -> None:
        """Create and start the aiohttp HTTP server."""
        self._app = web.Application()
        self._app.router.add_post(
            "/api/messages",
            self._handle_incoming,
        )
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            self._http_host,
            self._http_port,
        )
        try:
            await self._site.start()
            logger.info(
                "azure_bot: HTTP server listening on %s:%s/api/messages",
                self._http_host,
                self._http_port,
            )
        except OSError:
            logger.warning(
                "azure_bot: port %s:%s in use, watchdog will retry",
                self._http_host,
                self._http_port,
            )
            self._site = None
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None
            self._app = None

    async def _stop_http_server(self) -> None:
        """Tear down the HTTP server."""
        if self._site:
            try:
                await self._site.stop()
            except Exception:
                pass
            self._site = None
        if self._runner:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None
        self._app = None

    async def _watchdog_loop(self) -> None:
        """Periodically check server health."""
        while not self._stopping:
            await asyncio.sleep(
                AZURE_BOT_WATCHDOG_INTERVAL_S,
            )
            if self._stopping:
                break
            if not await self._is_server_healthy():
                logger.warning(
                    "azure_bot: watchdog detected server "
                    "not healthy, restarting...",
                )
                try:
                    await self._stop_http_server()
                    await self._start_http_server()
                    logger.info(
                        "azure_bot: watchdog restarted server OK",
                    )
                except Exception:
                    logger.exception(
                        "azure_bot: watchdog failed to restart",
                    )

    async def _is_server_healthy(self) -> bool:
        """Check if HTTP server is accepting connections."""
        if self._site is None:
            return False
        probe_host = (
            "127.0.0.1" if self._http_host == "0.0.0.0" else self._http_host
        )
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    probe_host,
                    self._http_port,
                ),
                timeout=3.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    # ------------------------------------------------------------------
    # Inbound: handle POST /api/messages
    # ------------------------------------------------------------------

    async def _handle_incoming(
        self,
        request: web.Request,
    ) -> web.Response:
        """Handle incoming Activity from Azure Bot Service."""
        # 1. Validate JWT *before* reading the request body, so an
        # unauthenticated request is rejected without buffering its
        # (potentially large) payload into memory. The auth header is
        # available without touching the body stream.
        auth_header = request.headers.get(
            "Authorization",
            "",
        )
        if not await self._token_validator.validate_auth_header(
            auth_header,
        ):
            logger.warning(
                "azure_bot: JWT validation failed",
            )
            return web.Response(
                status=401,
                text="Unauthorized",
            )

        # 2. Read and parse activity (only for authenticated requests)
        try:
            raw_body = await request.read()
        except Exception:
            raw_body = b""

        try:
            activity = json.loads(raw_body)
        except Exception:
            return web.Response(
                status=400,
                text="Bad Request",
            )

        activity_type = activity.get("type", "")

        # 3. Store conversation reference
        self._store_conversation_reference(activity)

        # 4. Dispatch by activity type
        if activity_type == "message":
            await self._on_message(activity)
        elif activity_type == "conversationUpdate":
            await self._on_conversation_update(activity)
        elif activity_type == "invoke":
            result = await self._on_invoke(activity)
            return web.json_response(
                result,
                status=200,
            )
        else:
            logger.debug(
                "azure_bot: ignoring activity type=%s",
                activity_type,
            )

        return web.Response(status=200)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    # Audio MIME types that should be treated as voice
    # (sent to speech-to-text pipeline via AudioContent).
    _VOICE_MIME_PREFIXES = (
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "audio/amr",
    )

    async def _on_message(
        self,
        activity: dict,
    ) -> None:
        """Handle incoming message activity."""
        text = activity.get("text", "") or ""
        sender = activity.get("from", {})
        sender_id = sender.get(
            "aadObjectId",
        ) or sender.get("id", "")
        sender_name = sender.get("name", "")
        conversation = activity.get("conversation", {})
        conversation_id = conversation.get("id", "")
        # Detect group: Teams uses conversationType,
        # standard Bot Framework uses isGroup,
        # Slack uses channelData.event.channel_type.
        conv_type = conversation.get(
            "conversationType",
            "",
        )
        is_group = (
            conv_type in ("channel", "groupChat")
            or conversation.get("isGroup") is True
        )
        if not is_group:
            channel_data = activity.get(
                "channelData",
                {},
            )
            slack_msg = channel_data.get(
                "SlackMessage",
                {},
            )
            slack_event = slack_msg.get("event", {})
            if slack_event.get("channel_type") in (
                "channel",
                "group",
            ):
                is_group = True
        service_url = activity.get("serviceUrl", "")

        # Strip bot @mention from text if present
        text = self._strip_bot_mention(text, activity)

        # Check group mention requirement
        if is_group and self.require_mention:
            if not self._is_bot_mentioned(activity):
                return

        # Build content_parts
        content_parts: list = []
        if text.strip():
            content_parts.append(
                TextContent(
                    type=ContentType.TEXT,
                    text=text.strip(),
                ),
            )

        # Handle attachments
        attachments = activity.get("attachments", [])
        if attachments:
            token = await self._get_bot_token() or ""
            for att in attachments:
                part = await self._parse_attachment_async(
                    att,
                    token,
                )
                if part is not None:
                    content_parts.append(part)

        if not content_parts:
            return

        # Resolve bot_channel_id from this activity's
        # recipient field (per-channel, not global)
        recipient = activity.get("recipient", {})
        activity_bot_id = recipient.get("id", "")

        meta = {
            "user_id": sender_id,
            "user_name": sender_name,
            "conversation_id": conversation_id,
            "azure_channel_id": activity.get(
                "channelId",
                "bot",
            ),
            "is_group": is_group,
            "is_dm": not is_group,
            "service_url": service_url,
            "activity_id": activity.get("id", ""),
            "bot_channel_id": activity_bot_id,
        }

        # Display sender: name#last6 or channelId#last6
        suffix = sender_id[-6:] if len(sender_id) >= 6 else sender_id
        azure_channel_id = meta.get(
            "azure_channel_id",
            "bot",
        )
        display_sender = (
            f"{sender_name}#{suffix}"
            if sender_name
            else f"{azure_channel_id}#{suffix}"
        )

        native = {
            "channel_id": self.channel,
            "sender_id": (
                "group"
                if (is_group and self._share_session_in_group)
                else display_sender
            ),
            "acl_sender_id": sender_id,
            "content_parts": content_parts,
            "meta": meta,
        }

        if self._enqueue is not None:
            self._enqueue(native)

    async def _download_attachment(
        self,
        url: str,
        token: str,
        filename: str,
    ) -> Optional[str]:
        """Download attachment to local media_dir.

        Bot Framework contentUrl requires Bearer auth.
        Returns local file path on success, None on failure.
        """
        if not url or not self._http_session:
            return None
        try:
            headers = {"Authorization": f"Bearer {token}"}
            async with self._http_session.get(
                url,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "azure_bot download attachment "
                        "failed: status=%d url=%s",
                        resp.status,
                        url[:120],
                    )
                    return None
                data = await resp.read()
                if not data:
                    return None
            self._media_dir.mkdir(
                parents=True,
                exist_ok=True,
            )
            safe_name = (
                "".join(c for c in filename if c.isalnum() or c in "-_.")
                or "file"
            )
            path = self._media_dir / safe_name
            # Avoid name collision
            if path.exists():
                stem = path.stem
                suffix = path.suffix
                path = self._media_dir / (f"{stem}_{int(time.time())}{suffix}")
            await asyncio.to_thread(
                path.write_bytes,
                data,
            )
            return str(path)
        except Exception:
            logger.exception(
                "azure_bot _download_attachment failed",
            )
            return None

    async def _parse_attachment_async(
        self,
        att: dict,
        token: str,
    ) -> Any:
        """Parse and download a Bot Framework attachment.

        Downloads to local storage, returns content part
        (ImageContent, AudioContent, FileContent) or None.
        """
        content_type = att.get("contentType", "")
        content_url = att.get("contentUrl", "")
        name = att.get("name", "") or "file"

        if not content_url:
            return None

        # Download to local
        local_path = await self._download_attachment(
            content_url,
            token,
            name,
        )
        if not local_path:
            # Fallback: pass URL directly (may not work
            # for agent but better than dropping)
            local_path = content_url

        # Image
        if content_type.startswith("image/"):
            return ImageContent(
                type=ContentType.IMAGE,
                image_url=local_path,
            )

        # Video
        if content_type.startswith("video/"):
            return VideoContent(
                type=ContentType.VIDEO,
                video_url=local_path,
            )

        # Audio: voice-like formats -> AudioContent
        if content_type.startswith("audio/"):
            if any(
                content_type.startswith(p) for p in self._VOICE_MIME_PREFIXES
            ):
                return AudioContent(
                    type=ContentType.AUDIO,
                    data=local_path,
                    format=content_type.split("/")[-1],
                )
            return FileContent(
                type=ContentType.FILE,
                file_url=local_path,
                filename=name or None,
            )

        # Everything else -> file
        return FileContent(
            type=ContentType.FILE,
            file_url=local_path,
            filename=name or None,
        )

    async def _on_conversation_update(
        self,
        activity: dict,  # pylint: disable=unused-argument
    ) -> None:
        """Handle conversationUpdate (e.g. bot added to chat)."""

    async def _on_invoke(
        self,
        activity: dict,  # pylint: disable=unused-argument
    ) -> dict:
        """Handle invoke activities (e.g. adaptive card actions)."""
        return {"status": 200}

    # ------------------------------------------------------------------
    # AgentRequest construction
    # ------------------------------------------------------------------

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> Any:
        """Build AgentRequest from native dict."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = dict(payload.get("meta") or {})
        session_id = self.resolve_session_id(
            sender_id,
            meta,
        )
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        setattr(request, "channel_meta", meta)
        return request

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Map sender to session_id.

        Format: azure_{channelId}#{conv_id_last10}
        Same for both DM and group (group shared via
        sender_id="group", not session_id).
        """
        meta = channel_meta or {}
        azure_channel = meta.get(
            "azure_channel_id",
            "bot",
        )
        conv_id = meta.get("conversation_id", "")
        conv_suffix = conv_id[-10:] if len(conv_id) >= 10 else conv_id
        return f"azure_{azure_channel}#{conv_suffix}"

    # ------------------------------------------------------------------
    # Outbound: send messages via Bot Framework REST API
    # ------------------------------------------------------------------

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a text message via Bot Framework REST."""
        if not self.enabled:
            return
        meta = meta or {}
        service_url = meta.get("service_url", "")
        conversation_id = meta.get(
            "conversation_id",
            "",
        )

        # Resolve bot_channel_id: meta > ref > global > app_id
        bot_id = meta.get("bot_channel_id", "")

        if not service_url or not conversation_id:
            ref = self._find_ref(to_handle, meta)
            if ref:
                service_url = ref.get(
                    "service_url",
                    "",
                )
                conversation_id = ref.get(
                    "conversation_id",
                    "",
                )
                if not bot_id:
                    bot_id = ref.get(
                        "bot_channel_id",
                        "",
                    )

        if not bot_id:
            bot_id = self._bot_channel_id or self._app_id

        if not service_url or not conversation_id:
            logger.warning(
                "azure_bot send: no service_url or "
                "conversation_id for to_handle=%s",
                to_handle,
            )
            return

        token = await self._get_bot_token()
        if not token:
            logger.warning(
                "azure_bot send: failed to get bot token",
            )
            return

        url = (
            f"{service_url.rstrip('/')}"
            f"/v3/conversations/"
            f"{conversation_id}/activities"
        )
        payload = {
            "type": "message",
            "from": {
                "id": bot_id,
            },
            "text": text,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            async with self._http_session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status not in (200, 201, 202):
                    body = await resp.text()
                    logger.warning(
                        "azure_bot send: failed status=%d body=%s",
                        resp.status,
                        body[:200],
                    )
        except Exception:
            logger.exception(
                "azure_bot send: error sending message",
            )

    async def _resolve_attachment_for_part(
        self,
        part: Any,
        part_type: Any,
        service_url: str,
        conversation_id: str,
        token: str,
    ) -> Optional[Dict[str, Any]]:
        """Resolve attachment dict from a content part."""
        if part_type == ContentType.IMAGE:
            url = getattr(part, "image_url", None)
            if url:
                return await self._upload_and_get_attachment(
                    url,
                    service_url,
                    conversation_id,
                    token,
                    "image/png",
                    "image.png",
                )
        elif part_type == ContentType.VIDEO:
            url = getattr(part, "video_url", None)
            if url:
                return await self._upload_and_get_attachment(
                    url,
                    service_url,
                    conversation_id,
                    token,
                    "video/mp4",
                    "video.mp4",
                )
        elif part_type == ContentType.AUDIO:
            url = getattr(part, "data", None)
            if url:
                return await self._upload_and_get_attachment(
                    url,
                    service_url,
                    conversation_id,
                    token,
                    "audio/mpeg",
                    "audio.mp3",
                )
        elif part_type == ContentType.FILE:
            url = getattr(part, "file_url", None)
            name = getattr(part, "filename", None) or "file"
            if url:
                return await self._upload_and_get_attachment(
                    url,
                    service_url,
                    conversation_id,
                    token,
                    "application/octet-stream",
                    name,
                )
        return None

    # ------------------------------------------------------------------
    # Media sending via Bot Framework REST API
    # ------------------------------------------------------------------

    async def send_media(
        self,
        to_handle: str,
        part: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a media attachment via Bot Framework."""
        if not self.enabled:
            return
        meta = meta or {}
        service_url = meta.get("service_url", "")
        conversation_id = meta.get(
            "conversation_id",
            "",
        )

        # Resolve bot_channel_id: meta > ref > global > app_id
        bot_id = meta.get("bot_channel_id", "")

        if not service_url or not conversation_id:
            ref = self._find_ref(to_handle, meta)
            if ref:
                service_url = ref.get(
                    "service_url",
                    "",
                )
                conversation_id = ref.get(
                    "conversation_id",
                    "",
                )
                if not bot_id:
                    bot_id = ref.get(
                        "bot_channel_id",
                        "",
                    )

        if not bot_id:
            bot_id = self._bot_channel_id or self._app_id

        if not service_url or not conversation_id:
            logger.warning(
                "azure_bot send_media: no service_url "
                "or conversation_id, to_handle=%s",
                to_handle,
            )
            return

        token = await self._get_bot_token()
        if not token:
            return

        part_type = getattr(part, "type", None)
        attachment = await self._resolve_attachment_for_part(
            part,
            part_type,
            service_url,
            conversation_id,
            token,
        )

        if not attachment:
            logger.warning(
                "azure_bot send_media: no attachment resolved, part_type=%s",
                part_type,
            )
            return

        # Handle file-too-large: send text fallback
        if attachment.get("_too_large"):
            msg = self._file_too_large_msg(
                attachment["name"],
                attachment["size"],
            )
            await self.send(
                to_handle,
                msg,
                meta,
            )
            return

        url = (
            f"{service_url.rstrip('/')}"
            f"/v3/conversations/"
            f"{conversation_id}/activities"
        )
        payload = {
            "type": "message",
            "from": {
                "id": bot_id,
            },
            "attachments": [attachment],
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            async with self._http_session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status not in (200, 201, 202):
                    body = await resp.text()
                    logger.warning(
                        "azure_bot send_media: failed status=%d body=%s",
                        resp.status,
                        body[:200],
                    )
        except Exception:
            logger.exception(
                "azure_bot send_media: error",
            )

    def _make_attachment(
        self,
        url_or_path: str,
        default_content_type: str,
        default_name: str,
    ) -> Optional[Dict[str, Any]]:
        # Strip file:// URI scheme if present
        actual = url_or_path
        if actual.startswith("file:///"):
            actual = unquote(actual[7:])
        elif actual.startswith("file://"):
            actual = unquote(actual[7:])

        path = Path(actual)
        if path.is_file():
            try:
                mime = (
                    mimetypes.guess_type(str(path))[0] or default_content_type
                )
                with open(path, "rb") as f:
                    raw = f.read()
                data = base64.b64encode(raw).decode()
                return {
                    "contentType": mime,
                    "contentUrl": (f"data:{mime};base64,{data}"),
                    "name": path.name,
                }
            except Exception:
                logger.warning(
                    "azure_bot: failed to read local file %s",
                    url_or_path,
                )
                return None

        # Otherwise treat as URL
        return {
            "contentType": default_content_type,
            "contentUrl": url_or_path,
            "name": default_name,
        }

    async def _upload_and_get_attachment(
        self,
        url_or_path: str,
        service_url: str,
        conversation_id: str,
        token: str,
        default_content_type: str,
        default_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Upload local file via Bot Framework Upload API.

        Returns attachment dict with public contentUrl.
        Falls back to _make_attachment (base64) on failure.
        """
        # Strip file:// URI scheme if present
        actual = url_or_path
        if actual.startswith("file:///"):
            actual = unquote(actual[7:])
        elif actual.startswith("file://"):
            actual = unquote(actual[7:])

        path = Path(actual)
        if not path.is_file():
            # It's a URL, use directly
            return {
                "contentType": default_content_type,
                "contentUrl": url_or_path,
                "name": default_name,
            }

        mime = mimetypes.guess_type(str(path))[0] or default_content_type
        try:
            raw = await asyncio.to_thread(path.read_bytes)
        except Exception:
            logger.warning(
                "azure_bot: failed to read file %s",
                url_or_path,
            )
            return None

        # Check file size limit
        if len(raw) > self._UPLOAD_MAX_FILE_SIZE:
            logger.info(
                "azure_bot: file %s too large "
                "(%d bytes), sending text fallback",
                path.name,
                len(raw),
            )
            # Return a special marker so send_media
            # can send a text message instead
            return {
                "_too_large": True,
                "name": path.name,
                "size": len(raw),
            }

        # Upload via Bot Framework API
        upload_url = (
            f"{service_url.rstrip('/')}"
            f"/v3/conversations/"
            f"{conversation_id}/attachments"
        )
        upload_body = {
            "type": mime,
            "name": path.name,
            "originalBase64": base64.b64encode(
                raw,
            ).decode(),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            async with self._http_session.post(
                upload_url,
                json=upload_body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status in (200, 201, 202):
                    data = await resp.json()
                    att_id = data.get("id", "")
                    if att_id:
                        content_url = (
                            f"{service_url.rstrip('/')}"
                            f"/v3/attachments/"
                            f"{att_id}/views/original"
                        )
                        return {
                            "contentType": mime,
                            "contentUrl": content_url,
                            "name": path.name,
                        }
                else:
                    body = await resp.text()
                    logger.warning(
                        "azure_bot upload: failed status=%d body=%s",
                        resp.status,
                        body[:200],
                    )
        except Exception:
            logger.warning(
                "azure_bot upload: error, falling back to base64",
                exc_info=True,
            )

        # Fallback to base64 inline (offload sync file read to a thread)
        return await asyncio.to_thread(
            self._make_attachment,
            url_or_path,
            default_content_type,
            default_name,
        )

    # ------------------------------------------------------------------
    # Token management (MSAL client credentials)
    # ------------------------------------------------------------------

    async def _get_bot_token(self) -> Optional[str]:
        """Get a valid bot token for outbound calls."""
        now = time.time()
        if self._bot_token and self._bot_token_expires_at > now + 60:
            return self._bot_token

        try:
            import msal  # type: ignore

            if self._msal_app is None:
                authority = (
                    "https://login.microsoftonline.com/" f"{self._tenant_id}"
                )
                self._msal_app = msal.ConfidentialClientApplication(
                    self._app_id,
                    authority=authority,
                    client_credential=(self._app_password),
                )

            result = self._msal_app.acquire_token_for_client(
                scopes=[AZURE_BOT_FRAMEWORK_SCOPE],
            )
            if result and "access_token" in result:
                self._bot_token = result["access_token"]
                expires_in = result.get(
                    "expires_in",
                    3600,
                )
                self._bot_token_expires_at = now + expires_in
                return self._bot_token
            else:
                # Log only the error code at warning level. The full
                # error_description may carry tenant/client/config
                # details, so keep it at debug level only.
                error_code = result.get(
                    "error",
                    "unknown_error",
                )
                logger.warning(
                    "azure_bot: MSAL token acquisition failed: %s",
                    error_code,
                )
                logger.debug(
                    "azure_bot: MSAL error detail: %s",
                    result.get("error_description", ""),
                )
                return None
        except Exception:
            logger.exception(
                "azure_bot: error acquiring bot token",
            )
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_ref(
        self,
        to_handle: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Find conversation ref by to_handle + meta.

        Group: key = session_id (shared).
        DM: key = session_id:user_id (per-user).
        Tries exact match, then session_id-only fallback
        (for group isolated sessions where to_handle =
        session_id:user_id but ref stored as session_id),
        then build from meta, then partial match.
        """
        # 1. Direct key match (DM: session_id:user_id,
        #    group shared: session_id)
        ref = self._conversation_refs.get(to_handle)
        if ref:
            return ref

        # 2. Group fallback: try session_id part only
        #    (to_handle may be session_id:user_id but
        #    group ref stored as session_id)
        if ":" in to_handle:
            sid_part = to_handle.split(":", 1)[0]
            ref = self._conversation_refs.get(sid_part)
            if ref:
                return ref

        # 3. Build key from meta
        m = meta or {}
        conv_id = m.get("conversation_id", "")
        azure_ch = m.get("azure_channel_id", "bot")
        if conv_id:
            conv_suffix = conv_id[-10:] if len(conv_id) >= 10 else conv_id
            session_id = f"azure_{azure_ch}#{conv_suffix}"
            # Try group key first (session_id only)
            ref = self._conversation_refs.get(session_id)
            if ref:
                return ref
            # Try DM key (session_id:to_handle)
            key = f"{session_id}:{to_handle}"
            ref = self._conversation_refs.get(key)
            if ref:
                return ref

        # 4. Partial match: find any ref containing
        #    to_handle or session_id part in key
        sid_part = (
            to_handle.split(":", 1)[0] if ":" in to_handle else to_handle
        )
        for k, v in self._conversation_refs.items():
            if to_handle in k or sid_part in k:
                return v
        return None

    def _store_conversation_reference(
        self,
        activity: dict,
    ) -> None:
        """Store conversation reference and persist.

        Group chat: key = session_id (shared, one entry per
        conversation since all users share service_url /
        conversation_id / bot_channel_id).
        DM: key = session_id:user_id (per-user, avoids
        collision when different conversations share suffix).
        """
        sender = activity.get("from", {})
        sender_id = sender.get(
            "aadObjectId",
        ) or sender.get("id", "")
        conversation = activity.get("conversation", {})
        conversation_id = conversation.get("id", "")
        service_url = activity.get("serviceUrl", "")
        azure_channel_id = activity.get(
            "channelId",
            "bot",
        )

        # Learn bot's own channel ID from recipient field
        recipient = activity.get("recipient", {})
        if recipient.get("id"):
            self._bot_channel_id = recipient["id"]

        if sender_id and conversation_id and service_url:
            # Detect group: same logic as _on_message
            conv_type = conversation.get(
                "conversationType",
                "",
            )
            is_group = (
                conv_type in ("channel", "groupChat")
                or conversation.get("isGroup") is True
            )
            if not is_group:
                channel_data = activity.get(
                    "channelData",
                    {},
                )
                slack_msg = channel_data.get(
                    "SlackMessage",
                    {},
                )
                slack_event = slack_msg.get(
                    "event",
                    {},
                )
                if slack_event.get(
                    "channel_type",
                ) in ("channel", "group"):
                    is_group = True

            conv_suffix = (
                conversation_id[-10:]
                if len(conversation_id) >= 10
                else conversation_id
            )
            prefix = f"azure_{azure_channel_id}"
            session_id = f"{prefix}#{conv_suffix}"

            # Group: key = session_id only (shared)
            # DM: key = session_id:user_id (per-user)
            if is_group:
                key = session_id
            else:
                sender_suffix = (
                    sender_id[-6:] if len(sender_id) >= 6 else sender_id
                )
                sender_name_val = sender.get("name", "")
                display_user = (
                    f"{sender_name_val}#{sender_suffix}"
                    if sender_name_val
                    else f"{azure_channel_id}#{sender_suffix}"
                )
                key = f"{session_id}:{display_user}"

            self._conversation_refs[key] = {
                "service_url": service_url,
                "conversation_id": conversation_id,
                "azure_channel_id": azure_channel_id,
                "bot_channel_id": self._bot_channel_id,
                "is_group": is_group,
            }
            self._schedule_save_refs()

    def _refs_store_path(self) -> Path:
        """Path to persist conversation refs."""
        if self._workspace_dir:
            return self._workspace_dir / "azure_bot_refs.json"
        from qwenpaw.constant import WORKING_DIR

        return WORKING_DIR / "azure_bot_refs.json"

    def _load_refs_from_disk(self) -> None:
        """Load conversation refs from disk."""
        path = self._refs_store_path()
        if not path.is_file():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        self._conversation_refs[k] = v
                        # Restore bot_channel_id
                        if not self._bot_channel_id and v.get(
                            "bot_channel_id",
                        ):
                            self._bot_channel_id = v["bot_channel_id"]
        except Exception:
            logger.debug(
                "azure_bot: load refs from %s failed",
                path,
                exc_info=True,
            )

    def _save_refs_to_disk(self) -> None:
        """Persist conversation refs to disk."""
        path = self._refs_store_path()
        try:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    self._conversation_refs,
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            logger.debug(
                "azure_bot: save refs to %s failed",
                path,
                exc_info=True,
            )

    def _schedule_save_refs(self) -> None:
        """Schedule a non-blocking, serialized refs persistence.

        The sync disk write runs in a worker thread so the event loop
        is never blocked, and writes are serialized via a lock to avoid
        concurrent writers corrupting the JSON file. Falls back to a
        direct sync write when no event loop is running (e.g. tests).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._save_refs_to_disk()
            return
        task = loop.create_task(self._save_refs_async())
        self._save_tasks.add(task)
        task.add_done_callback(self._save_tasks.discard)

    async def _save_refs_async(self) -> None:
        """Persist refs off the event loop, serialized by a lock."""
        async with self._save_lock:
            await asyncio.to_thread(self._save_refs_to_disk)

    def _is_bot_mentioned(
        self,
        activity: dict,
    ) -> bool:
        """Check if bot is mentioned in the activity."""
        entities = activity.get("entities", [])
        for entity in entities:
            if entity.get("type") != "mention":
                continue
            mentioned = entity.get("mentioned", {})
            mentioned_id = mentioned.get("id", "")
            if mentioned_id in (
                self._app_id,
                self._bot_channel_id,
            ):
                return True
        return False

    def _strip_bot_mention(
        self,
        text: str,
        activity: dict,
    ) -> str:
        """Remove bot @mention tags from text."""
        entities = activity.get("entities", [])
        for entity in entities:
            if entity.get("type") != "mention":
                continue
            mentioned = entity.get("mentioned", {})
            mid = mentioned.get("id", "")
            # Match by app_id or bot_channel_id
            if mid in (
                self._app_id,
                self._bot_channel_id,
            ):
                mention_text = entity.get("text", "")
                if mention_text and mention_text in text:
                    text = text.replace(
                        mention_text,
                        "",
                    ).strip()
        return text

    def to_handle_from_target(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> str:
        """Map cron target to to_handle.

        Group (user_id == "group"): returns session_id
        only, matching the shared group ref key.
        DM / isolated: returns session_id:user_id,
        matching the per-user ref key. _find_ref will
        fallback to session_id if group ref exists.
        """
        if user_id == "group":
            return session_id
        return f"{session_id}:{user_id}"

    async def health_check(self) -> Dict[str, Any]:
        """Return health status for this channel."""
        healthy = await self._is_server_healthy()
        return {
            "channel": self.channel,
            "status": ("healthy" if healthy else "unhealthy"),
            "detail": (
                f"HTTP server on port {self._http_port}"
                if healthy
                else "HTTP server not responding"
            ),
        }
