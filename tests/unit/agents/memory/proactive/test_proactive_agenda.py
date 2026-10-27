# -*- coding: utf-8 -*-
"""Reading, filtering and refreshing ReMe's proactive agenda."""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.agents.memory.proactive import proactive_agenda as pa
from qwenpaw.agents.memory.proactive.proactive_delivery import DeliveryLedger

from .conftest import (
    BlockingRefreshManager,
    FakeMemoryManager,
    agenda_entry,
)


def _ledger(tmp_path: Path) -> DeliveryLedger:
    return DeliveryLedger(tmp_path / "proactive_delivered.json")


def _aged(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestParseAgenda:
    def test_reads_metadata_and_keeps_order(self):
        response = SimpleNamespace(
            success=True,
            answer={},
            metadata={
                "date": "2026-10-11",
                "agenda": [
                    agenda_entry("t-reminder", kind="reminder"),
                    agenda_entry("t-follow", kind="follow_up"),
                ],
                "topics": [{"id": "t-follow", "reason": "asked twice"}],
            },
        )

        items = pa.parse_agenda(response)

        assert [item.topic_id for item in items] == [
            "t-reminder",
            "t-follow",
        ]
        assert items[0].is_reminder is True
        assert items[1].reason == "asked twice"
        assert items[1].linked_memory == ("memory/t-follow.md",)

    def test_falls_back_to_answer_payload(self):
        response = SimpleNamespace(
            success=True,
            metadata=None,
            answer={"agenda": [agenda_entry("t-1")], "topics": []},
        )

        assert [item.topic_id for item in pa.parse_agenda(response)] == [
            "t-1",
        ]

    def test_entries_without_topic_id_are_dropped(self):
        response = SimpleNamespace(
            success=True,
            answer={},
            metadata={"agenda": [{"title": "no id"}, agenda_entry("t-1")]},
        )

        assert [item.topic_id for item in pa.parse_agenda(response)] == [
            "t-1",
        ]

    def test_label_prefers_title_then_opener(self):
        assert pa.AgendaItem(title="T", opener="O").label == "T"
        assert pa.AgendaItem(title="", opener="O").label == "O"
        assert pa.AgendaItem(topic_id="id-1").label == "id-1"


class TestFetchAgenda:
    async def test_reads_without_content_and_with_horizon_one(self):
        manager = FakeMemoryManager([agenda_entry("t-1")])

        read = await pa.fetch_agenda(manager)

        assert read.available is True
        assert read.date == "2026-10-11"
        assert [item.topic_id for item in read.items] == ["t-1"]
        assert manager.calls == [
            (
                "proactive",
                {
                    "date": "",
                    "include_content": False,
                    "horizon_days": 1,
                    "include_delivered": False,
                },
            ),
        ]

    async def test_unavailable_when_reme_is_not_started(self):
        manager = FakeMemoryManager()
        manager.read_success = True

        async def _none(action, **kwargs):
            del action, kwargs
            return None

        manager.run_action = _none

        assert (await pa.fetch_agenda(manager)).available is False

    async def test_unavailable_when_the_read_fails(self):
        manager = FakeMemoryManager(read_success=False)

        assert (await pa.fetch_agenda(manager)).available is False

    async def test_unavailable_when_the_read_raises(self):
        manager = FakeMemoryManager()

        async def _boom(action, **kwargs):
            del action, kwargs
            raise RuntimeError("nope")

        manager.run_action = _boom

        assert (await pa.fetch_agenda(manager)).available is False

    def test_withheld_count_comes_from_delivered_ids(self):
        response = SimpleNamespace(
            success=True,
            answer={},
            metadata={"delivered_ids": ["a", "b"]},
        )

        assert pa._withheld_count(response) == 2


class TestFilterAndSelect:
    async def test_filter_delivered_uses_the_ledger(self, tmp_path: Path):
        ledger = _ledger(tmp_path)
        await ledger.record(
            [{"topic_id": "t-1", "channel": "inbox", "status": "shown"}],
        )
        items = [
            pa.AgendaItem(topic_id="t-1"),
            pa.AgendaItem(topic_id="t-2"),
        ]

        kept = pa.filter_delivered(items, ledger, cooldown_days=3)

        assert [item.topic_id for item in kept] == ["t-2"]

    async def test_filter_delivered_reannounces_a_reminder_next_day(
        self,
        tmp_path: Path,
    ):
        """A still-due reminder is announced again on a later day.

        Reminder ids derive from a stable schedule title, so treating them
        like discovery items would silence a recurring reminder for the whole
        window after one delivery.
        """
        ledger = _ledger(tmp_path)
        await ledger.record(
            [
                {
                    "topic_id": "r-1",
                    "channel": "inbox",
                    "status": "shown",
                    "delivered_at": _aged(1),
                },
                {"topic_id": "t-1", "channel": "inbox", "status": "shown"},
            ],
        )
        items = [
            pa.AgendaItem(topic_id="r-1", kind="reminder"),
            pa.AgendaItem(topic_id="t-1", kind="follow_up"),
        ]

        kept = pa.filter_delivered(items, ledger, cooldown_days=3)

        assert [item.topic_id for item in kept] == ["r-1"]

    async def test_filter_delivered_hides_a_reminder_shown_today(
        self,
        tmp_path: Path,
    ):
        """One alert per day: later rounds leave room for discovery items."""
        ledger = _ledger(tmp_path)
        await ledger.record(
            [
                {"topic_id": "r-1", "channel": "inbox", "status": "shown"},
                {"topic_id": "t-1", "channel": "inbox", "status": "shown"},
            ],
        )
        items = [
            pa.AgendaItem(topic_id="r-1", kind="reminder"),
            pa.AgendaItem(topic_id="t-2", kind="follow_up"),
        ]

        kept = pa.filter_delivered(items, ledger, cooldown_days=3)

        assert [item.topic_id for item in kept] == ["t-2"]

    def test_filter_without_ledger_keeps_everything(self):
        items = [pa.AgendaItem(topic_id="t-1")]

        assert pa.filter_delivered(items, None, cooldown_days=3) == items

    def test_select_respects_limit_and_zero_means_all(self):
        items = [pa.AgendaItem(topic_id=f"t-{i}") for i in range(4)]

        assert len(pa.select_presentation_items(items, limit=2)) == 2
        assert len(pa.select_presentation_items(items, limit=0)) == 4
        assert pa.select_presentation_items(items, limit=2)[0].topic_id == (
            "t-0"
        )


class TestEnsureAgenda:
    async def test_non_empty_agenda_never_refreshes(self):
        manager = FakeMemoryManager([agenda_entry("t-1")])

        bundle = await pa.ensure_agenda(
            manager,
            None,
            cooldown_days=3,
            min_interval_minutes=0,
        )

        assert manager.actions() == ["proactive"]
        assert bundle.refreshed is False
        assert bundle.throttled is False
        assert [item.topic_id for item in bundle.items] == ["t-1"]

    async def test_empty_agenda_triggers_one_refresh(self):
        manager = FakeMemoryManager(
            [],
            refresh_swaps_agenda=[agenda_entry("t-new")],
        )

        bundle = await pa.ensure_agenda(
            manager,
            None,
            cooldown_days=3,
            min_interval_minutes=0,
        )

        assert manager.actions() == [
            "proactive",
            "proactive_refresh",
            "proactive",
        ]
        assert bundle.refreshed is True
        assert [item.topic_id for item in bundle.items] == ["t-new"]

    async def test_throttle_skips_the_refresh(self, tmp_path: Path):
        manager = FakeMemoryManager([])
        ledger = _ledger(tmp_path)
        await ledger.record_refresh()

        bundle = await pa.ensure_agenda(
            manager,
            ledger,
            cooldown_days=3,
            min_interval_minutes=120,
        )

        assert manager.actions() == ["proactive"]
        assert bundle.throttled is True
        assert bundle.refreshed is False

    async def test_throttle_window_expires(self, tmp_path: Path):
        manager = FakeMemoryManager([])
        ledger = _ledger(tmp_path)
        await ledger.record_refresh()
        stale = datetime.now(timezone.utc) - timedelta(minutes=200)
        ledger._last_refresh_at = stale

        bundle = await pa.ensure_agenda(
            manager,
            ledger,
            cooldown_days=3,
            min_interval_minutes=120,
        )

        assert bundle.throttled is False
        assert "proactive_refresh" in manager.actions()

    async def test_force_refresh_runs_even_with_items(self):
        manager = FakeMemoryManager([agenda_entry("t-1")])

        bundle = await pa.ensure_agenda(
            manager,
            None,
            cooldown_days=3,
            min_interval_minutes=120,
            force_refresh=True,
        )

        assert manager.actions() == [
            "proactive",
            "proactive_refresh",
            "proactive",
        ]
        assert bundle.refreshed is True

    async def test_force_refresh_ignores_the_throttle(self, tmp_path: Path):
        manager = FakeMemoryManager([agenda_entry("t-1")])
        ledger = _ledger(tmp_path)
        await ledger.record_refresh()

        bundle = await pa.ensure_agenda(
            manager,
            ledger,
            cooldown_days=3,
            min_interval_minutes=120,
            force_refresh=True,
        )

        assert bundle.refreshed is True
        assert bundle.throttled is False

    async def test_failed_refresh_keeps_the_stale_read(self):
        manager = FakeMemoryManager(
            [],
            refresh_success=False,
        )

        bundle = await pa.ensure_agenda(
            manager,
            None,
            cooldown_days=3,
            min_interval_minutes=0,
        )

        assert manager.actions() == ["proactive", "proactive_refresh"]
        assert bundle.refreshed is False
        assert bundle.items == []

    async def test_delivered_items_count_as_hidden(self, tmp_path: Path):
        manager = FakeMemoryManager(
            [agenda_entry("t-1"), agenda_entry("t-2")],
            delivered_ids=["t-3"],
        )
        ledger = _ledger(tmp_path)
        await ledger.record(
            [{"topic_id": "t-1", "channel": "inbox", "status": "shown"}],
        )

        bundle = await pa.ensure_agenda(
            manager,
            ledger,
            cooldown_days=3,
            min_interval_minutes=120,
        )

        # t-3 was withheld by ReMe, t-1 by the host ledger.
        assert bundle.hidden_total == 2
        assert [item.topic_id for item in bundle.items] == ["t-2"]

    async def test_fresh_process_hydrates_the_ledger(self, tmp_path: Path):
        """An unloaded ledger written by a prior process still dedupes.

        ``is_delivered`` reads the in-memory copy, so ``ensure_agenda`` has to
        hydrate it or the first round after a restart re-shows everything and
        ignores the refresh throttle.
        """
        writer = _ledger(tmp_path)
        await writer.record(
            [{"topic_id": "t-1", "channel": "inbox", "status": "shown"}],
        )
        manager = FakeMemoryManager(
            [agenda_entry("t-1"), agenda_entry("t-2")],
        )
        fresh = DeliveryLedger(writer.path)
        assert not fresh.entries  # nothing hydrated yet

        bundle = await pa.ensure_agenda(
            manager,
            fresh,
            cooldown_days=3,
            min_interval_minutes=120,
        )

        assert [item.topic_id for item in bundle.items] == ["t-2"]

    async def test_reminder_survives_the_hydrated_ledger(self, tmp_path: Path):
        """A reminder from an earlier day stays; the discovery item goes."""
        writer = _ledger(tmp_path)
        await writer.record(
            [
                {
                    "topic_id": "r-1",
                    "channel": "inbox",
                    "status": "shown",
                    "delivered_at": _aged(1),
                },
                {"topic_id": "t-1", "channel": "inbox", "status": "shown"},
            ],
        )
        manager = FakeMemoryManager(
            [agenda_entry("r-1", kind="reminder"), agenda_entry("t-1")],
        )

        bundle = await pa.ensure_agenda(
            manager,
            DeliveryLedger(writer.path),
            cooldown_days=3,
            min_interval_minutes=120,
        )

        assert [item.topic_id for item in bundle.items] == ["r-1"]
        assert bundle.hidden_total == 1


def test_refresh_allowed_without_ledger_or_window():
    ledger = SimpleNamespace(last_refresh_at=lambda: None)

    assert pa._refresh_allowed(None, 120) is True
    assert pa._refresh_allowed(ledger, 0) is True
    assert pa._refresh_allowed(ledger, 120) is True


class TestRefreshSerialization:
    """One rebuild per workspace, and never on a read-only round."""

    async def test_read_only_round_never_refreshes(self):
        manager = FakeMemoryManager([])

        bundle = await pa.ensure_agenda(
            manager,
            None,
            cooldown_days=3,
            refresh=False,
        )

        # ``/proactive`` answers from this read alone and queues the rebuild
        # itself, so the minutes-long chain must not run inline.
        assert manager.actions() == ["proactive"]
        assert bundle.items == []
        assert bundle.refreshed is False
        assert bundle.throttled is False

    async def test_read_only_round_still_reports_the_throttle(
        self,
        tmp_path: Path,
    ):
        manager = FakeMemoryManager([])
        ledger = _ledger(tmp_path)
        await ledger.record_refresh()

        bundle = await pa.ensure_agenda(
            manager,
            ledger,
            cooldown_days=3,
            min_interval_minutes=120,
            refresh=False,
        )

        assert manager.actions() == ["proactive"]
        assert bundle.throttled is True

    async def test_parallel_rounds_share_one_refresh(self):
        manager = BlockingRefreshManager(
            [],
            refresh_swaps_agenda=[agenda_entry("t-new")],
        )

        first = asyncio.create_task(
            pa.ensure_agenda(manager, None, cooldown_days=3, scope="/ws/a"),
        )
        await manager.refresh_started.wait()
        assert pa.refresh_in_progress("/ws/a") is True

        second = asyncio.create_task(
            pa.ensure_agenda(manager, None, cooldown_days=3, scope="/ws/a"),
        )
        # Let the second round reach the lock the first one is holding.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        manager.release.set()

        first_bundle, second_bundle = await asyncio.gather(first, second)

        assert manager.actions().count("proactive_refresh") == 1
        assert [item.topic_id for item in first_bundle.items] == ["t-new"]
        # The waiter re-reads instead of rebuilding a second time.
        assert [item.topic_id for item in second_bundle.items] == ["t-new"]
        assert second_bundle.refreshed is False
        assert pa.refresh_in_progress("/ws/a") is False

    async def test_locks_and_progress_are_keyed_by_scope(self):
        assert pa._lock_for("/ws/a") is pa._lock_for("/ws/a")
        assert pa._lock_for("/ws/a") is not pa._lock_for("/ws/b")
        # An unknown workspace still shares one registry entry.
        assert pa._lock_for("") is pa._lock_for("   ")
        assert pa.refresh_in_progress("") is False
