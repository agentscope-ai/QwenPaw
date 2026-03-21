# -*- coding: utf-8 -*-
# pylint: disable=protected-access
# ChannelManager is the framework owner of BaseChannel and must call
# _is_native_payload and _consume_one_request as part of the contract.

from __future__ import annotations

import asyncio
import logging

from typing import (
    Callable,
    List,
    Optional,
    Any,
    Dict,
    Set,
    Tuple,
    TYPE_CHECKING,
)

from .base import BaseChannel, ContentType, ProcessHandler, TextContent
from .registry import get_channel_registry
from ...config import get_available_channels

if TYPE_CHECKING:
    from ....config.config import Config

logger = logging.getLogger(__name__)

# Callback when user reply was sent: (channel, user_id, session_id)
OnLastDispatch = Optional[Callable[[str, str, str], None]]

# Default max size per channel queue
_CHANNEL_QUEUE_MAXSIZE = 1000

# Workers per channel: drain same-session from queue and process in parallel
_CONSUMER_WORKERS_PER_CHANNEL = 4


def _drain_same_key(
    q: asyncio.Queue,
    ch: BaseChannel,
    key: str,
    first_payload: Any,
) -> List[Any]:
    """Drain queue of payloads with same debounce key; return batch."""
    batch = [first_payload]
    put_back: List[Any] = []
    while True:
        try:
            p = q.get_nowait()
        except asyncio.QueueEmpty:
            break
        if ch.get_debounce_key(p) == key:
            batch.append(p)
        else:
            put_back.append(p)
    for p in put_back:
        q.put_nowait(p)
    return batch


async def _process_batch(ch: BaseChannel, batch: List[Any]) -> None:
    """Merge if needed and process one payload (native or request)."""
    if ch.channel == "dingtalk" and batch and ch._is_native_payload(batch[0]):
        first = batch[0] if isinstance(batch[0], dict) else {}
        logger.info(
            "manager _process_batch dingtalk: batch_len=%s first_has_sw=%s",
            len(batch),
            bool(first.get("session_webhook")),
        )
    if len(batch) > 1 and ch._is_native_payload(batch[0]):
        merged = ch.merge_native_items(batch)
        if ch.channel == "dingtalk" and isinstance(merged, dict):
            logger.info(
                "manager _process_batch dingtalk merged: has_sw=%s",
                bool(merged.get("session_webhook")),
            )
        await ch._consume_one_request(merged)
    elif len(batch) > 1:
        merged = ch.merge_requests(batch)
        if merged is not None:
            await ch._consume_one_request(merged)
        else:
            await ch.consume_one(batch[0])
    elif ch._is_native_payload(batch[0]):
        await ch._consume_one_request(batch[0])
    else:
        await ch.consume_one(batch[0])


def _put_pending_merged(
    ch: BaseChannel,
    q: asyncio.Queue,
    pending: List[Any],
) -> None:
    """Merge pending items if multiple and put one or more on queue."""
    if not pending:
        return
    merged = None
    if len(pending) > 1 and ch._is_native_payload(pending[0]):
        merged = ch.merge_native_items(pending)
    elif len(pending) > 1:
        merged = ch.merge_requests(pending)
    if merged is not None:
        q.put_nowait(merged)
    else:
        for p in pending:
            q.put_nowait(p)


class ChannelManager:
    """Owns queues and consumer loops; channels define how to consume via
    consume_one(). Enqueue via enqueue(channel_id, payload) (thread-safe).
    """

    def __init__(self, channels: List[BaseChannel]):
        self.channels = channels
        self._lock = asyncio.Lock()
        self._queues: Dict[str, asyncio.Queue] = {}
        self._consumer_tasks: List[asyncio.Task[None]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Session in progress: (channel_id, debounce_key) -> True while worker
        # is processing. New payloads for that key go to _pending, merged
        # when worker finishes.
        self._in_progress: Set[Tuple[str, str]] = set()
        self._pending: Dict[Tuple[str, str], List[Any]] = {}
        # Per-key lock: same session is claimed by one worker for drain so
        # [image1, text] are not split across workers (avoids no-text
        # debounce reordering and duplicate content in AgentRequest).
        self._key_locks: Dict[Tuple[str, str], asyncio.Lock] = {}

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_last_dispatch: OnLastDispatch = None,
    ) -> "ChannelManager":
        """
        Create channels from env and inject unified process
        (AgentRequest -> Event stream).
        process is typically runner.stream_query, handled by AgentApp's
        process endpoint.
        on_last_dispatch: called when a user send+reply was sent.
        """
        available = get_available_channels()
        registry = get_channel_registry()
        channels: list[BaseChannel] = [
            ch_cls.from_env(process, on_reply_sent=on_last_dispatch)
            for key, ch_cls in registry.items()
            if key in available
        ]
        return cls(channels)

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: "Config",
        on_last_dispatch: OnLastDispatch = None,
    ) -> "ChannelManager":
        """Create channels from config (config.json)."""
        available = get_available_channels()
        ch = config.channels
        show_tool_details = getattr(config, "show_tool_details", True)
        extra = getattr(ch, "__pydantic_extra__", None) or {}

        channels: list[BaseChannel] = []
        for key, ch_cls in get_channel_registry().items():
            if key not in available:
                continue
            ch_cfg = getattr(ch, key, None)
            if ch_cfg is None and key in extra:
                from types import SimpleNamespace

                raw = extra[key]
                ch_cfg = (
                    SimpleNamespace(**raw) if isinstance(raw, dict) else raw
                )
            if ch_cfg is None:
                continue
            filter_tool_messages = getattr(
                ch_cfg,
                "filter_tool_messages",
                False,
            )
            filter_thinking = getattr(
                ch_cfg,
                "filter_thinking",
                False,
            )
            channels.append(
                ch_cls.from_config(
                    process,
                    ch_cfg,
                    on_reply_sent=on_last_dispatch,
                    show_tool_details=show_tool_details,
                    filter_tool_messages=filter_tool_messages,
                    filter_thinking=filter_thinking,
                ),
            )
        return cls(channels)

    def _make_enqueue_cb(self, channel_id: str) -> Callable[[Any], None]:
        """Return a callback that enqueues payload for the given channel."""

        def cb(payload: Any) -> None:
            self.enqueue(channel_id, payload)

        return cb

    def _enqueue_one(self, channel_id: str, payload: Any) -> None:
        """Run on event loop: enqueue or append to pending if session in
        progress.
        """
        q = self._queues.get(channel_id)
        if not q:
            logger.debug("enqueue: no queue for channel=%s", channel_id)
            return
        ch = next(
            (c for c in self.channels if c.channel == channel_id),
            None,
        )
        if not ch:
            q.put_nowait(payload)
            return
        key = ch.get_debounce_key(payload)
        if channel_id == "dingtalk" and isinstance(payload, dict):
            logger.info(
                "manager _enqueue_one dingtalk: key=%s in_progress=%s "
                "payload_has_sw=%s -> %s",
                key,
                (channel_id, key) in self._in_progress,
                bool(payload.get("session_webhook")),
                "pending"
                if (channel_id, key) in self._in_progress
                else "queue",
            )
        if (channel_id, key) in self._in_progress:
            self._pending.setdefault((channel_id, key), []).append(payload)
            return
        q.put_nowait(payload)

    def enqueue(self, channel_id: str, payload: Any) -> None:
        """Enqueue a payload for the channel. Thread-safe (e.g. from sync
        WebSocket or polling thread). If this session is already being
        processed, payload is held in pending and merged when the worker
        finishes. Call after start_all().
        """
        if not self._queues.get(channel_id):
            logger.debug("enqueue: no queue for channel=%s", channel_id)
            return
        if self._loop is None:
            logger.warning("enqueue: loop not set for channel=%s", channel_id)
            return
        self._loop.call_soon_threadsafe(
            self._enqueue_one,
            channel_id,
            payload,
        )

    async def _consume_channel_loop(
        self,
        channel_id: str,
        worker_index: int,
    ) -> None:
        """
        Run one consumer worker: pop payload, drain queue of same session,
        mark session in progress, merge batch (native or requests), process
        once, then flush any pending for this session (merged) back to queue.
        Multiple workers per channel allow different sessions in parallel.
        """
        q = self._queues.get(channel_id)
        if not q:
            return
        while True:
            try:
                payload = await q.get()
                ch = await self.get_channel(channel_id)
                if not ch:
                    continue
                key = ch.get_debounce_key(payload)
                key_lock = self._key_locks.setdefault(
                    (channel_id, key),
                    asyncio.Lock(),
                )
                async with key_lock:
                    self._in_progress.add((channel_id, key))
                    batch = _drain_same_key(q, ch, key, payload)
                try:
                    await _process_batch(ch, batch)
                finally:
                    self._in_progress.discard((channel_id, key))
                    pending = self._pending.pop((channel_id, key), [])
                    _put_pending_merged(ch, q, pending)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "channel consume_one failed: channel=%s worker=%s",
                    channel_id,
                    worker_index,
                )

    async def start_all(self) -> None:
        self._loop = asyncio.get_running_loop()
        async with self._lock:
            snapshot = list(self.channels)
        for ch in snapshot:
            if getattr(ch, "uses_manager_queue", True):
                self._queues[ch.channel] = asyncio.Queue(
                    maxsize=_CHANNEL_QUEUE_MAXSIZE,
                )
                ch.set_enqueue(self._make_enqueue_cb(ch.channel))
        for ch in snapshot:
            if ch.channel in self._queues:
                for w in range(_CONSUMER_WORKERS_PER_CHANNEL):
                    task = asyncio.create_task(
                        self._consume_channel_loop(ch.channel, w),
                        name=f"channel_consumer_{ch.channel}_{w}",
                    )
                    self._consumer_tasks.append(task)
        logger.debug(
            "starting channels=%s queues=%s",
            [g.channel for g in snapshot],
            list(self._queues.keys()),
        )
        for g in snapshot:
            try:
                await g.start()
            except Exception:
                logger.exception(f"failed to start channels={g.channel}")

    async def stop_all(self) -> None:
        self._in_progress.clear()
        self._pending.clear()
        for task in self._consumer_tasks:
            task.cancel()
        if self._consumer_tasks:
            _, pending = await asyncio.wait(
                self._consumer_tasks,
                timeout=5.0,
                return_when=asyncio.ALL_COMPLETED,
            )
            if pending:
                logger.warning(
                    "stop_all: %s consumer task(s) still pending after 5s",
                    len(pending),
                )
        self._consumer_tasks.clear()
        self._queues.clear()
        async with self._lock:
            snapshot = list(self.channels)
        for ch in snapshot:
            ch.set_enqueue(None)

        async def _stop(ch):
            try:
                await ch.stop()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(f"failed to stop channels={ch.channel}")

        await asyncio.gather(*[_stop(g) for g in reversed(snapshot)])

    async def get_channel(self, channel: str) -> Optional[BaseChannel]:
        async with self._lock:
            for ch in self.channels:
                if ch.channel == channel:
                    return ch
            return None

    async def replace_channel(
        self,
        new_channel: BaseChannel,
    ) -> None:
        """Replace a single channel by name.

        Flow: ensure queue+enqueue for new channel → start new (outside lock)
        → swap + stop old (inside lock). Lock only guards the swap+stop.

        Args:
            new_channel: New channel instance to replace with
        """
        new_channel_name = new_channel.channel
        # 1) Ensure queue and enqueue callback before start() so the channel
        #    (e.g. DingTalk) registers its handler with a valid callback.
        if new_channel_name not in self._queues:
            if getattr(new_channel, "uses_manager_queue", True):
                self._queues[new_channel_name] = asyncio.Queue(
                    maxsize=_CHANNEL_QUEUE_MAXSIZE,
                )
                for w in range(_CONSUMER_WORKERS_PER_CHANNEL):
                    task = asyncio.create_task(
                        self._consume_channel_loop(new_channel_name, w),
                        name=f"channel_consumer_{new_channel_name}_{w}",
                    )
                    self._consumer_tasks.append(task)
        new_channel.set_enqueue(self._make_enqueue_cb(new_channel_name))

        # 2) Start new channel outside lock (may be slow, e.g. DingTalk stream)
        logger.info(f"Pre-starting new channel: {new_channel_name}")
        try:
            await new_channel.start()
        except Exception:
            logger.exception(
                f"Failed to start new channel: {new_channel_name}",
            )
            try:
                await new_channel.stop()
            except Exception:
                pass
            raise

        # 3) Swap + stop old inside lock
        async with self._lock:
            old_channel = None
            for i, ch in enumerate(self.channels):
                if ch.channel == new_channel_name:
                    old_channel = ch
                    self.channels[i] = new_channel
                    break

            if old_channel is None:
                logger.info(f"Adding new channel: {new_channel_name}")
                self.channels.append(new_channel)
            else:
                logger.info(f"Stopping old channel: {old_channel.channel}")
                try:
                    await old_channel.stop()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception(
                        f"Failed to stop old channel: {old_channel.channel}",
                    )

    async def send_event(
        self,
        *,
        channel: str,
        user_id: str,
        session_id: str,
        event: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        ch = await self.get_channel(channel)
        if not ch:
            raise KeyError(f"channel not found: {channel}")
        merged_meta = dict(meta or {})
        merged_meta["session_id"] = session_id
        merged_meta["user_id"] = user_id
        bot_prefix = getattr(ch, "bot_prefix", None) or getattr(
            ch,
            "_bot_prefix",
            None,
        )
        if bot_prefix and "bot_prefix" not in merged_meta:
            merged_meta["bot_prefix"] = bot_prefix
        await ch.send_event(
            user_id=user_id,
            session_id=session_id,
            event=event,
            meta=merged_meta,
        )

    async def send_text(
        self,
        *,
        channel: str,
        user_id: str,
        session_id: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send plain text to a specific channel
        (used for scheduled jobs like task_type='text').
        """
        ch = await self.get_channel(channel.lower())
        if not ch:
            raise KeyError(f"channel not found: {channel}")

        # Convert (user_id, session_id) into the channel-specific target handle
        to_handle = ch.to_handle_from_target(
            user_id=user_id,
            session_id=session_id,
        )
        ch_name = getattr(ch, "channel", channel)
        logger.info(
            "channel send_text: channel=%s user_id=%s session_id=%s "
            "to_handle=%s",
            ch_name,
            (user_id or "")[:40],
            (session_id or "")[:40],
            (to_handle or "")[:60],
        )

        # Keep the same behavior as the agent pipeline:
        # if the channel has a fixed bot prefix, merge it into meta so
        # send_content_parts can use it.
        merged_meta = dict(meta or {})
        bot_prefix = getattr(ch, "bot_prefix", None) or getattr(
            ch,
            "_bot_prefix",
            None,
        )
        if bot_prefix and "bot_prefix" not in merged_meta:
            merged_meta["bot_prefix"] = bot_prefix
        merged_meta["session_id"] = session_id
        merged_meta["user_id"] = user_id

        # Send as content parts (single text part; use TextContent so channel
        # getattr(p, "type") / getattr(p, "text") work)
        await ch.send_content_parts(
            to_handle,
            [TextContent(type=ContentType.TEXT, text=text)],
            merged_meta,
        )
