# -*- coding: utf-8 -*-
"""Record which proactive agenda items QwenPaw already surfaced.

ReMe's ``proactive_feedback`` job is the authoritative store, but the
contract is deliberately optional: another agent framework may never
report back.  QwenPaw therefore keeps a small local ledger as well, for
two reasons ReMe cannot cover on its own --

* a ReMe-side failure (older install, job unavailable, unwritable truth
  source) must not make the host repeat the same agenda item;
* ReMe suppresses per ``agenda_date``, so the same topic resurfacing in a
  later ``interests.yaml`` would be proposed again.  Cross-day dedupe has
  to be the host's job.

Both stores use date granularity and the same cooldown window, matching
ReMe's ``is_delivery_suppressed`` semantics.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ....utils.io_utils import read_json_async, write_json_atomic_async

if TYPE_CHECKING:
    from ..action_provider import MemoryActionProvider
    from .proactive_agenda import AgendaItem

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "proactive_delivered.json"
LEDGER_VERSION = 1
MAX_ENTRIES = 500
RETENTION_DAYS = 90
DEFAULT_CONSUMER = "qwenpaw"
_ENTRY_KEYS = (
    "topic_id",
    "agenda_date",
    "delivered_at",
    "channel",
    "consumer",
    "status",
    "outcome",
    "external_ref",
)

_ledgers: dict[str, "DeliveryLedger"] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> datetime | None:
    """Parse an ISO timestamp into an aware UTC datetime, or ``None``."""
    if isinstance(value, datetime):
        parsed: datetime | None = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ledger_path(workspace_dir: str, metadata_dir: str) -> Path:
    """Absolute path of the host-side delivery ledger."""
    base = Path(metadata_dir or "mem_metadata")
    if not base.is_absolute():
        base = Path(workspace_dir) / base
    return base / LEDGER_FILENAME


def get_delivery_ledger(path: Path | str) -> "DeliveryLedger":
    """Return the process-wide ledger instance for ``path``."""
    key = str(path)
    ledger = _ledgers.get(key)
    if ledger is None:
        ledger = DeliveryLedger(key)
        _ledgers[key] = ledger
    return ledger


class DeliveryLedger:
    """Append-only-ish JSON record of proactive deliveries."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._entries: list[dict[str, str]] = []
        self._last_refresh_at: datetime | None = None
        self._loaded = False

    async def load(self, *, force: bool = False) -> None:
        """Read the ledger from disk; a missing file starts empty."""
        if self._loaded and not force:
            return
        self._loaded = True
        self._entries = []
        self._last_refresh_at = None
        if not self.path.exists():
            return
        try:
            payload = await read_json_async(self.path)
        except Exception:  # noqa: BLE001
            logger.warning(
                "unreadable proactive ledger %s; starting empty",
                self.path,
                exc_info=True,
            )
            return
        if not isinstance(payload, dict):
            return
        raw = payload.get("deliveries")
        if isinstance(raw, list):
            self._entries = [
                entry
                for entry in (_coerce_entry(item) for item in raw)
                if entry is not None
            ]
        self._last_refresh_at = _aware(payload.get("last_refresh_at"))

    @property
    def entries(self) -> list[dict[str, str]]:
        return list(self._entries)

    def is_delivered(self, topic_id: str, *, cooldown_days: int) -> bool:
        """Whether ``topic_id`` was surfaced inside the cooldown window."""
        key = str(topic_id or "").strip()
        if not key:
            return False
        today = _utc_now().date()
        window = max(int(cooldown_days), 0)
        for entry in self._entries:
            if entry.get("topic_id") != key:
                continue
            if entry.get("status") == "failed":
                continue
            delivered = _aware(entry.get("delivered_at"))
            if delivered is None:
                continue
            if (today - delivered.date()).days <= window:
                return True
        return False

    def last_delivered_at(self, *, channel: str = "") -> datetime | None:
        """Most recent delivery, optionally restricted to one channel."""
        latest: datetime | None = None
        for entry in self._entries:
            if channel and entry.get("channel") != channel:
                continue
            delivered = _aware(entry.get("delivered_at"))
            if delivered is None:
                continue
            if latest is None or delivered > latest:
                latest = delivered
        return latest

    def last_refresh_at(self) -> datetime | None:
        return self._last_refresh_at

    async def record(self, entries: list[dict[str, Any]]) -> None:
        """Merge delivery reports into the ledger and persist it."""
        if not entries:
            return
        await self.load()
        for raw in entries:
            entry = _coerce_entry(raw)
            if entry is None:
                continue
            self._upsert(entry)
        self._trim()
        await self._save()

    async def record_refresh(self) -> None:
        """Stamp the on-demand refresh throttle."""
        await self.load()
        self._last_refresh_at = _utc_now()
        await self._save()

    def _upsert(self, entry: dict[str, str]) -> None:
        identity = (entry["topic_id"], entry["external_ref"])
        for existing in self._entries:
            if (
                existing["topic_id"],
                existing["external_ref"],
            ) == identity:
                # Statuses only move forward, mirroring ReMe's rule that a
                # terminal record is never downgraded back to ``shown``.
                if existing["status"] in ("executed", "dismissed") and (
                    entry["status"] not in ("executed", "dismissed")
                ):
                    return
                existing.update(entry)
                return
        self._entries.append(entry)

    def _trim(self) -> None:
        cutoff = _utc_now() - timedelta(days=RETENTION_DAYS)
        kept = []
        for entry in self._entries:
            delivered = _aware(entry.get("delivered_at"))
            if delivered is not None and delivered < cutoff:
                continue
            kept.append(entry)
        kept.sort(key=lambda item: item.get("delivered_at") or "")
        self._entries = kept[-MAX_ENTRIES:]

    async def _save(self) -> None:
        payload = {
            "version": LEDGER_VERSION,
            "updated_at": _utc_now().isoformat(),
            "last_refresh_at": (
                self._last_refresh_at.isoformat()
                if self._last_refresh_at
                else ""
            ),
            "deliveries": self._entries,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            await write_json_atomic_async(self.path, payload)
        except Exception:  # noqa: BLE001
            logger.warning(
                "failed to persist the proactive ledger %s",
                self.path,
                exc_info=True,
            )


def _coerce_entry(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    entry = {key: str(raw.get(key) or "").strip() for key in _ENTRY_KEYS}
    if not entry["topic_id"]:
        return None
    entry["delivered_at"] = entry["delivered_at"] or _utc_now().isoformat()
    entry["status"] = entry["status"] or "shown"
    entry["channel"] = entry["channel"] or "other"
    return entry


def build_delivery_entries(
    items: list["AgendaItem"],
    *,
    channel: str,
    status: str = "shown",
    consumer: str = DEFAULT_CONSUMER,
    outcome: str = "",
    external_ref: str = "",
    date: str = "",
) -> list[dict[str, Any]]:
    """Shape agenda items into ``proactive_feedback`` report entries."""
    now = _utc_now().isoformat()
    return [
        {
            "topic_id": item.topic_id.strip(),
            "agenda_date": date,
            "delivered_at": now,
            "channel": channel,
            "consumer": consumer,
            "status": status,
            "outcome": outcome,
            "external_ref": external_ref,
        }
        for item in items
        if str(item.topic_id or "").strip()
    ]


async def mark_delivered(
    memory_manager: "MemoryActionProvider | None",
    ledger: "DeliveryLedger | None",
    *,
    items: list["AgendaItem"],
    channel: str,
    status: str = "shown",
    consumer: str = DEFAULT_CONSUMER,
    outcome: str = "",
    external_ref: str = "",
    date: str = "",
) -> None:
    """Report surfaced agenda items locally first, then to ReMe.

    The local write always runs so dedupe survives a ReMe-side failure;
    the ``proactive_feedback`` call is best-effort because the contract is
    optional and an older ReMe install simply does not have the job.
    """
    if not items:
        return
    entries = build_delivery_entries(
        items,
        channel=channel,
        status=status,
        consumer=consumer,
        outcome=outcome,
        external_ref=external_ref,
        date=date,
    )
    if ledger is not None:
        await ledger.record(entries)
    if memory_manager is None:
        return
    try:
        response = await memory_manager.run_action(
            "proactive_feedback",
            date=date,
            items=entries,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "proactive delivery feedback unavailable; local ledger only",
            exc_info=True,
        )
        return
    if response is None or not getattr(response, "success", False):
        logger.warning(
            "proactive delivery feedback rejected: %s",
            str(getattr(response, "answer", ""))[:200],
        )
        return
    logger.info(
        "proactive delivery feedback recorded: %d item(s) channel=%s",
        len(entries),
        channel,
    )
