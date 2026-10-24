# -*- coding: utf-8 -*-
"""The host-side delivery ledger and the feedback round-trip."""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from qwenpaw.agents.memory.proactive import proactive_delivery as pd
from qwenpaw.agents.memory.proactive.proactive_agenda import AgendaItem

from .conftest import FakeMemoryManager


def _item(topic_id: str) -> AgendaItem:
    return AgendaItem(topic_id=topic_id, title=f"title-{topic_id}")


def _aged(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestLedgerPath:
    def test_relative_metadata_dir_joins_the_workspace(self):
        path = pd.ledger_path("/ws/agent-1", "mem_metadata")

        assert path == Path(
            "/ws/agent-1/mem_metadata/proactive_delivered.json",
        )

    def test_absolute_metadata_dir_is_kept(self):
        path = pd.ledger_path("/ws/agent-1", "/var/lib/reme")

        assert path == Path("/var/lib/reme/proactive_delivered.json")

    def test_cache_returns_one_instance_per_path(self):
        first = pd.get_delivery_ledger("/tmp/a/proactive_delivered.json")
        second = pd.get_delivery_ledger("/tmp/a/proactive_delivered.json")

        assert first is second


class TestLedger:
    async def test_missing_file_starts_empty(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "missing.json")

        await ledger.load()

        assert not ledger.entries
        assert ledger.last_delivered_at() is None
        assert ledger.last_refresh_at() is None

    async def test_record_persists_and_survives_reload(self, tmp_path: Path):
        path = tmp_path / "proactive_delivered.json"
        ledger = pd.DeliveryLedger(path)

        await ledger.record(
            [
                {
                    "topic_id": "t-1",
                    "channel": "inbox",
                    "status": "shown",
                    "external_ref": "event-1",
                },
            ],
        )

        assert path.exists()
        reloaded = pd.DeliveryLedger(path)
        await reloaded.load()
        assert [entry["topic_id"] for entry in reloaded.entries] == ["t-1"]
        assert reloaded.is_delivered("t-1", cooldown_days=3) is True

    async def test_cooldown_window_is_date_based(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")
        await ledger.record(
            [
                {
                    "topic_id": "t-old",
                    "delivered_at": _aged(5),
                    "channel": "inbox",
                },
            ],
        )

        assert ledger.is_delivered("t-old", cooldown_days=3) is False
        assert ledger.is_delivered("t-old", cooldown_days=7) is True
        assert ledger.is_delivered("t-unknown", cooldown_days=90) is False

    async def test_same_day_delivery_is_hidden_with_zero_cooldown(
        self,
        tmp_path: Path,
    ):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")
        await ledger.record([{"topic_id": "t-1", "channel": "inbox"}])

        assert ledger.is_delivered("t-1", cooldown_days=0) is True

    async def test_failed_status_never_blocks(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")
        await ledger.record(
            [{"topic_id": "t-1", "channel": "inbox", "status": "failed"}],
        )

        assert ledger.is_delivered("t-1", cooldown_days=9) is False

    async def test_terminal_status_is_not_downgraded(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")
        await ledger.record(
            [
                {
                    "topic_id": "t-1",
                    "channel": "inbox",
                    "status": "executed",
                    "external_ref": "event-1",
                },
            ],
        )

        await ledger.record(
            [
                {
                    "topic_id": "t-1",
                    "channel": "inbox",
                    "status": "shown",
                    "external_ref": "event-1",
                },
            ],
        )

        assert ledger.entries[0]["status"] == "executed"
        assert len(ledger.entries) == 1

    async def test_retention_drops_aged_entries(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")
        await ledger.record(
            [
                {"topic_id": "t-old", "delivered_at": _aged(120)},
                {"topic_id": "t-new"},
            ],
        )

        reloaded = pd.DeliveryLedger(tmp_path / "l.json")
        await reloaded.load()

        assert [entry["topic_id"] for entry in reloaded.entries] == ["t-new"]

    async def test_entry_cap_keeps_the_newest(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")
        await ledger.record(
            [
                {
                    "topic_id": f"t-{index}",
                    "delivered_at": _aged(index / 100),
                }
                for index in range(pd.MAX_ENTRIES + 40)
            ],
        )

        assert len(ledger.entries) == pd.MAX_ENTRIES
        assert ledger.entries[-1]["topic_id"] == "t-0"

    async def test_last_delivered_at_filters_by_channel(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")
        await ledger.record(
            [
                {
                    "topic_id": "t-chat",
                    "channel": "in_conversation",
                    "delivered_at": _aged(1),
                },
                {
                    "topic_id": "t-inbox",
                    "channel": "inbox",
                    "delivered_at": _aged(0.01),
                },
            ],
        )

        assert ledger.last_delivered_at(channel="inbox") is not None
        assert ledger.last_delivered_at(channel="notification") is None
        assert ledger.last_delivered_at() is not None

    async def test_record_refresh_stamps_the_throttle(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")

        await ledger.record_refresh()

        assert ledger.last_refresh_at() is not None
        reloaded = pd.DeliveryLedger(tmp_path / "l.json")
        await reloaded.load()
        assert reloaded.last_refresh_at() is not None

    async def test_corrupt_file_is_tolerated(self, tmp_path: Path):
        path = tmp_path / "l.json"
        path.write_text("{not json", encoding="utf-8")
        ledger = pd.DeliveryLedger(path)

        await ledger.load()

        assert not ledger.entries

    async def test_empty_record_does_not_create_a_file(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")

        await ledger.record([])

        assert not (tmp_path / "l.json").exists()


class TestMarkDelivered:
    async def test_reports_locally_and_to_reme(self, tmp_path: Path):
        manager = FakeMemoryManager()
        ledger = pd.DeliveryLedger(tmp_path / "l.json")

        await pd.mark_delivered(
            manager,
            ledger,
            items=[_item("t-1"), _item("t-2")],
            channel="inbox",
            external_ref="event-9",
            date="2026-10-11",
        )

        assert manager.actions() == ["proactive_feedback"]
        reported = manager.feedback[0]
        assert [entry["topic_id"] for entry in reported] == ["t-1", "t-2"]
        assert reported[0]["channel"] == "inbox"
        assert reported[0]["status"] == "shown"
        assert reported[0]["consumer"] == "qwenpaw"
        assert reported[0]["external_ref"] == "event-9"
        assert reported[0]["agenda_date"] == "2026-10-11"
        assert ledger.is_delivered("t-1", cooldown_days=3) is True

    async def test_ledger_survives_a_rejected_feedback(self, tmp_path: Path):
        manager = FakeMemoryManager(feedback_success=False)
        ledger = pd.DeliveryLedger(tmp_path / "l.json")

        await pd.mark_delivered(
            manager,
            ledger,
            items=[_item("t-1")],
            channel="in_conversation",
        )

        assert ledger.is_delivered("t-1", cooldown_days=3) is True

    async def test_ledger_survives_a_missing_feedback_job(
        self,
        tmp_path: Path,
    ):
        manager = FakeMemoryManager()

        async def _unknown(action, **kwargs):
            del kwargs
            raise ValueError(f"Unknown or unavailable action: {action}")

        manager.run_action = _unknown
        ledger = pd.DeliveryLedger(tmp_path / "l.json")

        await pd.mark_delivered(
            manager,
            ledger,
            items=[_item("t-1")],
            channel="inbox",
        )

        assert ledger.is_delivered("t-1", cooldown_days=3) is True

    async def test_no_items_is_a_noop(self):
        manager = FakeMemoryManager()

        await pd.mark_delivered(manager, None, items=[], channel="inbox")

        assert not manager.calls

    async def test_works_without_a_memory_manager(self, tmp_path: Path):
        ledger = pd.DeliveryLedger(tmp_path / "l.json")

        await pd.mark_delivered(
            None,
            ledger,
            items=[_item("t-1")],
            channel="inbox",
        )

        assert ledger.is_delivered("t-1", cooldown_days=3) is True

    def test_entries_without_an_id_are_dropped(self):
        entries = pd.build_delivery_entries(
            [_item("t-1"), AgendaItem(topic_id="  ")],
            channel="inbox",
        )

        assert [entry["topic_id"] for entry in entries] == ["t-1"]
