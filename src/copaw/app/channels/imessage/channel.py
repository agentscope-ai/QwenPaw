# -*- coding: utf-8 -*-
# pylint:disable=too-many-return-statements
from __future__ import annotations

import logging
import os
import time
import sqlite3
import subprocess
import threading
import shutil
import asyncio
import base64
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, List

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ContentType,
)

from ....config.config import IMessageChannelConfig
from ..utils import file_url_to_local_path
from ....agents.utils.file_handling import download_file_from_url

from ..base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
    OutgoingContentPart,
)

logger = logging.getLogger(__name__)


class IMessageChannel(BaseChannel):
    channel = "imessage"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        db_path: str,
        poll_sec: float,
        bot_prefix: str,
        media_dir: str = "~/.copaw/media",
        max_decoded_size: int = 10 * 1024 * 1024,  # 10MB default
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
        )
        self.enabled = enabled
        self.db_path = os.path.expanduser(db_path)
        self.poll_sec = poll_sec
        self.bot_prefix = bot_prefix

        # Create media directory for downloaded files
        self._media_dir = Path(media_dir).expanduser()
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Base64 data size limit
        self.max_decoded_size = max_decoded_size

        self._imsg_path: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "IMessageChannel":
        return cls(
            process=process,
            enabled=os.getenv("IMESSAGE_CHANNEL_ENABLED", "1") == "1",
            db_path=os.getenv(
                "IMESSAGE_DB_PATH",
                "~/Library/Messages/chat.db",
            ),
            poll_sec=float(os.getenv("IMESSAGE_POLL_SEC", "1.0")),
            bot_prefix=os.getenv("IMESSAGE_BOT_PREFIX", "[BOT] "),
            media_dir=os.getenv("IMESSAGE_MEDIA_DIR", "~/.copaw/media"),
            max_decoded_size=int(
                os.getenv("IMESSAGE_MAX_DECODED_SIZE", "10485760"),
            ),  # 10MB
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: IMessageChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
    ) -> "IMessageChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            db_path=config.db_path or "~/Library/Messages/chat.db",
            poll_sec=config.poll_sec,
            bot_prefix=config.bot_prefix or "[BOT] ",
            media_dir=config.media_dir or "~/.copaw/media",
            max_decoded_size=config.max_decoded_size,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
        )

    def _ensure_imsg(self) -> str:
        path = shutil.which("imsg")
        if not path:
            raise RuntimeError(
                "Cannot find executable: imsg. Install it with:\n"
                "  brew install steipete/tap/imsg\n"
                "Then verify:\n"
                "  which imsg\n",
            )
        return path

    def _send_sync(
        self,
        to_handle: str,
        text: str,
        file_path: Optional[str] = None,
    ) -> None:
        if not self._imsg_path:
            raise RuntimeError(
                "iMessage channel not initialized (imsg path missing).",
            )
        # Capture stdout/stderr so imsg's "sent" (or similar) does not
        # appear in our process output.
        cmd = [self._imsg_path, "send", "--to", to_handle]
        if text:
            cmd.extend(["--text", text])
        if file_path:
            cmd.extend(["--file", file_path])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "imsg send failed: returncode=%s stderr=%r",
                result.returncode,
                (result.stderr or "").strip() or None,
            )
            result.check_returncode()

    def _emit_request_threadsafe(self, request: Any) -> None:
        """Enqueue request via manager (thread-safe)."""
        if self._enqueue is not None:
            self._enqueue(request)

    def _watcher_loop(self) -> None:
        logger.info(
            "watcher thread started (poll=%.2fs, db=%s)",
            self.poll_sec,
            self.db_path,
        )

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        last_rowid = conn.execute(
            "SELECT IFNULL(MAX(ROWID),0) FROM message",
        ).fetchone()[0]

        try:
            while not self._stop_event.is_set():
                try:
                    rows = conn.execute(
                        """
SELECT m.ROWID, m.text, m.is_from_me, c.ROWID as chat_rowid, h.id as sender
FROM message m
JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
JOIN chat c ON c.ROWID = cmj.chat_id
LEFT JOIN handle h ON h.ROWID = m.handle_id
WHERE m.ROWID > ?
ORDER BY m.ROWID ASC
""",
                        (last_rowid,),
                    ).fetchall()

                    for r in rows:
                        last_rowid = r["ROWID"]
                        if r["is_from_me"] == 1:
                            continue
                        text = r["text"]
                        if not text or str(text).startswith(self.bot_prefix):
                            continue
                        sender = (r["sender"] or "").strip()
                        if not sender:
                            continue

                        content_parts = [
                            TextContent(
                                type=ContentType.TEXT,
                                text=str(text) if text else "",
                            ),
                        ]
                        meta = {
                            "chat_rowid": str(r["chat_rowid"]),
                            "rowid": int(r["ROWID"]),
                        }
                        native = {
                            "channel_id": self.channel,
                            "sender_id": sender,
                            "content_parts": content_parts,
                            "meta": meta,
                        }
                        request = self.build_agent_request_from_native(native)
                        request.channel_meta = meta
                        logger.info(
                            "recv from=%s rowid=%s text=%r",
                            sender,
                            r["ROWID"],
                            text,
                        )
                        self._emit_request_threadsafe(request)

                except Exception:
                    logger.exception("poll iteration failed")

                time.sleep(self.poll_sec)
        finally:
            conn.close()
            logger.info("watcher thread stopped")

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Build AgentRequest from imessage native dict (runtime content)."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        return request

    async def _on_consume_error(
        self,
        request: Any,
        to_handle: str,
        err_text: str,
    ) -> None:
        """Send error via imessage _send_sync (sync API)."""
        await asyncio.to_thread(self._send_sync, to_handle, err_text)

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("disabled by env IMESSAGE_ENABLED=0")
            return

        self._imsg_path = self._ensure_imsg()
        logger.info(f"IMessage channel started with binary: {self._imsg_path}")

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watcher_loop, daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        if not self.enabled:
            return

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        await asyncio.to_thread(self._send_sync, to_handle, text, file_path)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a list of content parts.
        For iMessage: send text and media as separate messages.
        """
        if not parts:
            return

        text_parts: List[str] = []
        media_parts: List[OutgoingContentPart] = []

        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT:
                text_val = getattr(p, "text", None)
                if text_val:
                    text_parts.append(text_val)
            elif t == ContentType.REFUSAL:
                refusal_val = getattr(p, "refusal", None)
                if refusal_val:
                    text_parts.append(refusal_val)
            elif t in (
                ContentType.IMAGE,
                ContentType.VIDEO,
                ContentType.AUDIO,
                ContentType.FILE,
            ):
                media_parts.append(p)

        body = (meta or {}).get("bot_prefix", "") + "\n".join(text_parts)

        # Send text message first (if any)
        if body.strip():
            preview = body[:120] + "..." if len(body) > 120 else body
            logger.debug(
                f"imessage send_content_parts: to_handle={to_handle} "
                f"body_len={len(body)} preview={preview}",
            )
            await self.send(to_handle, body.strip(), meta)

        # Send media parts
        for media_part in media_parts:
            try:
                await self.send_media(to_handle, media_part, meta)
            except Exception as exc:
                # Fallback: send a textual placeholder if media delivery fails
                logger.warning(
                    "imessage send_content_parts: "
                    "send_media failed for %s: %s",
                    getattr(media_part, "type", None),
                    exc,
                )
                # Try to extract a useful URL or identifier from the media part
                url_candidates = [
                    getattr(media_part, "url", None),
                    getattr(media_part, "file_url", None),
                    getattr(media_part, "image_url", None),
                    getattr(media_part, "audio_url", None),
                    getattr(media_part, "video_url", None),
                ]
                fallback_url = next((u for u in url_candidates if u), None)
                if fallback_url:
                    fallback_text = f"[File: {fallback_url}]"
                else:
                    content_type = getattr(
                        getattr(media_part, "type", None),
                        "value",
                        getattr(media_part, "type", None),
                    )
                    fallback_text = (
                        f"[File could not be sent ({content_type})]"
                    )
                await self.send(to_handle, fallback_text, meta)

    def _extract_url_and_filename(self, part: OutgoingContentPart):
        """Extract URL and filename hint from media part based on
        content type."""
        url = None
        filename_hint = "media_file"
        t = getattr(part, "type", None)

        if t == ContentType.IMAGE:
            url = getattr(part, "image_url", None)
            filename_hint = "image"
        elif t == ContentType.FILE:
            url = getattr(part, "file_url", None) or getattr(
                part,
                "file_id",
                None,
            )
            filename_hint = getattr(part, "filename", "file")
        elif t == ContentType.VIDEO:
            url = getattr(part, "video_url", None)
            filename_hint = "video"
        elif t == ContentType.AUDIO:
            url = getattr(part, "audio_url", None) or getattr(
                part,
                "data",
                None,
            )
            filename_hint = "audio"

        return url, filename_hint, t

    def _get_file_extension(
        self,
        content_type: Any,
        filename_hint: str,
    ) -> str:
        """Get appropriate file extension based on content type."""
        # Sanitize filename_hint first to prevent path
        # traversal in extension extraction
        sanitized_hint = self._sanitize_filename(filename_hint)
        if "." in sanitized_hint:
            return Path(sanitized_hint).suffix
        elif content_type == ContentType.IMAGE:
            return ".jpg"
        elif content_type == ContentType.AUDIO:
            return ".mp3"
        elif content_type == ContentType.VIDEO:
            return ".mp4"
        else:
            return ".bin"

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename to prevent path traversal attacks.
        - Extract basename only (remove any path components)
        - Allow only alphanumeric characters, underscores, hyphens, and dots
        - Replace invalid characters with underscores
        - Ensure the result is not empty
        """
        # Extract basename to remove any path separators
        basename = Path(filename).name

        # If basename is empty (e.g., filename was just a path
        # separator), use default
        if not basename:
            return "media_file"

        # Allow only safe characters: alphanumeric, underscore, hyphen, dot
        import re

        sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", basename)

        # Ensure it doesn't start or end with dots or hyphens
        # (which could be problematic)
        sanitized = sanitized.strip("._-")

        # If after sanitization it's empty, use default
        if not sanitized:
            return "media_file"

        return sanitized

    async def _handle_local_file(self, url: str) -> Optional[str]:
        """Handle local file paths."""
        local_path = file_url_to_local_path(url)
        if local_path and Path(local_path).exists():
            logger.info(f"imessage send_media: using local file {local_path}")
            return local_path

        path_obj = Path(url).expanduser()
        if path_obj.exists():
            local_path = str(path_obj.resolve())
            logger.info(
                f"imessage send_media: using plain file path {local_path}",
            )
            return local_path

        logger.warning(f"imessage send_media: file not found {url}")
        return None

    async def _handle_remote_url(
        self,
        url: str,
        filename_hint: str,
        content_type: Any,
    ) -> Optional[str]:
        """Handle remote HTTP/HTTPS URLs."""
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
            ext = self._get_file_extension(content_type, filename_hint)
            safe_basename = self._sanitize_filename(filename_hint)
            safe_filename = f"{safe_basename}_{url_hash}{ext}"
            local_path = await download_file_from_url(
                url,
                filename=safe_filename,
                download_dir=str(self._media_dir),
            )
            # Verify the resolved path is within _media_dir
            # to prevent path traversal
            resolved_path = Path(local_path).resolve()
            media_dir_resolved = self._media_dir.resolve()
            if not str(resolved_path).startswith(str(media_dir_resolved)):
                logger.error(
                    "imessage send_media: attempted path traversal detected, "
                    f"blocked file creation at {resolved_path}",
                )
                return None

            logger.info(
                f"imessage send_media: downloaded {url} to {local_path}",
            )
            return local_path
        except Exception as e:
            logger.error(f"imessage send_media: failed to download {url}: {e}")
            return None

    async def _handle_data_url(
        self,
        url: str,
        content_type: Any,
        filename_hint: str,
    ) -> Optional[str]:
        """Handle base64 data URLs."""
        try:
            if "base64," in url:
                b64_data = url.split("base64,", 1)[-1]
                if content_type == ContentType.IMAGE:
                    ext = ".png" if "image/png" in url else ".jpg"
                elif content_type == ContentType.AUDIO:
                    ext = ".mp3"
                elif content_type == ContentType.VIDEO:
                    ext = ".mp4"
                else:
                    ext = ".bin"

                # Add validation and size limits for base64 data
                MAX_DECODED_SIZE = self.max_decoded_size

                # Validate base64 format and get decoded size
                # without full decode
                try:
                    # Get approximate decoded size: (n*3)/4 where n
                    # is length of base64 string
                    b64_length = len(b64_data)
                    # Remove padding for calculation
                    padding = b64_data.count("=", -2)
                    approx_decoded_size = (b64_length * 3) // 4 - padding

                    if approx_decoded_size > MAX_DECODED_SIZE:
                        logger.warning(
                            "imessage send_media: base64 data too large "
                            f"({approx_decoded_size} bytes > "
                            f"{MAX_DECODED_SIZE} bytes limit)",
                        )
                        return None

                    # Validate and decode with proper error handling
                    file_data = base64.b64decode(b64_data, validate=True)

                    if len(file_data) > MAX_DECODED_SIZE:
                        logger.warning(
                            "imessage send_media: decoded data too large "
                            f"({len(file_data)} bytes > {MAX_DECODED_SIZE} "
                            "bytes limit)",
                        )
                        return None

                except Exception as e:
                    logger.error(
                        f"imessage send_media: invalid base64 data: {e}",
                    )
                    return None

                url_hash = hashlib.md5(b64_data.encode()).hexdigest()[:16]
                safe_basename = self._sanitize_filename(filename_hint)
                safe_filename = f"{safe_basename}_{url_hash}{ext}"
                local_path = str(self._media_dir / safe_filename)

                # Verify the resolved path is within _media_dir
                # to prevent path traversal
                resolved_path = Path(local_path).resolve()
                media_dir_resolved = self._media_dir.resolve()
                if not str(resolved_path).startswith(str(media_dir_resolved)):
                    logger.error(
                        "imessage send_media: attempted path traversal "
                        "detected, "
                        f"blocked file creation at {resolved_path}",
                    )
                    return None

                Path(local_path).write_bytes(file_data)
                logger.info(
                    f"imessage send_media: saved base64 data to {local_path}",
                )
                return local_path
            else:
                logger.warning(
                    "imessage send_media: unsupported data URL "
                    f"format: {url[:50]}...",
                )
                return None
        except Exception as e:
            logger.error(
                f"imessage send_media: failed to process base64 data: {e}",
            )
            return None

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a single media part (image, video, audio, file).
        Downloads remote URLs to local files first, then sends via imsg.
        """
        if not self.enabled:
            return

        # Extract URL or data from the media part
        url, filename_hint, content_type = self._extract_url_and_filename(part)

        if not url:
            logger.warning(
                "imessage send_media: no URL found for media "
                f"type {content_type}",
            )
            return

        # Handle different URL types
        local_path = None

        if isinstance(url, str):
            if url.startswith(("http://", "https://")):
                local_path = await self._handle_remote_url(
                    url,
                    filename_hint,
                    content_type,
                )
            elif url.startswith("data:"):
                local_path = await self._handle_data_url(
                    url,
                    content_type,
                    filename_hint,
                )
            else:
                local_path = await self._handle_local_file(url)

        if local_path and Path(local_path).exists():
            logger.info(f"imessage sending media file: {local_path}")
            await self.send(to_handle, "", meta, local_path)
        else:
            logger.warning(
                "imessage send_media: could not resolve valid file "
                f"path for {url}",
            )
