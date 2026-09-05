# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Runtime→Agent notification bus (steer / inject delivery primitives).

Background work (the work-graph scheduler, and later asynchronous
specialists) reports back to the mainline Agent through this bus.  Two
delivery primitives, aligned with the Codex subagent-notification and
DeepSeek-Harness inject/steer models:

- ``steer`` (NEXT_STEP events): the fact requires an Agent action and no
  other mechanism will bring the Agent back.  It becomes one durable
  user-role RUNTIME-channel session message immediately (idempotent by
  ``client_message_id``) and wakes the dispatcher: an idle session starts
  a run within one poll interval, a busy session consumes it right after
  the current run — the mainline is never interrupted mid-run.

- ``inject`` (QUIET events): informational progress that must not spend a
  model run on its own.  It is staged in the per-project notification
  outbox and rides along with the next steer message or the end-of-run
  resume digest.

The session message log stays the single inbox; the outbox is only a
staging area whose content always ends up folded into inbox messages.

Delivery is idempotent end to end: every event carries a ``request_id``
anchored to the underlying fact (node fingerprint, project generation,
specialist run id), deduplicated once against the outbox history for
quiet events and once against the session log's ``client_message_id``
for steer messages.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
from typing import Any, Callable, Mapping

from services.runtime_files import (
    MessageChannel,
    MessagePayloadConflict,
    RuntimeSessionNotFound,
)
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.notification_store import (
    NotificationOutboxRecord,
    NotificationOutboxStore,
)
from utils.logger import setup_logger

logger = setup_logger("creator.notifications")


NOTIFICATION_SOURCE = "runtime_notification"

# Runtime-authored user messages that keep an unattended session moving.
# A steer counts the session tail's consecutive run of these sources as a
# hard fuse: past the cap the bus stops waking the Agent and downgrades to
# the outbox until a human message resets the streak.
RUNTIME_AUTONOMOUS_SOURCES = frozenset(
    {
        "yolo_auto_resume",
        "prompt_contract_resume",
        "mainline_resume",
        NOTIFICATION_SOURCE,
    },
)

NOTIFY_AUTONOMOUS_HARD_CAP = 10

# Escape valve for hard-cap parked NEXT_STEP events.  The cap stops
# autonomous steers, and a fully idle session has no future run whose
# turn boundary could inject the parked outbox — without a valve those
# events would wait forever for a human.  Once a parked NEXT_STEP event
# has aged past the cooldown on an idle session, the dispatcher may
# deliver it under its own steer identity (kind + payload preserved), at
# most ``NOTIFY_IDLE_FLUSH_BUDGET`` flush messages since the last human
# message: the flush→run→park loop stays bounded even when every flush
# spawns work that parks again.
NOTIFY_IDLE_FLUSH_BUDGET = 2
NOTIFY_IDLE_FLUSH_COOLDOWN_SECONDS = 120.0

# Window of tail messages inspected for the hard fuse; the streak resets on
# any human message, so a bounded window never miscounts a longer streak
# than the cap it guards.
_FUSE_TAIL_WINDOW = 200


class RuntimeEventKind(StrEnum):
    SUBAGENT_TERMINAL = "subagent_terminal"
    NODE_DETERMINISTIC_FAILURE = "node_deterministic_failure"
    NODE_TRANSIENT_CAP_EXHAUSTED = "node_transient_cap_exhausted"
    GRAPH_ALL_DONE = "graph_all_done"
    COMPOSE_COMPLETED = "compose_completed"
    NODE_DISPATCH_STARTED = "node_dispatch_started"
    NODE_SUCCEEDED = "node_succeeded"
    NODE_GATED = "node_gated"
    # Direct (HTTP, no agent turn) character-voice enrollment completed.
    VOICE_ENROLLED = "voice_enrolled"
    NARRATION_REGENERATED = "narration_regenerated"


class NotificationLevel(StrEnum):
    NEXT_STEP = "next_step"
    QUIET = "quiet"


EVENT_LEVELS: dict[RuntimeEventKind, NotificationLevel] = {
    RuntimeEventKind.SUBAGENT_TERMINAL: NotificationLevel.NEXT_STEP,
    RuntimeEventKind.NODE_DETERMINISTIC_FAILURE: NotificationLevel.NEXT_STEP,
    RuntimeEventKind.NODE_TRANSIENT_CAP_EXHAUSTED: (
        NotificationLevel.NEXT_STEP
    ),
    RuntimeEventKind.GRAPH_ALL_DONE: NotificationLevel.NEXT_STEP,
    RuntimeEventKind.COMPOSE_COMPLETED: NotificationLevel.NEXT_STEP,
    RuntimeEventKind.NODE_DISPATCH_STARTED: NotificationLevel.QUIET,
    RuntimeEventKind.NODE_SUCCEEDED: NotificationLevel.QUIET,
    RuntimeEventKind.NODE_GATED: NotificationLevel.QUIET,
    RuntimeEventKind.VOICE_ENROLLED: NotificationLevel.QUIET,
    RuntimeEventKind.NARRATION_REGENERATED: NotificationLevel.QUIET,
}


_STEER_HEADER = "【系统自动消息 · Runtime 通知】"
_DIGEST_HEADER = "【Runtime 进度速报】自动执行进展（进度信息，不是新的用户指令，不要为其重复生成）："
_STEER_FOOTER = (
    "本消息由 Runtime 自动发出，不是新的用户修改意见；请基于当前 Project 实际状态决定验证、修复或确认完成，不要重复已完成的工作。"
)


def render_steer_message(
    event_text: str,
    quiet_records: list[NotificationOutboxRecord],
) -> str:
    """Deterministically render one steer message (byte-stable per input)."""

    lines = [_STEER_HEADER]
    if quiet_records:
        lines.append(_DIGEST_HEADER)
        lines.extend(f"- {record.text}" for record in quiet_records)
        lines.append("")
    lines.append(event_text)
    lines.append("")
    lines.append(_STEER_FOOTER)
    return "\n".join(lines)


def render_resume_digest(
    quiet_records: list[NotificationOutboxRecord],
) -> str:
    """Digest prefix folded into a resume message; empty when nothing pends."""

    if not quiet_records:
        return ""
    lines = [_DIGEST_HEADER]
    lines.extend(f"- {record.text}" for record in quiet_records)
    lines.append("")
    return "\n".join(lines)


class RuntimeNotificationBus:
    """Route runtime events into the session inbox without disturbing runs."""

    def __init__(
        self,
        services: Any,
        *,
        wake_dispatcher: Callable[[str], None],
        store: NotificationOutboxStore | None = None,
    ) -> None:
        self.services = services
        self.store = store or NotificationOutboxStore(services.root)
        self._wake_dispatcher = wake_dispatcher
        # Projects whose idle-flush budget is exhausted, keyed to the
        # session's last_message_seq at exhaustion: the poll-driven
        # dispatcher probes every tick, and without this memo each tick
        # would repeat the budget tail scan and its log line. Any new
        # session message moves the seq and re-evaluates once.
        self._idle_flush_blocked: dict[str, int] = {}

    # -- public API ------------------------------------------------------

    async def notify(
        self,
        project_id: str,
        *,
        kind: RuntimeEventKind,
        request_id: str,
        text: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        level = EVENT_LEVELS.get(kind)
        if level is None:
            raise ValueError(
                f"runtime event kind has no declared level: {kind!r}",
            )
        if level is NotificationLevel.NEXT_STEP:
            await self.steer(
                project_id,
                kind=kind,
                request_id=request_id,
                text=text,
                payload=payload,
            )
        else:
            await self.inject(
                project_id,
                kind=kind,
                request_id=request_id,
                text=text,
                payload=payload,
            )

    async def inject(
        self,
        project_id: str,
        *,
        kind: RuntimeEventKind,
        request_id: str,
        text: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Stage a quiet event; it rides along with the next delivery."""

        try:
            await asyncio.to_thread(
                self.store.append_pending,
                project_id,
                kind=kind.value,
                level=EVENT_LEVELS[kind].value,
                request_id=request_id,
                text=text,
                payload=dict(payload or {}),
            )
        except RecordNotFoundError:
            logger.info(
                "notification dropped, project gone: %s %s",
                project_id,
                request_id,
            )

    # Guard-clause delivery pipeline: early returns are the clearest shape.
    async def steer(  # pylint: disable=too-many-return-statements
        self,
        project_id: str,
        *,
        kind: RuntimeEventKind,
        request_id: str,
        text: str,
        payload: Mapping[str, Any] | None = None,
    ) -> bool:
        """Deliver one next-step event as a durable user message + wake.

        Durable-intent-first: the event is staged in the outbox before any
        delivery attempt, so a transient Session write failure can never
        lose it — the staged record rides a later digest, turn-boundary
        injection or idle flush instead.  Assign-then-append: staged
        records are claimed under the notification lock, the message is
        rendered from the claimed set, appended outside the lock, then
        the claimed records settle to DRAINED.  Returns ``True`` when a
        message is durably present for this ``request_id``.
        """

        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:24]
        client_message_id = f"notif-{kind.value}-{digest}"
        try:
            await asyncio.to_thread(
                self.store.append_pending,
                project_id,
                kind=kind.value,
                level=EVENT_LEVELS[kind].value,
                request_id=request_id,
                text=text,
                payload=dict(payload or {}),
            )
        except RecordNotFoundError:
            logger.info(
                "steer dropped, project gone: %s %s",
                project_id,
                request_id,
            )
            return False
        try:
            session = await asyncio.to_thread(
                self.services.sessions.get_project_session_snapshot,
                project_id,
            )
        except RuntimeSessionNotFound:
            logger.info(
                "steer staged only, project %s has no runtime session",
                project_id,
            )
            return False
        conversation_id = await asyncio.to_thread(
            self._default_conversation_id,
            project_id,
            session.session_id,
        )
        if conversation_id is None:
            logger.warning(
                "steer staged only, project %s has no conversation",
                project_id,
            )
            return False
        if await asyncio.to_thread(
            self._autonomous_streak_exhausted,
            project_id,
            session,
        ):
            # The event is already staged in the outbox; parking it there
            # is the downgrade.
            logger.warning(
                "steer downgraded to outbox for %s (%d consecutive "
                "runtime-authored messages without a human): %s",
                project_id,
                NOTIFY_AUTONOMOUS_HARD_CAP,
                request_id,
            )
            return False
        try:
            # Quiet progress rides along; other NEXT_STEP records keep
            # their own delivery identity and are never folded here.
            claimed = await asyncio.to_thread(
                lambda: self.store.assign(
                    project_id,
                    client_message_id,
                    extra_request_ids=frozenset({request_id}),
                ),
            )
        except RecordNotFoundError:
            return False
        quiet_records = [
            record for record in claimed if record.request_id != request_id
        ]
        message_text = render_steer_message(text, quiet_records)
        metadata = {
            "notificationKind": kind.value,
            "requestId": request_id,
            **dict(payload or {}),
        }
        try:
            await asyncio.to_thread(
                self.services.sessions.append_message,
                project_id,
                session.session_id,
                conversation_id,
                role="user",
                content_parts=[{"type": "text", "text": message_text}],
                client_message_id=client_message_id,
                source=NOTIFICATION_SOURCE,
                channel=MessageChannel.RUNTIME,
                metadata=metadata,
            )
        except MessagePayloadConflict:
            # A message for this identity already exists, rendered from a
            # different claimed set. Only the anchor fact is provably
            # inside it; late-claimed records go back to PENDING for a
            # later delivery instead of being drained unseen.
            logger.info(
                "steer replay converged on existing message: %s %s",
                project_id,
                client_message_id,
            )
            await asyncio.to_thread(
                self.store.reopen_assigned,
                project_id,
                client_message_id,
                keep_request_ids=frozenset({request_id}),
            )
        except Exception:  # pylint: disable=broad-except
            # Delivery failure must never break the producer (scheduler
            # dispatch, specialist finalizer). Claimed records — including
            # the staged event itself — stay ASSIGNED and are rescued by
            # the next end-of-run digest.
            logger.exception(
                "steer delivery failed for %s %s",
                project_id,
                request_id,
            )
            return False
        await asyncio.to_thread(
            self.store.settle,
            project_id,
            client_message_id,
        )
        self._wake_dispatcher(project_id)
        return True

    async def drain_into_resume(
        self,
        project_id: str,
        *,
        assigned_to: str,
    ) -> str:
        """Claim pending quiet progress for an end-of-run resume message.

        The caller appends its resume message, then calls
        :meth:`settle_resume` with the same identity.  Records claimed by
        another delivery are never stolen — that delivery may be between
        its claim and its append; crash leftovers reopen on startup.
        """

        try:
            claimed = await asyncio.to_thread(
                self.store.assign,
                project_id,
                assigned_to,
            )
        except RecordNotFoundError:
            return ""
        return render_resume_digest(claimed)

    async def settle_resume(
        self,
        project_id: str,
        *,
        assigned_to: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self.store.settle,
                project_id,
                assigned_to,
            )
        except RecordNotFoundError:
            pass

    async def inject_pending_into_run(
        self,
        project_id: str,
        *,
        run_id: str,
    ) -> str:
        """Render staged progress into a live run's next model turn.

        The records turn INJECTED (no durable session message); the
        caller settles them when the run succeeds or reopens them when it
        fails, and a restart sweep reopens any survivors.
        """

        try:
            claimed = await asyncio.to_thread(
                self.store.mark_injected,
                project_id,
                run_id,
            )
        except RecordNotFoundError:
            return ""
        return render_resume_digest(claimed)

    async def settle_injected(
        self,
        project_id: str,
        *,
        run_id: str,
        success: bool,
    ) -> None:
        try:
            if success:
                await asyncio.to_thread(
                    self.store.settle,
                    project_id,
                    f"injected-{run_id}",
                )
            else:
                await asyncio.to_thread(
                    self.store.reopen_injected,
                    project_id,
                    run_id=run_id,
                )
        except RecordNotFoundError:
            pass

    async def reopen_all_injected(self, project_id: str) -> None:
        """Startup sweep: surviving claims all belong to dead deliveries.

        Reopens both INJECTED (dead run turns) and ASSIGNED (deliveries
        that crashed between claim and append) records to PENDING; this
        is the sole crash-recovery boundary for stranded claims.
        """

        try:
            await asyncio.to_thread(
                self.store.reopen_undelivered,
                project_id,
            )
        except RecordNotFoundError:
            pass

    async def cancel_pending(self, project_id: str) -> None:
        """Drop undelivered progress: a human hard stop took over."""

        try:
            await asyncio.to_thread(self.store.cancel_pending, project_id)
        except RecordNotFoundError:
            pass

    async def has_flush_candidates(self, project_id: str) -> bool:
        """Cheap probe: an aged, undelivered NEXT_STEP event exists."""

        try:
            outstanding = await asyncio.to_thread(
                self.store.undelivered_records,
                project_id,
            )
        except RecordNotFoundError:
            return False
        return bool(self._flush_candidates(outstanding))

    # Guard-clause delivery pipeline: early returns are the clearest shape.
    async def flush_pending_on_idle(  # pylint: disable=too-many-return-statements
        self,
        project_id: str,
    ) -> bool:
        """Deliver hard-cap parked NEXT_STEP events on an idle session.

        The caller (dispatcher reconcile) guarantees the session is idle:
        no active run, no queued user messages, no active review, no
        in-flight specialists.  Every parked event is delivered as its
        own message under its steer identity with its original kind and
        payload metadata — flattening a SUBAGENT_TERMINAL into a text
        digest would strip the delegation-origin identity that repair
        dedup and the paid repair budget key on.  Quiet records ride
        along with the first delivery; the wave is capped by the
        remaining flush budget.
        """

        try:
            outstanding = await asyncio.to_thread(
                self.store.undelivered_records,
                project_id,
            )
        except RecordNotFoundError:
            return False
        candidates = self._flush_candidates(outstanding)
        if not candidates:
            return False
        try:
            session = await asyncio.to_thread(
                self.services.sessions.get_project_session_snapshot,
                project_id,
            )
        except RuntimeSessionNotFound:
            return False
        if (
            self._idle_flush_blocked.get(project_id)
            == session.last_message_seq
        ):
            return False
        self._idle_flush_blocked.pop(project_id, None)
        conversation_id = await asyncio.to_thread(
            self._default_conversation_id,
            project_id,
            session.session_id,
        )
        if conversation_id is None:
            return False
        remaining_budget = await asyncio.to_thread(
            self._idle_flush_budget_remaining,
            project_id,
            session,
        )
        if remaining_budget <= 0:
            self._idle_flush_blocked[project_id] = session.last_message_seq
            logger.info(
                "idle flush skipped for %s: budget of %d used since the "
                "last human message; parked notifications wait for a human",
                project_id,
                NOTIFY_IDLE_FLUSH_BUDGET,
            )
            return False
        delivered = 0
        for index, record in enumerate(candidates[:remaining_budget]):
            if await self._flush_one(
                project_id,
                session,
                conversation_id,
                record,
                fold_quiet=index == 0,
            ):
                delivered += 1
            else:
                break
        if delivered == 0:
            return False
        logger.warning(
            "idle flush delivered %d parked notification(s) for %s",
            delivered,
            project_id,
        )
        self._wake_dispatcher(project_id)
        return True

    async def _flush_one(
        self,
        project_id: str,
        session: Any,
        conversation_id: str,
        record: NotificationOutboxRecord,
        *,
        fold_quiet: bool,
    ) -> bool:
        """Deliver one parked event under its steer identity."""

        digest = hashlib.sha256(
            record.request_id.encode("utf-8"),
        ).hexdigest()[:24]
        client_message_id = f"notif-{record.kind}-{digest}"
        try:
            claimed = await asyncio.to_thread(
                lambda: self.store.assign(
                    project_id,
                    client_message_id,
                    levels=(
                        frozenset({"quiet"}) if fold_quiet else frozenset()
                    ),
                    extra_request_ids=frozenset({record.request_id}),
                ),
            )
        except RecordNotFoundError:
            return False
        if not any(item.request_id == record.request_id for item in claimed):
            return False
        quiet_records = [
            item for item in claimed if item.request_id != record.request_id
        ]
        message_text = render_steer_message(record.text, quiet_records)
        metadata = {
            "notificationKind": record.kind,
            "requestId": record.request_id,
            **dict(record.payload),
            "idleFlush": True,
        }
        try:
            await asyncio.to_thread(
                self.services.sessions.append_message,
                project_id,
                session.session_id,
                conversation_id,
                role="user",
                content_parts=[{"type": "text", "text": message_text}],
                client_message_id=client_message_id,
                source=NOTIFICATION_SOURCE,
                channel=MessageChannel.RUNTIME,
                metadata=metadata,
            )
        except MessagePayloadConflict:
            # A message for this identity already exists (a partially
            # delivered steer); only the anchor is provably inside it.
            logger.info(
                "idle flush replay converged on existing message: %s %s",
                project_id,
                client_message_id,
            )
            await asyncio.to_thread(
                self.store.reopen_assigned,
                project_id,
                client_message_id,
                keep_request_ids=frozenset({record.request_id}),
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "idle flush delivery failed for %s %s",
                project_id,
                record.request_id,
            )
            return False
        await asyncio.to_thread(
            self.store.settle,
            project_id,
            client_message_id,
        )
        return True

    # -- internals ---------------------------------------------------------

    def _default_conversation_id(
        self,
        project_id: str,
        session_id: str,
    ) -> str | None:
        conversations = self.services.sessions.list_conversations(
            project_id,
            session_id,
        )
        default = next(
            (item for item in conversations if item.is_default),
            conversations[0] if conversations else None,
        )
        return default.conversation_id if default is not None else None

    def _autonomous_streak_exhausted(
        self,
        project_id: str,
        session: Any,
    ) -> bool:
        after_seq = max(0, session.last_message_seq - _FUSE_TAIL_WINDOW)
        messages = self.services.sessions.list_messages(
            project_id,
            session.session_id,
            after_seq=after_seq,
            limit=None,
        )
        streak = 0
        for item in reversed(messages):
            if item.role != "user":
                continue
            if item.source in RUNTIME_AUTONOMOUS_SOURCES:
                streak += 1
                if streak >= NOTIFY_AUTONOMOUS_HARD_CAP:
                    return True
                continue
            break
        return False

    def _flush_candidates(
        self,
        outstanding: list[NotificationOutboxRecord],
    ) -> list[NotificationOutboxRecord]:
        """Undelivered NEXT_STEP records aged past the cooldown, oldest first.

        The age gate doubles as the idleness signal: had any run happened
        since a record parked, its steer identity would already have been
        retried or delivered.
        """

        now = datetime.now(UTC)
        return sorted(
            (
                record
                for record in outstanding
                if record.level == "next_step"
                and (now - record.created_at).total_seconds()
                >= NOTIFY_IDLE_FLUSH_COOLDOWN_SECONDS
            ),
            key=lambda record: (record.created_at, record.record_id),
        )

    def _idle_flush_budget_remaining(
        self,
        project_id: str,
        session: Any,
    ) -> int:
        after_seq = max(0, session.last_message_seq - _FUSE_TAIL_WINDOW)
        messages = self.services.sessions.list_messages(
            project_id,
            session.session_id,
            after_seq=after_seq,
            limit=None,
        )
        flushes = 0
        for item in reversed(messages):
            if item.role != "user":
                continue
            if item.source not in RUNTIME_AUTONOMOUS_SOURCES:
                break
            if item.metadata.get("idleFlush"):
                flushes += 1
        return NOTIFY_IDLE_FLUSH_BUDGET - flushes


__all__ = [
    "EVENT_LEVELS",
    "NOTIFICATION_SOURCE",
    "NOTIFY_AUTONOMOUS_HARD_CAP",
    "NOTIFY_IDLE_FLUSH_BUDGET",
    "NOTIFY_IDLE_FLUSH_COOLDOWN_SECONDS",
    "NotificationLevel",
    "RUNTIME_AUTONOMOUS_SOURCES",
    "RuntimeEventKind",
    "RuntimeNotificationBus",
    "render_resume_digest",
    "render_steer_message",
]
