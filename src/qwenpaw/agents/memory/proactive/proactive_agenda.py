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

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..action_provider import MemoryActionProvider
    from .proactive_delivery import DeliveryLedger

logger = logging.getLogger(__name__)

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

    Reminders are exempt. A reminder's ``topic_id`` derives from a stable
    schedule title, so without the exemption one delivery would silence a
    recurring reminder for the whole window even while it keeps coming due.
    """
    if ledger is None:
        return list(items)
    return [
        item
        for item in items
        if item.is_reminder
        or not ledger.is_delivered(item.topic_id, cooldown_days=cooldown_days)
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
    """
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

    refreshed = await refresh_agenda(memory_manager, date=date)
    if ledger is not None:
        await ledger.record_refresh()
    if not refreshed:
        return AgendaBundle(read=read, items=items)

    read = await fetch_agenda(memory_manager, date=date)
    items = filter_delivered(read.items, ledger, cooldown_days=cooldown_days)
    return AgendaBundle(read=read, items=items, refreshed=True)


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
