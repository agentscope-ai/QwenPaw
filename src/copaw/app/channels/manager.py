# -*- coding: utf-8 -*-
# pylint: disable=protected-access
# ChannelManager is the framework owner of BaseChannel and must call
# _is_native_payload and _consume_one_request as part of the contract.

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

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
from ..runner.daemon_commands import parse_daemon_query
from ..runner.command_router import PrioritizedPayload
from ...agents.command_handler import CommandHandler as ConvCommandHandler

if TYPE_CHECKING:
    from ....config.config import Config
    from ..runner.command_router import CommandRouter

logger = logging.getLogger(__name__)

# Callback when user reply was sent: (channel, user_id, session_id)
OnLastDispatch = Optional[Callable[[str, str, str], None]]

# Default max size per channel queue
_CHANNEL_QUEUE_MAXSIZE = 1000

# Workers per channel: drain same-session from queue and process in parallel
_CONSUMER_WORKERS_PER_CHANNEL = 4


def _extract_text_from_payload(ch: BaseChannel, payload: Any) -> str:
    """Extract first text content from a payload for /stop detection."""
    try:
        request = ch._payload_to_request(payload)
        if not request.input:
            return ""
        contents = list(
            getattr(request.input[0], "content", None) or [],
        )
        for c in contents:
            ctype = getattr(c, "type", None)
            if ctype in (ContentType.TEXT, "text"):
                return getattr(c, "text", "") or ""
        return ""
    except Exception:
        logger.debug(
            "Failed to extract text from payload for /stop detection",
            exc_info=True,
        )
        return ""


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
        # Track active processing tasks per session key for /stop cancellation
        self._active_process_tasks: Dict[
            Tuple[str, str],
            asyncio.Task,
        ] = {}
        # -- Dual-queue: command queue attributes -----------------------
        self._command_queues: Dict[str, asyncio.PriorityQueue] = {}
        self._command_router: CommandRouter | None = None
        self._command_seq: int = 0

    # ------------------------------------------------------------------
    # Dual-queue: command router wiring
    # ------------------------------------------------------------------

    def set_command_router(self, router: CommandRouter) -> None:
        """Attach a :class:`CommandRouter` for classification."""
        self._command_router = router

    # pylint: disable=too-many-return-statements
    def _classify_command(
        self,
        ch: BaseChannel,
        payload: Any,
    ) -> tuple[str, list[str]] | None:
        """Extract payload text and check if it is a registered command.

        Returns:
            ``(command_name, command_args)`` when the payload matches a
            registered command, or ``None`` for normal messages.
        """
        if self._command_router is None:
            return None

        # 1. Extract text from payload
        try:
            text = _extract_text_from_payload(ch, payload)
        except Exception:
            logger.debug(
                "classify_command: failed to extract text from payload",
                exc_info=True,
            )
            return None

        if not text or not text.strip().startswith("/"):
            return None

        registered = self._command_router.get_registered_commands()

        # 2. Try daemon command parsing
        #    (handles /daemon <sub> and short aliases)
        parsed = parse_daemon_query(text)
        if parsed is not None:
            cmd_name, cmd_args = parsed
            if cmd_name in registered:
                return (cmd_name, cmd_args)
            # /daemon <sub> resolves to sub; check if
            # "daemon" itself is registered
            if "daemon" in registered:
                # Re-parse: the raw text was /daemon <sub>,
                # route via "daemon" handler
                raw = text.strip()
                parts = raw.lstrip("/").split()
                if parts and parts[0].lower() == "daemon":
                    return ("daemon", parts[1:] if len(parts) > 1 else [])

        # 3. Try conversation command parsing
        stripped = text.strip()
        cmd_candidate = (
            stripped.lstrip("/").split()[0] if stripped.startswith("/") else ""
        )
        if cmd_candidate in ConvCommandHandler.SYSTEM_COMMANDS:
            if cmd_candidate in registered:
                args = stripped.lstrip("/").split()[1:]
                return (cmd_candidate, args)

        # 4. Generic fallback: check if first word after / is registered
        if cmd_candidate and cmd_candidate in registered:
            args = stripped.lstrip("/").split()[1:]
            return (cmd_candidate, args)

        return None

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
    # pylint: disable=too-many-branches
    def from_config(
        cls,
        process: ProcessHandler,
        config: "Config",
        on_last_dispatch: OnLastDispatch = None,
        workspace_dir: Path | None = None,
    ) -> "ChannelManager":
        """Create channels from config (config.json or agent.json).

        Args:
            process: Process handler for agent communication
            config: Configuration object with channels
            on_last_dispatch: Callback for dispatch events
            workspace_dir: Agent workspace directory for channel state files
        """
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
                ch_cfg = extra[key]
            if ch_cfg is None:
                continue
            if isinstance(ch_cfg, dict):
                from types import SimpleNamespace
                from ...config.config import BaseChannelConfig

                defaults = BaseChannelConfig().model_dump()
                defaults.update(ch_cfg)
                ch_cfg = SimpleNamespace(**defaults)

            # Check if channel is enabled
            # Handle both Pydantic objects (built-in)
            # and dicts (customchannels)
            if isinstance(ch_cfg, dict):
                enabled = ch_cfg.get("enabled", False)
            else:
                enabled = getattr(ch_cfg, "enabled", False)
            if not enabled:
                continue

            # Handle both Pydantic objects (built-in)
            # and dicts (custom channels)
            if isinstance(ch_cfg, dict):
                filter_tool_messages = ch_cfg.get(
                    "filter_tool_messages",
                    False,
                )
                filter_thinking = ch_cfg.get("filter_thinking", False)
            else:
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

            from_config_kwargs = {
                "process": process,
                "config": ch_cfg,
                "on_reply_sent": on_last_dispatch,
                "show_tool_details": show_tool_details,
                "filter_tool_messages": filter_tool_messages,
                "filter_thinking": filter_thinking,
                "workspace_dir": workspace_dir,
            }

            # Only pass kwargs that the channel's from_config accepts
            import inspect

            sig = inspect.signature(ch_cls.from_config)
            if any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            ):
                filtered_kwargs = from_config_kwargs
            else:
                filtered_kwargs = {
                    k: v
                    for k, v in from_config_kwargs.items()
                    if k in sig.parameters
                }

            try:
                channels.append(ch_cls.from_config(**filtered_kwargs))
            except Exception as e:
                logger.warning(
                    "Failed to initialize channel '%s', skipping: %s",
                    key,
                    e,
                )
                continue

        return cls(channels)

    def _make_enqueue_cb(self, channel_id: str) -> Callable[[Any], None]:
        """Return a callback that enqueues payload for the given channel."""

        def cb(payload: Any) -> None:
            self.enqueue(channel_id, payload)

        return cb

    def _enqueue_one(self, channel_id: str, payload: Any) -> None:
        """Run on event loop: classify message and route to CommandQueue or
        DataQueue. Command messages bypass the in_progress/pending mechanism.
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

        # --- CommandClassifier: route commands to CommandQueue ---
        classified = self._classify_command(ch, payload)
        if classified is not None and channel_id in self._command_queues:
            command_name, command_args = classified
            priority = (
                self._command_router.get_priority(command_name)
                if self._command_router is not None
                else 2  # NORMAL fallback
            )
            self._command_seq += 1
            item = PrioritizedPayload(
                priority=priority,
                sequence=self._command_seq,
                payload=payload,
                command_name=command_name,
                command_args=command_args,
            )
            self._command_queues[channel_id].put_nowait(item)
            return

        # --- Normal message: DataQueue logic (in_progress/pending) ---
        key = ch.get_debounce_key(payload)
        if channel_id == "dingtalk" and isinstance(payload, dict):
            logger.info(
                "manager _enqueue_one dingtalk: key=%s in_progress=%s "
                "payload_has_sw=%s -> %s",
                key,
                (channel_id, key) in self._in_progress,
                bool(payload.get("session_webhook")),
                (
                    "pending"
                    if (channel_id, key) in self._in_progress
                    else "queue"
                ),
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
                try:
                    async with key_lock:
                        self._in_progress.add((channel_id, key))
                        batch = _drain_same_key(q, ch, key, payload)
                    process_task = asyncio.create_task(
                        _process_batch(ch, batch),
                    )
                    self._active_process_tasks[(channel_id, key)] = (
                        process_task
                    )
                    try:
                        await process_task
                    except asyncio.CancelledError:
                        logger.info(
                            "/stop: task cancelled for key=%s",
                            key,
                        )
                finally:
                    self._active_process_tasks.pop((channel_id, key), None)
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

    # ------------------------------------------------------------------
    # Dual-queue: command consume loop
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_msg_text(msg: Any) -> str:
        """Extract the first text block from a ``Msg`` response."""
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                # Handle both dict (Msg serializes TextBlock
                # to dict) and objects
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        return block.get("text", "") or ""
                elif getattr(block, "type", None) == "text":
                    return getattr(block, "text", "") or ""
            return ""
        return str(content) if content else ""

    async def _consume_command_loop(self, channel_id: str) -> None:
        """Command consume loop: dequeue from PriorityQueue by priority and
        dispatch via CommandRouter.

        Each channel has exactly one command consumer (single worker) to
        avoid concurrency issues with command processing.
        """
        from ..runner.command_router import CommandContext

        cq = self._command_queues.get(channel_id)
        if not cq:
            return
        while True:
            try:
                item: PrioritizedPayload = await cq.get()

                # Find the channel instance
                ch = next(
                    (c for c in self.channels if c.channel == channel_id),
                    None,
                )
                if not ch:
                    logger.warning(
                        "command consume: channel not found: %s",
                        channel_id,
                    )
                    continue

                if self._command_router is None:
                    logger.warning(
                        "command consume: no command router set",
                    )
                    continue

                # Build CommandContext from PrioritizedPayload
                try:
                    request = ch._payload_to_request(item.payload)
                    session_id = getattr(request, "session_id", "") or ""
                    user_id = getattr(request, "user_id", "") or ""
                except Exception:
                    logger.debug(
                        "command consume: failed to parse payload for "
                        "context, using defaults",
                        exc_info=True,
                    )
                    session_id = ""
                    user_id = ""
                    request = None

                raw_query = f"/{item.command_name}" + (
                    " " + " ".join(item.command_args)
                    if item.command_args
                    else ""
                )

                context = CommandContext(
                    channel=ch,
                    channel_id=channel_id,
                    session_id=session_id,
                    user_id=user_id,
                    command_name=item.command_name,
                    command_args=item.command_args,
                    raw_query=raw_query,
                    payload=item.payload,
                    task_tracker=getattr(ch, "_task_tracker", None),
                    runner=getattr(self._command_router, "_runner", None),
                )

                # Dispatch via CommandRouter
                result_msg = await self._command_router.dispatch(context)

                # Send result back via channel
                if request is not None:
                    to_handle = ch.get_to_handle_from_request(request)
                else:
                    to_handle = ""
                text = self._extract_msg_text(result_msg)
                await ch.send(to_handle, text)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "command consume failed: channel=%s",
                    channel_id,
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
                # -- CommandQueue: one PriorityQueue + one consumer --
                self._command_queues[ch.channel] = asyncio.PriorityQueue()
                cmd_task = asyncio.create_task(
                    self._consume_command_loop(ch.channel),
                    name=f"command_consumer_{ch.channel}",
                )
                self._consumer_tasks.append(cmd_task)
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
        self._command_queues.clear()
        self._command_seq = 0
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
