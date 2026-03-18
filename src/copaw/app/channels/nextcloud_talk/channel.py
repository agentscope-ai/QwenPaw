# -*- coding: utf-8 -*-
"""Nextcloud Talk Channel.

Nextcloud Talk (Spreed) Bot integration via Webhook API.

Features:
- Receive chat messages via webhook
- Send messages/reactions via bot API
- HMAC-SHA256 signature verification
- Support for Markdown messages
- Session management for proactive/cron sends

Bot Installation:
    Requires Nextcloud admin to run:
    ./occ talk:bot:install <name> <webhook-url> [--secret=<secret>]

API Documentation:
    https://nextcloud-talk.readthedocs.io/en/latest/bots/
"""


from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import aiohttp

from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    ProcessHandler,
)

try:
    from agentscope_runtime.engine.schemas.agent_schemas import RunStatus
except ImportError:
    RunStatus = None

from .content_utils import (
    session_param_from_token,
    nextcloud_content_from_type,
)

from .constants import MAX_MESSAGE_LENGTH
from .files_client import NextcloudFilesClient
from .handler_stdlib import StdlibWebhookServer
from .utils import (
    normalize_nextcloud_url,
    build_bot_headers,
    load_token_store,
    save_token_store,
)

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)

MIME_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
}


class NextcloudTalkChannel(BaseChannel):
    """
    Nextcloud Talk Channel: Webhook -> Incoming -> to_agent_request ->
    process -> send_response -> Nextcloud API.

    Proactive send (stored backend_url):
    - We store backend_url from incoming messages in memory and disk
    - Key uses conversation token for lookup
    - to_handle "nextcloud_talk:token:<token>" stores by conversation
    """

    channel = "nextcloud_talk"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        webhook_secret: str,
        webhook_host: str = "0.0.0.0",
        webhook_port: int = 8765,
        webhook_path: str = "/webhook/nextcloud_talk",
        bot_prefix: str = "[BOT] ",
        username: str = "",
        password: str = "",
        media_dir: str = "~/.copaw/media/nextcloud_talk",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.webhook_secret = webhook_secret

        # Store credentials for file downloads
        self.nc_username = username
        self.nc_password = password

        # Setup media directory for downloaded files
        self._media_dir = Path(media_dir).expanduser()
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Log secret length for debugging (don't log the actual secret)
        logger.info(
            f"nextcloud_talk channel initialized: "
            f"enabled={enabled} secret_len={len(webhook_secret)} "
            f"host={webhook_host} port={webhook_port}",
        )
        self.webhook_host = webhook_host
        self.webhook_port = webhook_port
        self.webhook_path = webhook_path or "/webhook/nextcloud_talk"
        self.bot_prefix = bot_prefix

        # Webhook server (using Python standard library, no FastAPI)
        self._webhook_server: Optional[StdlibWebhookServer] = None

        # Backend URL store for proactive sends
        # Maps conversation/token suffix to backend URL for cron jobs
        self._backend_url_store: Dict[str, str] = {}
        self._backend_url_lock = asyncio.Lock()

        # Time debounce (disabled, manager handles)
        self._debounce_seconds = 0.0

        # API user for WebDAV access
        # This is the bot account username used to construct WebDAV
        # URLs for downloading files via
        # /remote.php/dav/files/{api_user}/{file_path}
        # Use username as api_user for WebDAV access
        self.api_user = username

        # Rate limiting: track last send time per session
        self._last_send_time: Dict[str, float] = {}
        self._send_lock = asyncio.Lock()

        # Minimum interval between sends (seconds)
        self._min_send_interval = 2.0

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "NextcloudTalkChannel":
        return cls(
            process=process,
            enabled=os.getenv("NEXTCLOUD_TALK_CHANNEL_ENABLED", "1") == "1",
            webhook_secret=os.getenv("NEXTCLOUD_TALK_WEBHOOK_SECRET", ""),
            webhook_host=os.getenv("NEXTCLOUD_TALK_WEBHOOK_HOST", "0.0.0.0"),
            webhook_port=int(os.getenv("NEXTCLOUD_TALK_WEBHOOK_PORT", "8765")),
            webhook_path=os.getenv(
                "NEXTCLOUD_TALK_WEBHOOK_PATH",
                "/webhook/nextcloud_talk",
            ),
            bot_prefix=os.getenv("NEXTCLOUD_TALK_BOT_PREFIX", "[BOT] "),
            username=os.getenv("NEXTCLOUD_USERNAME", ""),
            password=os.getenv("NEXTCLOUD_PASSWORD", ""),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "NextcloudTalkChannel":
        webhook_secret = getattr(config, "webhook_secret", "")
        return cls(
            process=process,
            enabled=config.enabled,
            webhook_secret=webhook_secret,
            webhook_host=getattr(config, "webhook_host", "0.0.0.0"),
            webhook_port=getattr(config, "webhook_port", 8765),
            webhook_path=getattr(
                config,
                "webhook_path",
                "/webhook/nextcloud_talk",
            ),
            bot_prefix=getattr(config, "bot_prefix", "[BOT] "),
            username=getattr(config, "username", ""),
            password=getattr(config, "password", ""),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )

    # ---------------------------
    # Session and backend URL management
    # ---------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Session_id = conversation token for consistent conversation tracking.
        """
        meta = channel_meta or {}
        conversation_token = meta.get("conversation_token", "")
        if conversation_token:
            # Use conversation token as session
            return f"{self.channel}:{conversation_token}"
        return f"{self.channel}:{sender_id}"

    def get_debounce_key(self, payload: Any) -> str:
        """Use conversation_token for debouncing."""
        if isinstance(payload, dict):
            token = (payload.get("meta") or {}).get("conversation_token", "")
            return token or payload.get("sender_id", "")
        return ""

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """
        Resolve cron dispatch target to channel-specific to_handle.

        Format: "nextcloud_talk:token:<conversation_token>"
        """
        # session_id format: "nextcloud_talk:<conversation_token>"
        if session_id and session_id.startswith(f"{self.channel}:"):
            token = session_id[len(self.channel) + 1 :]
            return f"nextcloud_talk:token:{token}"
        return f"nextcloud_talk:token:{user_id}"

    def _route_from_handle(self, to_handle: str) -> dict:
        """
        Parse to_handle to extract conversation token and backend URL.

        Supported formats:
        - "nextcloud_talk:token:<token>" -> lookup backend URL from store
        - "http://..." -> direct backend URL
        """
        s = (to_handle or "").strip()

        # Direct URL
        if s.startswith("http://") or s.startswith("https://"):
            return {"backend_url": s}

        # Token format
        if s.startswith("nextcloud_talk:token:"):
            token = s[len("nextcloud_talk:token:") :]
            return {"conversation_token": token}

        return {}

    async def _save_backend_url(
        self,
        conversation_token: str,
        backend_url: str,
    ) -> None:
        """Store backend URL for a conversation."""
        if not conversation_token or not backend_url:
            return

        # Generate key from token suffix (same as session_id suffix)
        key = session_param_from_token(conversation_token)

        async with self._backend_url_lock:
            self._backend_url_store[key] = backend_url

        logger.debug("saved backend_url for token_suffix=%s", key)

    async def _get_backend_url_from_token(
        self,
        conversation_token: str,
    ) -> Optional[str]:
        """
        Lookup backend URL for a conversation token.

        Uses token suffix for lookup (consistent with session_id).
        """
        key = session_param_from_token(conversation_token)

        async with self._backend_url_lock:
            return self._backend_url_store.get(key)

    # ---------------------------
    # Build AgentRequest from native
    # ---------------------------

    def _process_file_content_part(
        self,
        part: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a single file content part and populate file_url.
        """
        existing_file_url = part.get("file_url")
        metadata = part.get("metadata", {})
        share_link = metadata.get("share-token") or metadata.get("link")

        logger.info(
            "Processing file: filename=%s, existing_file_url=%s, "
            "metadata_keys=%s, share_link=%s",
            part.get("filename"),
            existing_file_url,
            list(metadata.keys()),
            share_link,
        )

        # Prefer existing file_url (local path), then WebDAV URL, then
        # share link
        webdav_url = metadata.get("webdav_url")
        share_link = metadata.get("share-token") or metadata.get("link")

        file_part = {
            "type": "file",
            "filename": part.get("file_name") or part.get("filename", ""),
        }

        # Preserve file_type if already set
        if part.get("file_type"):
            file_part["file_type"] = part.get("file_type")

        # Populate file_url based on availability
        if existing_file_url:
            file_part["file_url"] = existing_file_url
            logger.info(
                "Using existing file_url (local path) for file: %s -> %s",
                file_part.get("filename"),
                existing_file_url,
            )
        elif webdav_url:
            file_part["file_url"] = webdav_url
            logger.info(
                "Populated file_url with WebDAV URL for file: %s -> %s",
                file_part.get("filename"),
                webdav_url,
            )
        elif share_link:
            file_part["file_url"] = share_link
            logger.info(
                "Populated file_url for file: %s -> %s",
                file_part.get("filename"),
                share_link,
            )
        else:
            logger.warning(
                "No WebDAV URL or share link found for file: %s",
                file_part.get("filename"),
            )

        return file_part

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> Any:
        """
        Build AgentRequest from Nextcloud Talk native dict.
        """
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = dict(payload.get("meta") or {})

        # Process content parts
        converted_parts = []
        for part in content_parts:
            if isinstance(part, dict) and part.get("type") == "file":
                file_part = self._process_file_content_part(part)
                converted_parts.append(file_part)
            else:
                # Keep other content parts as-is
                converted_parts.append(part)

        content_parts = converted_parts
        logger.info(
            "build_agent_request_from_native: final content_parts=%s",
            content_parts,
        )

        # Extract and store backend URL for proactive sends
        backend_url = meta.get("backend_url") or payload.get(
            "session_webhook",
            "",
        )
        conversation_token = meta.get("conversation_token", "")
        if backend_url and conversation_token:
            asyncio.create_task(
                self._save_backend_url(conversation_token, backend_url),
            )

        session_id = self.resolve_session_id(sender_id, meta)

        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )

        # Preserve original content_parts in meta for later use
        if meta is None:
            meta = {}
        meta["original_content_parts"] = content_parts

        if hasattr(request, "channel_meta"):
            request.channel_meta = meta

        # Check the actual content in the request
        has_actual_content = False
        if hasattr(request, "input") and request.input:
            first_msg = request.input[0]
            if hasattr(first_msg, "content") and first_msg.content:
                has_actual_content = True
                logger.info(
                    "build_agent_request_from_native: request has content: %s",
                    [getattr(c, "type", "unknown") for c in first_msg.content],
                )

        logger.info(
            "build_agent_request_from_native: request created, "
            "has content_parts=%s",
            has_actual_content,
        )
        return request

    # ---------------------------
    # Message processing
    # ---------------------------

    def _content_has_media(self, content_parts: List[Any]) -> bool:
        """
        Check if content_parts has media files (images, videos, audio).
        """
        if not content_parts:
            return False
        for c in content_parts:
            # Check type attribute
            t = getattr(c, "type", None)

            # Case 1: type is string 'file'
            if t == "file":
                return True

            # Case 2: type is ContentType.FILE enum (if available)
            try:
                from agentscope_runtime.engine.schemas.message_schemas import (
                    ContentType as MessageContentType,
                )

                if t == MessageContentType.FILE:
                    return True
            except ImportError:
                # If the module is not available, skip this check
                pass

            # Case 3: type has name attribute (Enum)
            if hasattr(t, "name") and t.name == "FILE":
                return True

            # Case 4: dict format
            if isinstance(c, dict) and c.get("type") == "file":
                return True
        return False

    def _apply_no_text_debounce(
        self,
        session_id: str,
        content_parts: List[Any],
    ) -> tuple[bool, List[Any]]:
        """
        Override base class: process media files immediately even without text.
        Only debounce when there's no text AND no media.
        """
        logger.info(
            "_apply_no_text_debounce: called with content_parts=%s",
            content_parts,
        )

        # If has media, process immediately
        if self._content_has_media(content_parts):
            logger.info("Media detected, processing immediately")
            return (True, list(content_parts))

        # Otherwise use default logic (debounce if no text)
        result = super()._apply_no_text_debounce(session_id, content_parts)
        logger.info("_apply_no_text_debounce: result=%s", result)
        return result

    def _setup_webhook_server(self):
        """Setup webhook server using Python standard library."""
        self._webhook_server = StdlibWebhookServer(
            host=self.webhook_host,
            port=self.webhook_port,
            webhook_path=self.webhook_path,
        )

        # Set callback and config on the handler class via the server
        self._webhook_server.set_enqueue_callback(self.consume_one)
        self._webhook_server.set_webhook_secret(self.webhook_secret)
        self._webhook_server.set_bot_prefix(self.bot_prefix)
        self._webhook_server.set_api_user(self.api_user)
        self._webhook_server.set_credentials(
            self.nc_username,
            self.nc_password,
        )
        self._webhook_server.set_webhook_path(self.webhook_path)

    # ---------------------------
    # Lifecycle
    # ---------------------------

    async def consume_one(self, payload: Any) -> None:
        """
        Process one payload from the manager-owned queue.
        """
        logger.info("consume_one: CALLED with payload type=%s", type(payload))
        await super().consume_one(payload)

    async def _consume_one_request(self, payload: Any) -> None:
        """
        Convert payload to request, apply no-text debounce, run _process,
        send messages, handle errors and on_reply_sent.
        """
        logger.info(
            f"_consume_one_request: CALLED with payload type={type(payload)}",
        )

        # Check if we need to download media file (async, non-blocking)
        if isinstance(payload, dict):
            meta = payload.get("meta", {})
            download_url = meta.get("download_url")
            media_info = meta.get("media_info")

            if download_url and media_info:
                logger.info(
                    "Downloading media file asynchronously: %s",
                    media_info.get("name"),
                )
                try:
                    local_path = await self._download_media_async(
                        download_url=download_url,
                        media_info=media_info,
                        backend_url=meta.get("backend_url", ""),
                    )
                    if local_path:
                        # Update content_parts with local file path

                        file_part = nextcloud_content_from_type(
                            media_info["type"],
                            local_path,
                            media_info["name"],
                        )
                        payload["content_parts"] = [file_part]
                        logger.info(
                            f"Media downloaded successfully: {local_path}",
                        )
                    else:
                        logger.warning(
                            "Failed to download media: %s",
                            media_info.get("name"),
                        )
                        # Skip this payload if download failed
                        return
                except Exception as e:
                    logger.exception("Error downloading media: %s", e)
                    return

        # Call parent implementation
        await super()._consume_one_request(payload)

        logger.info("_consume_one_request: COMPLETED")

    async def _download_media_async(
        self,
        download_url: str,
        media_info: Dict[str, Any],
        backend_url: str,
    ) -> Optional[str]:
        """
        Download media file asynchronously.

        Args:
            download_url: URL to download from
            media_info: Media file information
            backend_url: Nextcloud backend URL

        Returns:
            Local file path or None on failure
        """
        if not download_url:
            logger.warning("download_media_async: empty URL")
            return None

        try:
            # Prepare local path
            media_dir = self._media_dir

            # Get mime type for extension detection
            mime_type = media_info.get("mime_type", "")

            # Add extension based on mime_type or media_type
            ext_map = MIME_TYPE_EXTENSIONS
            media_type = media_info.get("type", "")
            suffix = (
                ext_map.get(
                    mime_type.lower(),
                )
                or f".{media_type}"
                if media_type
                else ".file"
            )

            # Generate safe filename
            safe_name = hashlib.sha256(download_url.encode()).hexdigest()
            local_path = media_dir / f"{safe_name}{suffix}"

            logger.info(
                f"Downloading Nextcloud media: {download_url} -> {local_path}",
            )

            # Use NextcloudFilesClient for authenticated download
            client = NextcloudFilesClient(
                backend_url,
                self.nc_username,
                self.nc_password,
            )

            success = await client.download_file(download_url, str(local_path))
            # No need to call client.close() - download_file manages its own
            # session

            if success and local_path.exists():
                logger.info("Downloaded successfully: %s", local_path)
                return str(local_path)
            else:
                logger.warning(
                    f"Download failed or path doesn't exist: {local_path}",
                )
                return None

        except Exception as e:
            logger.exception("Error downloading media: %s", e)
            return None

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("nextcloud_talk channel disabled")
            return

        # Load backend URL store from disk
        self._backend_url_store = load_token_store() or {}

        # Setup and start webhook server (using stdlib, no new dependency)
        self._setup_webhook_server()
        self._webhook_server.start()

        logger.info(
            f"nextcloud_talk channel started: webhook at "
            f"{self.webhook_host}:{self.webhook_port}{self.webhook_path}",
        )

    async def stop(self) -> None:
        if not self.enabled:
            return

        # Stop webhook server
        if self._webhook_server:
            self._webhook_server.stop()
            self._webhook_server = None

        # Persist the backend URL store for cron jobs
        if self._backend_url_store:
            try:
                save_token_store(self._backend_url_store)
                logger.info(
                    "persisted backend_url_store with %s entries",
                    len(self._backend_url_store),
                )
            except Exception:
                logger.exception("failed to persist backend_url_store")

        logger.info("nextcloud_talk channel stopped")

    # ---------------------------
    # Sending messages
    # ---------------------------

    async def _apply_rate_limiting(self, to_handle: str) -> None:
        """
        Apply rate limiting to prevent sending messages too frequently.
        """
        session_id = to_handle
        async with self._send_lock:
            last_time = self._last_send_time.get(session_id, 0)
            current_time = asyncio.get_event_loop().time()
            elapsed = current_time - last_time

            if elapsed < self._min_send_interval:
                delay = self._min_send_interval - elapsed
                logger.debug(
                    "nextcloud_talk rate limiting: waiting %.1fs "
                    "before sending",
                    delay,
                )
                await asyncio.sleep(delay)

            self._last_send_time[session_id] = asyncio.get_event_loop().time()

    def _truncate_message_if_needed(self, text: str) -> str:
        """
        Truncate message if it exceeds the maximum length.
        """
        if len(text) > MAX_MESSAGE_LENGTH:
            truncated = text[: MAX_MESSAGE_LENGTH - 3] + "..."
            logger.warning(
                "nextcloud_talk message truncated to %s chars",
                MAX_MESSAGE_LENGTH,
            )
            return truncated
        return text

    async def _resolve_backend_url(
        self,
        to_handle: str,
        meta: Dict[str, Any],
        meta_token: str,
    ) -> Optional[str]:
        """
        Resolve the backend URL for sending messages.
        """
        route = self._route_from_handle(to_handle)

        # Try to get backend URL from meta
        backend_url = meta.get("backend_url") or meta.get(
            "session_webhook",
            "",
        )

        # If not in meta, try lookup from token
        if not backend_url and "conversation_token" in route:
            token = route["conversation_token"]
            backend_url = await self._get_backend_url_from_token(token)
            if not backend_url and meta_token:
                # Use meta_token as fallback
                backend_url = await self._get_backend_url_from_token(
                    meta_token,
                )

        return backend_url

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a message to Nextcloud Talk.

        NOTE: This endpoint expects the webhook_secret to be configured
        in the config.json file. The bot must use the same secret that
        was used during installation.

        The backend URL and conversation token must be properly configured.
        """
        if not self.enabled:
            return

        # Apply rate limiting
        await self._apply_rate_limiting(to_handle)

        # Truncate message if too long
        text = self._truncate_message_if_needed(text)

        # Get conversation token from meta
        meta = meta or {}
        meta_token = meta.get("conversation_token", "")

        # Resolve backend URL
        backend_url = await self._resolve_backend_url(
            to_handle,
            meta,
            meta_token,
        )
        if not backend_url:
            logger.warning(
                "nextcloud_talk cannot send: no backend_url for to_handle=%s",
                to_handle,
            )
            return

        # Get conversation token (for API request)
        route = self._route_from_handle(to_handle)
        conversation_token = route.get("conversation_token", meta_token)

        if not conversation_token:
            logger.warning(
                "nextcloud_talk cannot send: no conversation token "
                "for to_handle=%s",
                to_handle,
            )
            return

        # Normalize backend URL
        backend_url = normalize_nextcloud_url(backend_url)

        # Build request body following Nextcloud Talk Bot API spec:
        # { "message": "<text>" }
        # Note: conversation token is in the URL path, not body
        body = {
            "message": text,
        }
        body_str = json.dumps(body, ensure_ascii=False, separators=(",", ":"))

        # Generate signature on the message text (not full JSON body)
        # According to Nextcloud Talk Bot API verification logic:
        # signature = HMAC(random_header + message_text, secret)
        headers = build_bot_headers(self.webhook_secret, text)

        headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        # Send message
        url = (
            f"{backend_url}ocs/v2.php/apps/spreed/api/v1/bot/"
            f"{conversation_token}/message"
        )

        # Debug logging - show full values for verification
        random_val = headers.get("X-Nextcloud-Talk-Bot-Random", "N/A")
        signature_val = headers.get("X-Nextcloud-Talk-Bot-Signature", "N/A")
        logger.info(
            f"nextcloud_talk send: url={url} "
            f"secret_len={len(self.webhook_secret)} "
            f"random={random_val} "
            f"signature={signature_val} "
            f"body={body_str}",
        )

        try:
            # Use data=body_str to ensure exact same body is sent
            # (for signature verification)
            # Create a new session per request to avoid event loop binding
            # issues when called from different contexts (e.g., webhook thread)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data=body_str.encode("utf-8"),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp_text = await resp.text()

                    if resp.status >= 400:
                        logger.warning(
                            "nextcloud_talk send failed: status=%s "
                            "url=%s "
                            "secret_len=%s "
                            "body=%s",
                            resp.status,
                            url,
                            len(self.webhook_secret),
                            resp_text[:200],
                        )
                        return

                    # Try to parse JSON response
                    try:
                        resp_data = json.loads(resp_text) if resp_text else {}
                    except json.JSONDecodeError:
                        resp_data = {}

                    ocs = resp_data.get("ocs", {})
                    resp_meta = ocs.get("meta", {})

                    if resp_meta.get("statuscode") != 200:
                        logger.warning(
                            "nextcloud_talk send API error: "
                            "statuscode=%s message=%s",
                            resp_meta.get("statuscode"),
                            resp_meta.get("message"),
                        )
                        return

                    logger.info(
                        "nextcloud_talk send ok: conversation=%s len=%s",
                        conversation_token,
                        len(text),
                    )

        except asyncio.TimeoutError:
            logger.warning(
                "nextcloud_talk send timeout for conversation=%s",
                conversation_token,
            )
        except Exception:
            logger.exception(
                "nextcloud_talk send failed for conversation=%s",
                conversation_token,
            )

    def _extract_content_parts(self, parts: List[Any]) -> tuple[list, list]:
        """
        Extract text and media parts from content parts.
        """
        text_parts = []
        media_parts = []

        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
            elif t in (
                ContentType.IMAGE,
                ContentType.VIDEO,
                ContentType.AUDIO,
                ContentType.FILE,
            ):
                media_parts.append(p)

        return text_parts, media_parts

    def _build_text_body(
        self,
        text_parts: list,
        meta: Optional[Dict[str, Any]],
    ) -> str:
        """
        Build the main text body from text parts.
        """
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", "")
        if prefix and body:
            body = prefix + body
        elif prefix and not body:
            body = prefix
        return body

    def _add_media_attachments(self, body: str, media_parts: list) -> str:
        """
        Add media attachments to the message body following OpenClaw pattern.
        """
        for m in media_parts:
            t = getattr(m, "type", None)
            if t == ContentType.FILE:
                # For file content, extract file information
                file_name = getattr(m, "filename", "unknown_file")
                file_url = getattr(m, "file_url", None)
                if file_url:
                    body += f"\n\nAttachment: {file_name} - {file_url}"
                else:
                    # Fallback to file name only
                    body += f"\n\nFile: {file_name}"
            elif t == ContentType.IMAGE and getattr(m, "image_url", None):
                body += f"\n\nImage: {m.image_url}"
            elif t == ContentType.VIDEO and getattr(m, "video_url", None):
                body += f"\n\nVideo: {m.video_url}"
            elif t == ContentType.AUDIO:
                body += "\n\nAudio attachment"

        return body

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[Any],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send content parts (text, images, etc.) to Nextcloud Talk.

        Supports text, images, videos, and audio files.
        For media files, combines text with media links following
        OpenClaw pattern.
        """
        # Extract text and media parts
        text_parts, media_parts = self._extract_content_parts(parts)

        # Build main text body
        body = self._build_text_body(text_parts, meta)

        # Add media attachments
        body = self._add_media_attachments(body, media_parts)

        if body.strip():
            full_body = body.strip()
            while full_body:
                chunk = full_body[:MAX_MESSAGE_LENGTH]
                full_body = full_body[MAX_MESSAGE_LENGTH:]
                await self.send(to_handle, chunk, meta)

    async def _run_process_loop(
        self,
        request: "AgentRequest",
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """
        Override _run_process_loop to batch messages for rate limiting.
        Nextcloud Talk Bot API has rate limits, so we collect all messages
        and send them at the end as a single message.
        Also handles media files (images, videos, audio).
        """

        logger.info("_run_process_loop: STARTED for to_handle=%s", to_handle)

        all_parts: List[Any] = []
        last_response = None

        try:
            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)

                if (
                    obj == "message"
                    and RunStatus
                    and status == RunStatus.Completed
                ):
                    # Extract content parts from event, applying filters
                    parts = self._message_to_content_parts(event)
                    if parts:
                        all_parts.extend(parts)

                elif obj == "response":
                    last_response = event
                    await self.on_event_response(request, event)

            # Send all collected parts as a single message
            if all_parts:
                await self.send_content_parts(to_handle, all_parts, send_meta)

            if last_response and getattr(last_response, "error", None):
                err_text = (
                    self._get_response_error_message(last_response)
                    or "Unknown error"
                )
                await self._on_consume_error(request, to_handle, err_text)

            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)

        except Exception:
            logger.exception("channel consume_one failed")
            await self._on_consume_error(
                request,
                to_handle,
                "An error occurred while processing your request.",
            )
