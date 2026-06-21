# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Slack native streaming output with automatic fallback.

Slack's "Agents & AI Apps" streaming API
(``chat.startStream`` / ``chat.appendStream`` / ``chat.stopStream``)
provides incremental message rendering — but only within threads.
This module wraps that API and falls back to ``chat_update`` when
native streaming is unavailable or fails.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict

from slack_sdk.errors import SlackRequestError

from .constants import (
    SLACK_STREAM_BUFFER_SIZE,
    SLACK_STREAM_EDIT_MIN_INTERVAL,
)
from .format import markdown_to_slack_mrkdwn

if TYPE_CHECKING:
    from slack_sdk.web.async_chat_stream import AsyncChatStream
    from slack_sdk.web.async_client import AsyncWebClient
    from .channel import SlackChannel

logger = logging.getLogger(__name__)


# ── Exceptions ──


class SlackStreamNotDeliveredError(Exception):
    """Native streaming did not deliver any content to Slack.

    The caller should fall back to ``chat_postMessage`` or
    ``chat_update`` as appropriate.
    """

    def __init__(self, pending_text: str = ""):
        self.pending_text = pending_text
        super().__init__(
            f"Slack native stream not delivered: {pending_text[:80]}",
        )


# ── Session state ──


@dataclass
class SlackStreamSession:
    """State for one native streaming session.

    Wraps a ``slack_sdk.AsyncChatStream`` instance.
    """

    streamer: "AsyncChatStream"
    channel: str
    thread_ts: str
    stopped: bool = False
    delivered: bool = False


@dataclass
class SlackEditStreamSession:
    """State for one ``chat_update`` fallback streaming session."""

    channel: str
    message_ts: str
    accumulated_text: str = ""
    last_flush: float = field(default_factory=time.monotonic)
    stopped: bool = False


# ── Manager ──


class SlackStreamManager:
    """Orchestrate Slack streaming output.

    Two modes are supported:

    **Native streaming** (``start_native_stream`` / ``append_native`` /
    ``stop_native``)
        Uses ``AsyncWebClient.chat_stream()`` → ``AsyncChatStream``.
        Requires a ``thread_ts`` (streamed messages must be thread replies).
        The SDK buffers text locally and flushes to Slack in bulk;
        ``append_native`` returns *True* when content has actually been
        sent to Slack.

    **Edit fallback** (``start_edit_stream`` / ``append_edit`` /
    ``stop_edit``)
        Posts a placeholder message first, then repeatedly calls
        ``chat_update`` at a minimum interval.  Used when ``thread_ts``
        is unavailable or native streaming raises
        :class:`SlackStreamNotDeliveredError`.
    """

    def __init__(self, channel: "SlackChannel"):
        self._channel = channel
        self._native_sessions: Dict[str, SlackStreamSession] = {}
        self._edit_sessions: Dict[str, SlackEditStreamSession] = {}

    # ── Native streaming ──

    async def start_native_stream(
        self,
        channel_id: str,
        thread_ts: str,
        *,
        team_id: str = "",
        user_id: str = "",
    ) -> SlackStreamSession:
        """Create and start a native Slack streaming session.

        Parameters
        ----------
        channel_id:
            Slack channel or DM ID.
        thread_ts:
            Parent message timestamp — **required** by the streaming API.
        team_id:
            Workspace team ID (optional but recommended for channels).
        user_id:
            Recipient user ID (optional but recommended for channels).
        """
        old = self._native_sessions.get(channel_id)
        if old and not old.stopped:
            logger.warning(
                "slack stream: replacing stale native session for %s",
                channel_id,
            )
            try:
                await old.streamer.stop()
            except Exception:
                pass
        client = await self._channel.get_client()
        streamer = await client.chat_stream(
            channel=channel_id,
            thread_ts=thread_ts,
            recipient_team_id=team_id or None,
            recipient_user_id=user_id or None,
            buffer_size=SLACK_STREAM_BUFFER_SIZE,
            logger=logger,
        )
        session = SlackStreamSession(
            streamer=streamer,
            channel=channel_id,
            thread_ts=thread_ts,
        )
        self._native_sessions[channel_id] = session
        logger.debug(
            "slack native stream started: channel=%s thread_ts=%s",
            channel_id,
            thread_ts,
        )
        return session

    async def append_native(
        self,
        session: SlackStreamSession,
        text: str,
    ) -> bool:
        """Append *text* to a native streaming session.

        Returns *True* when the content has been flushed to Slack
        (``append`` returned a non-*None* response).  Returns *False*
        when the content is still buffered locally.

        Raises :class:`SlackStreamNotDeliveredError` when the stream
        has never been delivered and the API returns an error.
        """
        if session.stopped or not text:
            return False

        try:
            result = await session.streamer.append(markdown_text=text)
            if result is not None:
                session.delivered = True
                return True
            return False
        except SlackRequestError as exc:
            if session.delivered:
                # Content already arrived — benign transient error.
                logger.debug(
                    "slack native append benign error (already delivered): %s",
                    exc,
                )
                return False
            raise SlackStreamNotDeliveredError(text) from exc

    async def stop_native(
        self,
        session: SlackStreamSession,
        final_text: str = "",
    ) -> None:
        """Finalise a native streaming session.

        The message becomes a regular (non-streaming) Slack message
        after this call.

        Raises :class:`SlackStreamNotDeliveredError` when the stream
        never delivered any content.
        """
        if session.stopped:
            return
        session.stopped = True
        try:
            await session.streamer.stop(
                markdown_text=final_text if final_text else None,
            )
            session.delivered = True
        except SlackRequestError as exc:
            if session.delivered:
                logger.debug(
                    "slack native stop benign error (already delivered)",
                )
            else:
                raise SlackStreamNotDeliveredError(final_text) from exc
        finally:
            self._native_sessions.pop(session.channel, None)

    # ── Edit fallback ──

    async def start_edit_stream(
        self,
        channel_id: str,
        message_ts: str,
    ) -> SlackEditStreamSession:
        """Create a ``chat_update``-based streaming session.

        The caller must have already posted a placeholder message whose
        ``.ts`` is *message_ts*.
        """
        old = self._edit_sessions.get(channel_id)
        if old and not old.stopped:
            logger.warning(
                "slack stream: replacing stale edit session for %s",
                channel_id,
            )
            old.stopped = True
        session = SlackEditStreamSession(
            channel=channel_id,
            message_ts=message_ts,
        )
        self._edit_sessions[channel_id] = session
        return session

    async def append_edit(
        self,
        session: SlackEditStreamSession,
        text: str,
    ) -> None:
        """Accumulate *text* and flush to Slack via ``chat_update``.

        Flushing is rate-limited to one API call per
        ``SLACK_STREAM_EDIT_MIN_INTERVAL`` seconds.
        """
        if session.stopped or not text:
            return
        session.accumulated_text += text
        now = time.monotonic()
        if now - session.last_flush < SLACK_STREAM_EDIT_MIN_INTERVAL:
            return
        session.last_flush = now
        await self._flush_edit(session)

    async def stop_edit(
        self,
        session: SlackEditStreamSession,
        final_text: str = "",
    ) -> None:
        """Finalise an edit-stream session with one last update."""
        if session.stopped:
            return
        session.stopped = True
        if final_text:
            session.accumulated_text += final_text
        await self._flush_edit(session)
        self._edit_sessions.pop(session.channel, None)

    async def _flush_edit(self, session: SlackEditStreamSession) -> None:
        """Send accumulated text via chat_update. Raises on failure
        so the caller can fall back to a final chat_postMessage."""
        client = await self._channel.get_client()
        try:
            await client.chat_update(
                channel=session.channel,
                ts=session.message_ts,
                text=markdown_to_slack_mrkdwn(session.accumulated_text),
            )
        except Exception:
            logger.exception(
                "slack edit stream: chat_update failed channel=%s ts=%s",
                session.channel,
                session.message_ts,
            )
            raise

    # ── Cleanup ──

    async def cleanup_all(self) -> None:
        """Gracefully shut down all active streaming sessions."""
        for ch_id in list(self._native_sessions):
            await self.cleanup(ch_id)
        for ch_id in list(self._edit_sessions):
            await self.cleanup(ch_id)

    async def cleanup(self, channel_id: str) -> None:
        """Gracefully shut down streaming sessions for *channel_id*.

        Native sessions are stopped via ``AsyncChatStream.stop()`` so the
        SDK can finalise the streaming message.  Edit sessions receive a
        final ``chat_update`` flush if there is accumulated text.
        Failures are logged but not re-raised — cleanup is best-effort
        during shutdown.
        """
        native = self._native_sessions.pop(channel_id, None)
        if native is not None and not native.stopped:
            native.stopped = True
            try:
                await native.streamer.stop()
            except Exception:
                logger.debug(
                    "slack stream: cleanup native failed channel=%s",
                    channel_id,
                    exc_info=True,
                )

        edit = self._edit_sessions.pop(channel_id, None)
        if edit is not None and not edit.stopped:
            edit.stopped = True
            if edit.accumulated_text:
                try:
                    await self._flush_edit(edit)
                except Exception:
                    logger.debug(
                        "slack stream: cleanup edit failed channel=%s",
                        channel_id,
                        exc_info=True,
                    )
