# -*- coding: utf-8 -*-
"""Read ReMe's proactive agenda for QwenPaw's delivery paths.

Three entry points share one read path: the ``/proactive`` command
receipt, the idle trigger and the daily cron job.  All of them read the
agenda ReMe already ranked (due reminders pinned first), drop the items
the host delivered inside the cooldown window, and only fall back to a
full ``proactive_refresh`` when nothing is left to show.

Nothing here runs an LLM by itself; the only model work happens inside
ReMe's ``proactive_refresh`` job, and ReMe early-exits it without a call
when there is no new material to read.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..action_provider import MemoryActionProvider
    from .proactive_delivery import DeliveryLedger

logger = logging.getLogger(__name__)

# One rebuild at a time per workspace.  ReMe's chain (extract -> topics ->
# plan -> agenda) costs minutes of model work and rewrites the day's
# ``interests.yaml``, so letting ``/proactive``, the idle trigger and the
# daily cron start it in parallel would duplicate the work and race on the
# same files.
_DEFAULT_SCOPE = "default"
_refresh_locks: dict[str, asyncio.Lock] = {}
_refresh_running: set[str] = set()


def _scope_key(scope: str) -> str:
    return scope.strip() or _DEFAULT_SCOPE


def _lock_for(scope: str) -> asyncio.Lock:
    key = _scope_key(scope)
    lock = _refresh_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[key] = lock
    return lock


def refresh_in_progress(scope: str = "") -> bool:
    """Whether one rebuild is already running for this workspace."""
    return _scope_key(scope) in _refresh_running


_TEXT_FIELDS = (
    "topic_id",
    "title",
    "kind",
    "scenario_type",
    "opener",
    "next_action",
    "delivery",
    "due_at",
    "schedule_id",
    "order_reason",
)
_LIST_FIELDS = ("preconditions", "linked_memory")


@dataclass(frozen=True)
class AgendaItem:
    """One ranked agenda entry exactly as ReMe wrote it."""

    topic_id: str = ""
    title: str = ""
    kind: str = ""
    scenario_type: str = ""
    opener: str = ""
    next_action: str = ""
    delivery: str = ""
    preconditions: tuple[str, ...] = ()
    linked_memory: tuple[str, ...] = ()
    due_at: str = ""
    schedule_id: str = ""
    order_reason: str = ""
    reason: str = ""

    @property
    def label(self) -> str:
        """Best available one-line heading for rendering."""
        for value in (self.title, self.opener, self.topic_id):
            if value.strip():
                return value.strip()
        return "untitled agenda item"

    @property
    def is_reminder(self) -> bool:
        return self.kind == "reminder"


@dataclass
class AgendaRead:
    """One ``proactive`` read: ranked items plus ReMe's agenda date."""

    items: list[AgendaItem] = field(default_factory=list)
    date: str = ""
    available: bool = True
    # ReMe's own report of agenda entries it withheld because the host
    # already surfaced them (``ProactiveResult.delivered_ids``).
    withheld: int = 0


@dataclass
class AgendaBundle:
    """Outcome of :func:`ensure_agenda` for the three delivery paths."""

    read: AgendaRead = field(default_factory=AgendaRead)
    items: list[AgendaItem] = field(default_factory=list)
    refreshed: bool = False
    throttled: bool = False

    @property
    def date(self) -> str:
        return self.read.date

    @property
    def available(self) -> bool:
        return self.read.available

    @property
    def hidden_total(self) -> int:
        """Agenda items withheld by either dedupe layer.

        ReMe withholds inside ``delivery_cooldown_days``; the host ledger
        additionally covers cross-day repeats ReMe cannot see.
        """
        local = max(len(self.read.items) - len(self.items), 0)
        return self.read.withheld + local


def _clean_str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _item_from_dict(raw: Any, reasons: dict[str, str]) -> AgendaItem | None:
    """Coerce one agenda entry; ``None`` when it has no usable identity."""
    if not isinstance(raw, dict):
        return None
    text = {name: str(raw.get(name) or "").strip() for name in _TEXT_FIELDS}
    if not text["topic_id"]:
        return None
    return AgendaItem(
        topic_id=text["topic_id"],
        title=text["title"],
        kind=text["kind"],
        scenario_type=text["scenario_type"],
        opener=text["opener"],
        next_action=text["next_action"],
        delivery=text["delivery"],
        preconditions=_clean_str_list(raw.get("preconditions")),
        linked_memory=_clean_str_list(raw.get("linked_memory")),
        due_at=text["due_at"],
        schedule_id=text["schedule_id"],
        order_reason=text["order_reason"],
        # The agenda entry carries no ``reason``; the topic with the same id
        # does, and that is what explains why the item exists at all.
        reason=reasons.get(text["topic_id"], ""),
    )


def _reasons_by_id(topics: Any) -> dict[str, str]:
    reasons: dict[str, str] = {}
    if not isinstance(topics, (list, tuple)):
        return reasons
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        key = str(topic.get("id") or topic.get("topic_id") or "").strip()
        if key:
            reasons[key] = str(topic.get("reason") or "").strip()
    return reasons


def parse_agenda(response: Any) -> list[AgendaItem]:
    """Extract ranked agenda items from a ``proactive`` action response.

    ``proactive_step`` mirrors the whole ``ProactiveResult`` into
    ``response.metadata`` and keeps a trimmed dict in ``response.answer``,
    so metadata is the primary source and answer the fallback.
    """
    payloads: list[Any] = []
    metadata = getattr(response, "metadata", None)
    if isinstance(metadata, dict):
        payloads.append(metadata)
    answer = getattr(response, "answer", None)
    if isinstance(answer, dict):
        payloads.append(answer)

    for payload in payloads:
        raw_agenda = payload.get("agenda")
        if not isinstance(raw_agenda, (list, tuple)):
            continue
        reasons = _reasons_by_id(payload.get("topics"))
        items = [
            item
            for item in (
                _item_from_dict(entry, reasons) for entry in raw_agenda
            )
            if item is not None
        ]
        if items:
            return items
    return []


async def fetch_agenda(
    memory_manager: "MemoryActionProvider",
    *,
    date: str = "",
    include_delivered: bool = False,
) -> AgendaRead:
    """Read today's agenda from ReMe without triggering any generation."""
    try:
        response = await memory_manager.run_action(
            "proactive",
            date=date,
            include_content=False,
            horizon_days=1,
            include_delivered=include_delivered,
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to read the proactive agenda", exc_info=True)
        return AgendaRead(available=False)
    if response is None:
        logger.info("proactive agenda read skipped; ReMe is not started")
        return AgendaRead(available=False)
    if not getattr(response, "success", False):
        logger.warning(
            "proactive agenda read failed: %s",
            str(getattr(response, "answer", ""))[:200],
        )
        return AgendaRead(available=False)
    read = AgendaRead(
        items=parse_agenda(response),
        date=_read_date(response),
        withheld=_withheld_count(response),
    )
    logger.info(
        "proactive agenda read: %d item(s) date=%s",
        len(read.items),
        read.date or "-",
    )
    return read


def _withheld_count(response: Any) -> int:
    """How many agenda items ReMe itself withheld as already delivered."""
    metadata = getattr(response, "metadata", None)
    if not isinstance(metadata, dict):
        return 0
    delivered = metadata.get("delivered_ids")
    if isinstance(delivered, (list, tuple)):
        return len(delivered)
    return 0


def _read_date(response: Any) -> str:
    """ReMe's own agenda date, so dedupe and headers agree with the file."""
    for payload in (
        getattr(response, "metadata", None),
        getattr(response, "answer", None),
    ):
        if isinstance(payload, dict) and payload.get("date"):
            return str(payload["date"])
    return ""


async def refresh_agenda(
    memory_manager: "MemoryActionProvider",
    *,
    date: str = "",
) -> bool:
    """Rebuild the agenda from topic extraction; ``True`` on success."""
    try:
        response = await memory_manager.run_action(
            "proactive_refresh",
            date=date,
        )
    except Exception:  # noqa: BLE001
        logger.warning("proactive agenda refresh raised", exc_info=True)
        return False
    if response is None:
        logger.info("proactive agenda refresh skipped; ReMe not started")
        return False
    success = bool(getattr(response, "success", False))
    if not success:
        logger.warning(
            "proactive agenda refresh failed: %s",
            str(getattr(response, "answer", ""))[:200],
        )
    return success


def filter_delivered(
    items: list[AgendaItem],
    ledger: "DeliveryLedger | None",
    *,
    cooldown_days: int,
) -> list[AgendaItem]:
    """Drop items the host already surfaced inside the cooldown window.

    A reminder skips the multi-day window but not the day it was already
    announced on.  Its ``topic_id`` derives from a stable schedule title,
    so treating it like a discovery item would silence a still-due schedule
    for the whole window, while re-announcing it on every round of the same
    day is only noise.
    """
    if ledger is None:
        return list(items)
    return [
        item
        for item in items
        if not ledger.is_delivered(
            item.topic_id,
            cooldown_days=0 if item.is_reminder else cooldown_days,
        )
    ]


def select_presentation_items(
    items: list[AgendaItem],
    *,
    limit: int,
) -> list[AgendaItem]:
    """Keep ReMe's order and cut to ``limit``; ``limit <= 0`` means all."""
    if limit <= 0:
        return list(items)
    return list(items[:limit])


async def ensure_agenda(
    memory_manager: "MemoryActionProvider",
    ledger: "DeliveryLedger | None",
    *,
    cooldown_days: int,
    min_interval_minutes: int = 0,
    force_refresh: bool = False,
    date: str = "",
    scope: str = "",
    refresh: bool = True,
) -> AgendaBundle:
    """Return undelivered agenda items, refreshing only when empty.

    Args:
        memory_manager: Backend exposing ReMe's memory actions.
        ledger: Host-side delivery record; ``None`` disables local dedupe.
        cooldown_days: Window during which a delivered item stays hidden.
        min_interval_minutes: On-demand refresh throttle; ``0`` lifts it.
        force_refresh: Refresh first regardless of the current agenda. The
            daily cron uses this so every push reflects fresh extraction.
        date: Agenda date override, empty means ReMe's today.
        scope: Workspace the rebuild belongs to; refreshes for one scope are
            serialized so parallel callers cannot stack duplicate chains.
        refresh: Set ``False`` for a read-only round. The bundle then only
            reports whether a rebuild is due (``throttled`` says it is not),
            which is what lets ``/proactive`` answer immediately and hand the
            rebuild to a background task.
    """
    if ledger is not None:
        # ``is_delivered`` and ``last_refresh_at`` read the in-memory copy,
        # which only ``record``/``record_refresh`` used to hydrate. Without
        # this the first round in a fresh process would skip host-side dedupe
        # and the refresh throttle entirely.
        await ledger.load()
    read = await fetch_agenda(memory_manager, date=date)
    items = filter_delivered(read.items, ledger, cooldown_days=cooldown_days)
    if items and not force_refresh:
        return AgendaBundle(read=read, items=items)

    if not force_refresh and not _refresh_allowed(
        ledger,
        min_interval_minutes,
    ):
        logger.info(
            "proactive agenda refresh throttled (%d min window)",
            min_interval_minutes,
        )
        return AgendaBundle(read=read, items=items, throttled=True)

    if not refresh:
        return AgendaBundle(read=read, items=items)

    key = _scope_key(scope)
    lock = _lock_for(key)
    # ``Lock.acquire`` has a no-yield fast path, so reading ``locked()``
    # here is atomic with respect to other tasks: it tells us whether the
    # rebuild below is a second one for the same empty agenda.
    waited = lock.locked()
    async with lock:
        if waited and not force_refresh:
            settled = await _reread_after_wait(
                memory_manager,
                ledger,
                cooldown_days=cooldown_days,
                min_interval_minutes=min_interval_minutes,
                date=date,
            )
            if settled is not None:
                return settled
        _refresh_running.add(key)
        try:
            logger.info("proactive agenda refresh started (scope=%s)", key)
            refreshed = await refresh_agenda(memory_manager, date=date)
            if ledger is not None:
                await ledger.record_refresh()
        finally:
            _refresh_running.discard(key)
    if not refreshed:
        return AgendaBundle(read=read, items=items)

    read = await fetch_agenda(memory_manager, date=date)
    items = filter_delivered(read.items, ledger, cooldown_days=cooldown_days)
    return AgendaBundle(read=read, items=items, refreshed=True)


async def _reread_after_wait(
    memory_manager: "MemoryActionProvider",
    ledger: "DeliveryLedger | None",
    *,
    cooldown_days: int,
    min_interval_minutes: int,
    date: str,
) -> AgendaBundle | None:
    """Re-read once a concurrent rebuild finished.

    ``None`` means the wait bought nothing -- the agenda is still empty and
    the throttle still allows it -- so the caller owes its own rebuild.
    """
    read = await fetch_agenda(memory_manager, date=date)
    items = filter_delivered(read.items, ledger, cooldown_days=cooldown_days)
    if items:
        return AgendaBundle(read=read, items=items)
    if not _refresh_allowed(ledger, min_interval_minutes):
        logger.info(
            "proactive agenda refresh throttled (%d min window)",
            min_interval_minutes,
        )
        return AgendaBundle(read=read, items=items, throttled=True)
    return None


def _refresh_allowed(
    ledger: "DeliveryLedger | None",
    min_interval_minutes: int,
) -> bool:
    if ledger is None or min_interval_minutes <= 0:
        return True
    last = ledger.last_refresh_at()
    if last is None:
        return True
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= min_interval_minutes * 60
