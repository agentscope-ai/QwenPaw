# -*- coding: utf-8 -*-
"""Reading, filtering and refreshing ReMe's proactive agenda."""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.agents.memory.proactive import proactive_agenda as pa
from qwenpaw.agents.memory.proactive.proactive_delivery import DeliveryLedger

from .conftest import FakeMemoryManager, agenda_entry


def _ledger(tmp_path: Path) -> DeliveryLedger:
    return DeliveryLedger(tmp_path / "proactive_delivered.json")


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


def test_refresh_allowed_without_ledger_or_window():
    ledger = SimpleNamespace(last_refresh_at=lambda: None)

    assert pa._refresh_allowed(None, 120) is True
    assert pa._refresh_allowed(ledger, 0) is True
    assert pa._refresh_allowed(ledger, 120) is True
