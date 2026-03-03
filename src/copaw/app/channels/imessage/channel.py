# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import os
import time
import sqlite3
import subprocess
import threading
import shutil
import asyncio
from typing import Any, Dict, Optional

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ContentType,
)

from ....config.config import IMessageChannelConfig

from ..base import BaseChannel, OnReplySent, ProcessHandler

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

    def _send_sync(self, to_handle: str, text: str) -> None:
        if not self._imsg_path:
            raise RuntimeError(
                "iMessage channel not initialized (imsg path missing).",
            )
        # Capture stdout/stderr so imsg's "sent" (or similar) does not
        # appear in our process output.
        result = subprocess.run(
            [self._imsg_path, "send", "--to", to_handle, "--text", text],
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
    ) -> None:
        if not self.enabled:
            return
        await asyncio.to_thread(self._send_sync, to_handle, text)
