# -*- coding: utf-8 -*-
"""Python standard library HTTP handler for Nextcloud Talk webhook."""


import asyncio
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Dict, Optional
from functools import partial

from .content_utils import (
    NextcloudTalkContentParser,
)
from .files_client import NextcloudFilesClient
from .utils import (
    verify_request_signature,
    extract_backend_url,
)
from .constants import (
    HEADER_SIGNATURE,
    HEADER_RANDOM,
    HEADER_BACKEND,
)

logger = logging.getLogger(__name__)

# Download filename hint by type (e.g. image -> .png, video -> .mp4)
FILENAME_HINT_BY_TYPE = {
    "image": ".png",
    "video": ".mp4",
    "audio": ".mp3",
}
DEFAULT_FILENAME_HINT = ".file"


def nextcloud_content_from_type(
    media_type: str,
    local_path: str,
    filename: str = "",
) -> dict:
    """
    Build content part from Nextcloud media type and local path.

    Args:
        media_type: "image", "video", "audio", or "file"
        local_path: Local file path (already downloaded)
        filename: Filename for the file

    Returns:
        Dict compatible with content_parts format
    """
    base = {
        "type": "file",
        "filename": filename or f"file_{media_type}",
        "file_url": local_path,  # Local path, not remote URL!
    }

    if media_type == "image":
        base["file_type"] = "image"
    elif media_type == "video":
        base["file_type"] = "video"
    elif media_type == "audio":
        base["file_type"] = "audio"
    else:
        base["file_type"] = "file"

    return base


class NextcloudTalkWebhookHandler(BaseHTTPRequestHandler):
    """
    HTTP webhook handler for Nextcloud Talk using Python standard library.

    Receives POST requests from Nextcloud Talk,
    verifies signatures, and forwards to the channel's enqueue callback.
    """

    # Class-level attributes (set by channel)
    enqueue_callback: Optional[Callable[..., Any]] = None
    webhook_secret: str = ""
    bot_prefix: str = ""
    api_user: str = ""  # Same as username (BOT account for WebDAV access)
    nc_username: str = ""  # Nextcloud username for authentication
    nc_password: str = ""  # Nextcloud password for authentication

    def __init__(self, *args, **kwargs):
        """
        Initialize handler.

        Class-level attributes (set by channel):
        - enqueue_callback: Function to enqueue payloads to channel
        - webhook_secret: Shared secret for signature verification
        - bot_prefix: Bot message prefix
        - api_user: Bot account username for WebDAV access (alias for username)  # noqa: E501
        """
        self.enqueue_callback = self.__class__.enqueue_callback
        self.webhook_secret = self.__class__.webhook_secret
        self.bot_prefix = self.__class__.bot_prefix
        self.api_user = self.__class__.api_user
        self.nc_username = self.__class__.nc_username
        self.nc_password = self.__class__.nc_password
        super().__init__(*args, **kwargs)

    def log_message(self, format_str, *args):
        """Suppress default http.server logging"""
        logger.info(f"nextcloud_talk webhook: {format_str % args}")

    def do_POST(self):
        """Handle POST requests from Nextcloud Talk."""
        # Only handle the webhook path
        if not self.path.startswith("/webhook/nextcloud_talk"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"Not found"}')
            return

        try:
            # Extract headers
            signature = self.headers.get(HEADER_SIGNATURE, "")
            random = self.headers.get(HEADER_RANDOM, "")
            backend = self.headers.get(HEADER_BACKEND, "")

            logger.info(
                "nextcloud_talk webhook: backend_suffix=%s "
                "signature_len=%s random_len=%s",
                backend[-20:] if backend else "None",
                len(signature),
                len(random),
            )

            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            # Verify signature
            if not verify_request_signature(
                body,
                signature,
                random,
                self.webhook_secret,
            ):
                logger.warning(
                    "nextcloud_talk webhook: signature verification failed",
                )
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":"Invalid signature"}')
                return

            # Parse JSON payload
            try:
                payload = json.loads(body.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError:
                logger.error("nextcloud_talk webhook: invalid JSON payload")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"Invalid JSON"}')
                return

            # Normalize backend URL
            normalized_backend = extract_backend_url(backend)

            # Process payload
            self._process_payload(payload, normalized_backend)

            # Return 200 OK
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        except Exception:
            logger.exception("nextcloud_talk webhook: handling failed")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"Internal server error"}')

    def _schedule_callback_async(self, callback_func, actor_name: str):
        """Schedule async callback in main event loop or background thread."""
        try:
            # Get the main event loop (created when the application starts).
            loop = asyncio.get_running_loop()
            # Schedule the coroutine in the main thread's event loop.
            asyncio.run_coroutine_threadsafe(
                callback_func(),
                loop,
            )
            logger.info(f"Scheduled message processing for: {actor_name}")
        except RuntimeError:
            # If there is no running event loop, run in a new thread.
            def run_in_thread():
                asyncio.run(callback_func())

            thread = threading.Thread(target=run_in_thread, daemon=True)
            thread.start()
            logger.info(f"Started thread for message processing: {actor_name}")

    def _process_payload(
        self,
        payload: dict,
        backend_url: str,
    ) -> bool:
        """
        Process the Activity Streams payload and enqueue for processing.

        Returns True if message was enqueued, False otherwise.
        """
        # Extract basic information
        activity_type = payload.get("type", "")
        obj = payload.get("object", {})

        # Handle wrapped Activity type
        self._handle_wrapped_activity(activity_type, obj)

        # Extract actor and conversation information
        actor_info = self._extract_actor_and_conversation(payload)
        actor_id, _, actor_type = actor_info["actor"]
        _, conversation_name = actor_info["conversation"]

        # Log processing information
        self._log_processing_info(
            activity_type,
            actor_id,
            actor_type,
            conversation_name,
            payload,
            obj,
        )

        # Check conversation events (bot added/removed)
        if self._handle_conversation_event(payload):
            return False

        # Check reactions
        if self._handle_reaction(payload):
            return False

        # Check media files
        media_result = self._handle_media_file(
            payload,
            obj,
            backend_url,
            actor_info,
        )
        if media_result is not None:
            return media_result

        # Check regular messages
        return self._handle_regular_message(
            payload,
            obj,
            backend_url,
            actor_info,
        )

    def _handle_wrapped_activity(self, activity_type: str, obj: dict) -> None:
        """Handle wrapped Activity type for debugging."""
        if activity_type == "Activity":
            logger.debug(
                "Detected wrapped Activity type, "
                "checking for nested structure",
            )

            # Log activity summary
            obj_summary = obj.get("summary", "")
            if obj_summary:
                logger.debug(f"Activity summary: {obj_summary}")

            # Log full object for debugging
            logger.info(
                f"Activity object name: {obj.get('name')}, "
                f"type: {obj.get('type')}",
            )
            logger.info(f"Activity object keys: {list(obj.keys())}")

            # Log content field which may contain file info
            obj_content = obj.get("content", "")
            if obj_content:
                logger.info(
                    "Activity object content (first 200 chars): %s",
                    str(obj_content)[:200],
                )

                # Try to parse as JSON to see if it contains file data
                try:
                    content_json = json.loads(obj_content)
                    logger.info(
                        "Activity content parsed: %s",
                        list(content_json.keys())
                        if isinstance(content_json, dict)
                        else type(content_json),
                    )
                    if "parameters" in content_json:
                        logger.info(
                            "Activity has parameters: %s",
                            list(content_json["parameters"].keys()),
                        )
                except Exception as e:
                    logger.debug(f"Content is not JSON: {e}")

    def _extract_actor_and_conversation(
        self,
        payload: dict,
    ) -> Dict[str, tuple]:
        """Extract actor and conversation information."""
        actor = payload.get("actor", {})
        target = payload.get("target", {})

        actor_data = NextcloudTalkContentParser.parse_actor(actor)
        conversation_data = NextcloudTalkContentParser.parse_conversation(
            target,
        )

        return {
            "actor": actor_data,
            "conversation": conversation_data,
        }

    def _log_processing_info(
        self,
        activity_type: str,
        actor_id: str,
        actor_type: str,
        conversation_name: str,
        payload: dict,
        obj: dict,
    ) -> None:
        """Log processing information for debugging."""
        logger.info(
            "nextcloud_talk webhook: activity=%s actor=%s... "
            "type=%s conversation=%s",
            activity_type,
            actor_id[:20],
            actor_type,
            conversation_name[:30]
            if len(conversation_name) > 30
            else conversation_name,
        )
        logger.debug("Full payload keys: %s", list(payload.keys()))
        logger.debug(
            "Object details: name=%s, content=%s",
            obj.get("name"),
            str(obj.get("content", ""))[:100],
        )
        logger.debug(
            "Full payload preview: %s",
            json.dumps(payload, indent=2)[:500],
        )

    def _handle_conversation_event(self, payload: dict) -> bool:
        """Handle conversation events (bot added/removed)."""
        conversation_event = (
            NextcloudTalkContentParser.extract_conversation_event(payload)
        )
        if conversation_event:
            logger.info(
                f"nextcloud_talk webhook: bot {conversation_event} "
                "to conversation",
            )
            return True
        return False

    def _handle_reaction(self, payload: dict) -> bool:
        """Handle reaction events."""
        reaction_data = NextcloudTalkContentParser.extract_reaction(payload)
        if reaction_data:
            emoji, message_id = reaction_data
            logger.info(
                "nextcloud_talk webhook: reaction emoji=%s message_id=%s",
                emoji,
                message_id,
            )
            return True
        return False

    def _handle_media_file(
        self,
        payload: dict,
        obj: dict,
        backend_url: str,
        actor_info: dict,
    ) -> Optional[bool]:
        """Handle media file processing."""
        media_info = NextcloudTalkContentParser.extract_media_file(payload)
        if not media_info:
            return None

        logger.info(
            f"nextcloud_talk webhook: media file type={media_info['type']} "
            f"name={media_info['name']} size={media_info['size']}",
        )

        # Normalize backend_url
        backend_url = extract_backend_url(backend_url)

        # Build WebDAV URL if possible
        webdav_url = self._build_webdav_url(media_info, backend_url)

        # Extract share link from metadata
        metadata = media_info.get("metadata", {})
        share_link = metadata.get("share-token") or metadata.get("link")

        # Determine download URL
        download_url = webdav_url or share_link

        if not download_url:
            logger.warning("No download URL available for media file")
            return False

        # Build channel payload
        channel_payload = self._build_media_channel_payload(
            obj,
            actor_info,
            backend_url,
            media_info,
            download_url,
        )

        # Enqueue the media file
        return self._enqueue_payload(channel_payload, media_info["name"])

    def _build_webdav_url(
        self,
        media_info: dict,
        backend_url: str,
    ) -> Optional[str]:
        """Build WebDAV URL for media file."""
        if not self.api_user or not media_info.get("path"):
            return None

        try:
            # Extract filename and file path
            metadata = media_info.get("metadata", {})
            filename = media_info.get("name", metadata.get("name", ""))
            file_path = media_info.get("path", "")

            logger.info(
                "Building WebDAV URL: base_url=%s, api_user=%s, "
                "file_path=%s, filename=%s",
                backend_url,
                self.api_user,
                file_path,
                filename,
            )

            # Build WebDAV URL
            client = NextcloudFilesClient(
                backend_url,
                self.nc_username,
                self.nc_password,
            )
            webdav_url = client.build_webdav_url(self.api_user, file_path)

            if webdav_url:
                logger.info("Built WebDAV URL: %s", webdav_url)
            else:
                logger.warning(
                    "Failed to build WebDAV URL for path: %s, api_user: %s",
                    file_path,
                    self.api_user,
                )
            return webdav_url
        except Exception as e:
            logger.error(f"Error building WebDAV URL: {e}")
            return None

    def _build_media_channel_payload(
        self,
        obj: dict,
        actor_info: dict,
        backend_url: str,
        media_info: dict,
        download_url: str,
    ) -> Dict[str, Any]:
        """Build channel payload for media files."""
        actor_id, actor_name, actor_type = actor_info["actor"]
        conversation_token, conversation_name = actor_info["conversation"]

        return {
            "channel_id": "nextcloud_talk",
            "sender_id": actor_id,
            "session_webhook": backend_url,
            "content_parts": [],
            "meta": {
                "actor_id": actor_id,
                "actor_name": actor_name,
                "actor_type": actor_type,
                "conversation_token": conversation_token,
                "conversation_name": conversation_name,
                "message_id": obj.get("id", ""),
                "backend_url": backend_url,
                "bot_prefix": self.bot_prefix,
                "download_url": download_url,
                "media_info": media_info,
                "api_user": self.api_user,
            },
        }

    def _handle_regular_message(
        self,
        payload: dict,
        obj: dict,
        backend_url: str,
        actor_info: dict,
    ) -> bool:
        """Handle regular message processing."""
        message = NextcloudTalkContentParser.extract_message_text(payload)
        if message is None:
            logger.debug(
                "nextcloud_talk webhook: not a regular message, ignoring",
            )
            return False

        # Build channel payload for regular message
        channel_payload = self._build_message_channel_payload(
            obj,
            actor_info,
            backend_url,
            message,
        )

        # Enqueue the message
        _, actor_name, _ = actor_info["actor"]
        return self._enqueue_payload(channel_payload, actor_name)

    def _build_message_channel_payload(
        self,
        obj: dict,
        actor_info: dict,
        backend_url: str,
        message: str,
    ) -> Dict[str, Any]:
        """Build channel payload for regular messages."""
        actor_id, actor_name, actor_type = actor_info["actor"]
        conversation_token, conversation_name = actor_info["conversation"]

        return {
            "channel_id": "nextcloud_talk",
            "sender_id": actor_id,
            "session_webhook": backend_url,
            "content_parts": [{"type": "text", "text": message}],
            "meta": {
                "actor_id": actor_id,
                "actor_name": actor_name,
                "actor_type": actor_type,
                "conversation_token": conversation_token,
                "conversation_name": conversation_name,
                "message_id": obj.get("id", ""),
                "backend_url": backend_url,
                "bot_prefix": self.bot_prefix,
            },
        }

    def _enqueue_payload(
        self,
        channel_payload: Dict[str, Any],
        identifier: str,
    ) -> bool:
        """Enqueue payload for processing."""
        logger.info(f"nextcloud_talk webhook: enqueueing {identifier}")

        if self.enqueue_callback and callable(self.enqueue_callback):
            safe_callback = partial(self.enqueue_callback, channel_payload)

            self._schedule_callback_async(safe_callback, identifier)
            return True
        else:
            logger.warning(
                "nextcloud_talk webhook: no enqueue callback set or "
                "not callable: %s",
                type(self.enqueue_callback),
            )
            return False


class StdlibWebhookServer:
    """
    Webhook server using Python standard library http.server.

    Runs in a separate thread to avoid blocking the main event loop.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        webhook_path: str = "/webhook/nextcloud_talk",
    ):
        """
        Initialize server.

        Args:
            host: Server host (default "0.0.0.0" for all interfaces)
            port: Server port (default 8765)
            webhook_path: Webhook endpoint path
        """
        self.host = host
        self.port = port
        self.webhook_path = webhook_path

        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @classmethod
    def set_enqueue_callback(cls, callback: Callable):
        """Set the enqueue callback for the handler."""
        NextcloudTalkWebhookHandler.enqueue_callback = callback

    @classmethod
    def set_webhook_secret(cls, secret: str):
        """Set the webhook secret for signature verification."""
        NextcloudTalkWebhookHandler.webhook_secret = secret

    @classmethod
    def set_bot_prefix(cls, prefix: str):
        """Set the bot message prefix."""
        NextcloudTalkWebhookHandler.bot_prefix = prefix

    @classmethod
    def set_api_user(cls, api_user: str):
        """Set the bot API user for WebDAV access."""
        NextcloudTalkWebhookHandler.api_user = api_user

    @classmethod
    def set_credentials(cls, username: str, password: str):
        """Set Nextcloud credentials for file downloads."""
        NextcloudTalkWebhookHandler.nc_username = username
        NextcloudTalkWebhookHandler.nc_password = password

    def start(self):
        """Start the webhook server in a background thread."""
        if self._server is not None:
            logger.warning("nextcloud_talk webhook server already running")
            return

        def run_server():
            self._server = HTTPServer(
                (self.host, self.port),
                NextcloudTalkWebhookHandler,
            )
            logger.info(
                f"nextcloud_talk webhook server listening on "
                f"{self.host}:{self.port}",
            )
            self._server.serve_forever()

        self._stop_event.clear()
        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the webhook server."""
        if self._server is None:
            return

        self._stop_event.set()
        self._server.shutdown()
        self._server.server_close()
        self._server = None

        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

        logger.info("nextcloud_talk webhook server stopped")
