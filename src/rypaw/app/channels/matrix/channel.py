# -*- coding: utf-8 -*-
"""Matrix channel implementation using matrix-nio."""

import asyncio
import logging
import mimetypes
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)
from nio import (
    AsyncClient,
    MatrixRoom,
    RoomMessageAudio,
    RoomMessageFile,
    RoomMessageImage,
    RoomMessageText,
    RoomMessageVideo,
    RoomSendError,
    UploadError,
)

from ....config.config import MatrixConfig
from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

logger = logging.getLogger(__name__)


class MatrixChannel(BaseChannel):
    channel = "matrix"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        homeserver: str,
        user_id: str,
        access_token: str,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        bot_prefix: str = "",
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
        **_kwargs: Any,
    ) -> None:
        super().__init__(
            process=process,
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
        self.homeserver = homeserver.rstrip("/")
        self.user_id = user_id
        self.access_token = access_token
        self.bot_prefix = bot_prefix
        self.client: Optional[AsyncClient] = None
        self._sync_task: Optional[asyncio.Task] = None

    def _mxc_to_http(self, mxc_url: str) -> str:
        """Convert mxc://server/media_id to an authenticated HTTP URL."""
        if not mxc_url.startswith("mxc://"):
            return mxc_url
        rest = mxc_url[len("mxc://") :]
        parts = rest.split("/", 1)
        if len(parts) != 2:
            return mxc_url
        server, media_id = parts
        return (
            f"{self.homeserver}/_matrix/media/v3/download/"
            f"{server}/{media_id}"
            f"?access_token={self.access_token}"
        )

    def _check_allowlist(
        self,
        sender_id: str,
        is_group: bool = False,
    ) -> tuple:
        policy = self.group_policy if is_group else self.dm_policy
        if policy == "open":
            return True, ""
        if self.allow_from and sender_id in self.allow_from:
            return True, ""
        return False, self.deny_message

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "MatrixChannel":
        raise NotImplementedError(
            "Matrix channel must be configured via config file.",
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: MatrixConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "MatrixChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            homeserver=config.homeserver,
            user_id=config.user_id,
            access_token=config.access_token,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            bot_prefix=config.bot_prefix,
            dm_policy=config.dm_policy,
            group_policy=config.group_policy,
            allow_from=config.allow_from,
            deny_message=config.deny_message,
            require_mention=config.require_mention,
        )

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> AgentRequest:
        room_id = native_payload["room_id"]
        sender = native_payload["sender"]
        content_parts = native_payload.get("content_parts") or []

        if not content_parts:
            body = native_payload.get("body", "")
            content_parts = [TextContent(type=ContentType.TEXT, text=body)]

        session_id = self.resolve_session_id(room_id)
        request = self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=sender,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta={"room_id": room_id},
        )
        return request

    def get_to_handle_from_request(self, request: AgentRequest) -> str:
        session_id = getattr(request, "session_id", "") or ""
        if session_id.startswith("matrix:"):
            return session_id[len("matrix:") :]
        meta = getattr(request, "channel_meta", {}) or {}
        return meta.get("room_id", getattr(request, "user_id", ""))

    async def _handle_event(
        self,
        room: MatrixRoom,
        sender: str,
        content_parts: List[Any],
        bot_mentioned: bool = False,
    ) -> None:
        """Apply access control and enqueue a payload."""
        is_group = len(room.users) > 2
        meta = {
            "room_id": room.room_id,
            "is_group": is_group,
            "bot_mentioned": bot_mentioned,
        }

        allowed, deny_msg = self._check_allowlist(sender, is_group=is_group)
        if not allowed:
            if deny_msg:
                await self.send(room.room_id, deny_msg)
            return

        if not self._check_group_mention(is_group, meta):
            return

        payload = {
            "room_id": room.room_id,
            "sender": sender,
            "content_parts": content_parts,
            "meta": meta,
        }
        if self._enqueue:
            self._enqueue(payload)

    async def _message_callback(
        self,
        room: MatrixRoom,
        event: RoomMessageText,
    ) -> None:
        if event.sender == self.user_id:
            return

        logger.info(
            "Matrix received text from %s in %s: %s",
            event.sender,
            room.room_id,
            event.body,
        )

        # Detect @-mention for require_mention support
        localpart = self.user_id.split(":")[0].lstrip("@")
        bot_mentioned = self.user_id in event.body or localpart in event.body

        content_parts = [TextContent(type=ContentType.TEXT, text=event.body)]
        await self._handle_event(
            room,
            event.sender,
            content_parts,
            bot_mentioned=bot_mentioned,
        )

    async def _media_callback(
        self,
        room: MatrixRoom,
        event: Any,
    ) -> None:
        if event.sender == self.user_id:
            return

        mxc_url = getattr(event, "url", "") or ""
        filename = getattr(event, "body", "file") or "file"
        http_url = self._mxc_to_http(mxc_url) if mxc_url else ""

        logger.info(
            "Matrix received media from %s in %s: %s",
            event.sender,
            room.room_id,
            filename,
        )

        content_parts: List[Any] = []
        if isinstance(event, RoomMessageImage):
            content_parts.append(
                ImageContent(type=ContentType.IMAGE, image_url=http_url),
            )
        elif isinstance(event, RoomMessageVideo):
            content_parts.append(
                VideoContent(type=ContentType.VIDEO, video_url=http_url),
            )
        elif isinstance(event, RoomMessageAudio):
            content_parts.append(
                AudioContent(type=ContentType.AUDIO, data=http_url),
            )
        else:
            content_parts.append(
                FileContent(type=ContentType.FILE, file_url=http_url),
            )

        await self._handle_event(room, event.sender, content_parts)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        media_types = {
            ContentType.IMAGE,
            ContentType.VIDEO,
            ContentType.AUDIO,
            ContentType.FILE,
        }
        text_parts = [
            p
            for p in (parts or [])
            if getattr(p, "type", None) not in media_types
        ]
        media_parts = [
            p for p in (parts or []) if getattr(p, "type", None) in media_types
        ]
        if text_parts:
            await super().send_content_parts(to_handle, text_parts, meta)
        for m in media_parts:
            await self.send_media(to_handle, m, meta)

    async def send_media(  # pylint: disable=too-many-branches
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Upload a file to the homeserver and send it as a room message."""
        if not self.client:
            logger.error("Matrix client not initialized, cannot send media")
            return

        url = (
            getattr(part, "image_url", None)
            or getattr(part, "video_url", None)
            or getattr(part, "data", None)
            or getattr(part, "file_url", None)
        )
        if not url:
            return

        ctype = getattr(part, "type", None)
        if ctype == ContentType.IMAGE:
            msgtype = "m.image"
        elif ctype == ContentType.VIDEO:
            msgtype = "m.video"
        elif ctype == ContentType.AUDIO:
            msgtype = "m.audio"
        else:
            msgtype = "m.file"

        temp_path = None
        try:
            if url.startswith("file://"):
                file_path = Path(url[7:])
                mime = (
                    mimetypes.guess_type(str(file_path))[0]
                    or "application/octet-stream"
                )
                filename = file_path.name
                data = file_path.read_bytes()
            elif url.startswith(("http://", "https://")):
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            logger.warning(
                                "Matrix send_media: download failed"
                                " status=%d url=%s",
                                resp.status,
                                url[:80],
                            )
                            return
                        data = await resp.read()
                        mime = (
                            resp.content_type
                            or mimetypes.guess_type(
                                urlparse(url).path,
                            )[0]
                            or "application/octet-stream"
                        )
                parsed_path = urlparse(url).path
                filename = Path(parsed_path).name or "file"
            else:
                logger.warning(
                    "Matrix send_media: unsupported URL scheme: %s",
                    url[:40],
                )
                return

            suffix = Path(filename).suffix or (
                mimetypes.guess_extension(mime) or ""
            )
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=suffix,
            ) as tmp:
                tmp.write(data)
                temp_path = tmp.name

            with open(temp_path, "rb") as f:
                upload_resp, _ = await self.client.upload(
                    f,
                    content_type=mime,
                    filename=filename,
                    filesize=len(data),
                )

            if isinstance(upload_resp, UploadError):
                logger.error("Matrix upload failed: %s", upload_resp)
                return

            content = {
                "msgtype": msgtype,
                "body": filename,
                "url": upload_resp.content_uri,
                "info": {"mimetype": mime, "size": len(data)},
            }
            send_resp = await self.client.room_send(
                room_id=to_handle,
                message_type="m.room.message",
                content=content,
            )
            if isinstance(send_resp, RoomSendError):
                logger.error(
                    "Matrix room_send media failed: %s",
                    send_resp,
                )

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Matrix send_media error: %s", e, exc_info=True)
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    async def start(self) -> None:
        if (
            not self.enabled
            or not self.homeserver
            or not self.user_id
            or not self.access_token
        ):
            logger.info(
                "Matrix channel not configured or disabled. Skipping start.",
            )
            return

        self.client = AsyncClient(self.homeserver, self.user_id)
        self.client.access_token = self.access_token

        self.client.add_event_callback(
            self._message_callback,
            RoomMessageText,
        )
        self.client.add_event_callback(
            self._media_callback,
            RoomMessageImage,
        )
        self.client.add_event_callback(
            self._media_callback,
            RoomMessageVideo,
        )
        self.client.add_event_callback(
            self._media_callback,
            RoomMessageAudio,
        )
        self.client.add_event_callback(
            self._media_callback,
            RoomMessageFile,
        )

        logger.info(
            "Starting Matrix client for %s on %s",
            self.user_id,
            self.homeserver,
        )

        async def sync_loop() -> None:
            try:
                await self.client.sync_forever(
                    timeout=30000,
                    full_state=True,
                )
            except asyncio.CancelledError:
                pass
            except Exception as e:  # pylint: disable=broad-except
                logger.error(
                    "Matrix sync loop error: %s",
                    e,
                    exc_info=True,
                )

        self._sync_task = asyncio.create_task(sync_loop())

    async def stop(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
        if self.client:
            await self.client.close()
        logger.info("Matrix channel stopped.")

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.client:
            logger.error("Matrix client not initialized, cannot send message")
            return

        if not text:
            return

        logger.info(
            "Matrix sending to room=%s text_len=%d",
            to_handle,
            len(text),
        )
        resp = await self.client.room_send(
            room_id=to_handle,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": text,
            },
        )
        if isinstance(resp, RoomSendError):
            logger.error("Matrix room_send failed: %s", resp)
