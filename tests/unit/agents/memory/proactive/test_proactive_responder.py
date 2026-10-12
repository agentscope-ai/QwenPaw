# -*- coding: utf-8 -*-
"""The two delivery surfaces: the /proactive receipt and the inbox round."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.agents.memory.proactive import proactive_responder as pr

from .conftest import FakeMemoryManager, agenda_entry


def _settings(**overrides) -> pr.ProactiveSettings:
    base = {
        "language": "en",
        "enabled": True,
        "inbox_enabled": True,
        "max_items": 2,
        "cron_max_items": 0,
        "cooldown_days": 3,
        "refresh_min_interval_minutes": 0,
        "metadata_dir": "mem_metadata",
    }
    base.update(overrides)
    return pr.ProactiveSettings(**base)


@pytest.fixture
def append_event(monkeypatch):
    """Capture inbox appends instead of touching the real store."""
    events: list[dict] = []

    async def _append(**kwargs):
        events.append(kwargs)
        return {"id": f"event-{len(events)}", "status": "success"}

    monkeypatch.setattr(
        "qwenpaw.app.inbox_store.append_event",
        _append,
    )
    return events


@pytest.fixture
def memory_config(monkeypatch):
    monkeypatch.setattr(
        pr,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            language="en",
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    proactive_inbox_push_enabled=True,
                ),
            ),
        ),
    )


class TestLoadSettings:
    async def test_missing_memory_config_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            pr,
            "load_agent_config",
            lambda _agent_id: SimpleNamespace(
                language="zh",
                running=SimpleNamespace(),
            ),
        )

        settings = await pr.load_proactive_settings("agent-1")

        assert settings.language == "zh"
        assert settings.enabled is False

    async def test_all_switches_are_mapped(self, monkeypatch):
        monkeypatch.setattr(
            pr,
            "load_agent_config",
            lambda _agent_id: SimpleNamespace(
                language="en",
                running=SimpleNamespace(
                    reme_light_memory_config=SimpleNamespace(
                        proactive_enabled=True,
                        proactive_inbox_push_enabled=False,
                        proactive_max_items=4,
                        proactive_cron_max_items=6,
                        proactive_delivery_cooldown_days=7,
                        proactive_refresh_min_interval_minutes=15,
                        metadata_dir="custom_meta",
                    ),
                ),
            ),
        )

        settings = await pr.load_proactive_settings("agent-1")

        assert settings == pr.ProactiveSettings(
            language="en",
            enabled=True,
            inbox_enabled=False,
            max_items=4,
            cron_max_items=6,
            cooldown_days=7,
            refresh_min_interval_minutes=15,
            metadata_dir="custom_meta",
        )


class TestProviderResolution:
    def test_non_provider_is_rejected(self):
        assert pr.resolve_memory_provider(object()) is None
        assert pr.resolve_memory_provider(None) is None

    def test_provider_is_accepted(self):
        manager = FakeMemoryManager()

        assert pr.resolve_memory_provider(manager) is manager


class TestBuildAgendaReceipt:
    async def test_disabled_switch_explains_how_to_enable(
        self,
        tmp_path: Path,
    ):
        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=FakeMemoryManager(),
            settings=_settings(enabled=False, language="zh"),
        )

        assert "运行配置" in receipt
        assert "/proactive" in receipt

    async def test_presents_ranked_openers_and_reports_back(
        self,
        tmp_path: Path,
    ):
        manager = FakeMemoryManager(
            [
                agenda_entry("t-1", kind="reminder", due_at="2026-10-12"),
                agenda_entry("t-2", opener="Want me to draft the summary?"),
                agenda_entry("t-3"),
            ],
        )

        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            external_ref="chat-7",
            settings=_settings(),
        )

        # max_items=2 keeps ReMe's order: the reminder is pinned first.
        assert "1. title-t-1" in receipt
        assert "**2. title-t-2**" in receipt
        assert "Want me to draft the summary?" in receipt
        assert "title-t-3" not in receipt
        assert "`reminder`" in receipt
        assert "2026-10-12" in receipt
        assert "next-t-2" in receipt
        assert manager.actions() == ["proactive", "proactive_feedback"]
        assert manager.feedback[0][0]["channel"] == "in_conversation"
        assert manager.feedback[0][0]["external_ref"] == "chat-7"
        assert manager.feedback[0][0]["agenda_date"] == "2026-10-11"

    async def test_empty_agenda_refreshes_then_explains(self, tmp_path: Path):
        manager = FakeMemoryManager([])

        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=_settings(),
        )

        assert "proactive_refresh" in manager.actions()
        assert "Nothing worth raising today" in receipt
        assert not manager.feedback

    async def test_forced_refresh_empty_state_says_so(self, tmp_path: Path):
        manager = FakeMemoryManager([])

        outcome = await pr.collect_agenda(
            manager,
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            force_refresh=True,
            settings=_settings(),
        )

        assert outcome.forced_refresh is True
        assert "rebuilt the agenda from topic extraction" in (
            outcome.empty_state()
        )

    async def test_throttled_empty_state_names_the_window(
        self,
        tmp_path: Path,
    ):
        manager = FakeMemoryManager([])
        settings = _settings(refresh_min_interval_minutes=120)
        ledger = pr._ledger_for(str(tmp_path), settings)
        await ledger.record_refresh()

        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=settings,
        )

        assert manager.actions() == ["proactive"]
        assert "120 minutes ago" in receipt

    async def test_withheld_items_outrank_the_throttle(
        self,
        tmp_path: Path,
    ):
        """A throttled round still reports what it withheld.

        Both facts can hold at once: an earlier round delivered the whole
        agenda, so the next read is throttled *and* every item is inside
        the cooldown window.  Naming the cooldown is the actionable
        answer; naming the throttle would hide why nothing is shown.
        """
        manager = FakeMemoryManager([], delivered_ids=["t-1", "t-2"])
        settings = _settings(
            cooldown_days=5,
            refresh_min_interval_minutes=120,
        )
        ledger = pr._ledger_for(str(tmp_path), settings)
        await ledger.record_refresh()

        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=settings,
        )

        assert manager.actions() == ["proactive"]
        assert "already delivered" in receipt
        assert "5 day(s)" in receipt
        assert "120 minutes ago" not in receipt

    async def test_delivered_items_empty_state_names_the_cooldown(
        self,
        tmp_path: Path,
    ):
        manager = FakeMemoryManager(
            [agenda_entry("t-1")],
            delivered_ids=["t-2", "t-3"],
        )
        settings = _settings(cooldown_days=5)
        ledger = pr._ledger_for(str(tmp_path), settings)
        await ledger.record([{"topic_id": "t-1", "channel": "inbox"}])

        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=settings,
        )

        assert "already delivered" in receipt
        assert "5 day(s)" in receipt
        # Everything was withheld, so the round still tried one refresh.
        assert "proactive_refresh" in manager.actions()

    async def test_unavailable_backend_explains(self, tmp_path: Path):
        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=object(),
            settings=_settings(),
        )

        assert "unavailable" in receipt

    async def test_localized_receipt_follows_the_agent_language(
        self,
        tmp_path: Path,
    ):
        manager = FakeMemoryManager([agenda_entry("t-1")])

        receipt = await pr.build_agenda_receipt(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=_settings(language="zh"),
        )

        assert "主动议程建议" in receipt
        assert "可以让我" in receipt


class TestDeliverProactiveRound:
    async def test_disabled_feature_is_skipped(self, tmp_path: Path):
        manager = FakeMemoryManager([agenda_entry("t-1")])

        outcome = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=_settings(enabled=False),
        )

        assert outcome.skip_reason == "disabled"
        assert not manager.calls

    async def test_inbox_switch_off_is_skipped(self, tmp_path: Path):
        manager = FakeMemoryManager([agenda_entry("t-1")])

        outcome = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=_settings(inbox_enabled=False),
        )

        assert outcome.skip_reason == "inbox_disabled"
        assert not manager.calls

    async def test_idle_round_pushes_and_reports(
        self,
        tmp_path: Path,
        append_event,
        memory_config,
    ):
        manager = FakeMemoryManager(
            [agenda_entry("t-1"), agenda_entry("t-2"), agenda_entry("t-3")],
        )

        outcome = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            channel="idle",
            settings=_settings(),
        )

        assert outcome.pushed is True
        assert outcome.event_id == "event-1"
        assert len(outcome.shown) == 2  # max_items
        assert append_event[0]["source_type"] == "memory"
        assert append_event[0]["source_id"] == "proactive"
        assert append_event[0]["event_type"] == "proactive_agenda_result"
        assert append_event[0]["title"] == "Proactive agenda suggestions (2)"
        assert "title-t-1" in append_event[0]["body"]
        assert append_event[0]["payload"]["channel"] == "idle"
        assert manager.feedback[0][0]["channel"] == "inbox"
        assert manager.feedback[0][0]["external_ref"] == "event-1"

    async def test_cron_round_sends_the_whole_agenda(
        self,
        tmp_path: Path,
        append_event,
        memory_config,
    ):
        manager = FakeMemoryManager(
            [agenda_entry(f"t-{i}") for i in range(6)],
        )

        outcome = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            channel="cron",
            force_refresh=True,
            settings=_settings(max_items=2, cron_max_items=0),
        )

        assert "proactive_refresh" in manager.actions()
        assert len(outcome.shown) == 6
        assert append_event[0]["title"] == "Today's proactive agenda (6)"
        assert append_event[0]["payload"]["channel"] == "cron"

    async def test_cron_item_cap_is_honoured(
        self,
        tmp_path: Path,
        append_event,
        memory_config,
    ):
        manager = FakeMemoryManager(
            [agenda_entry(f"t-{i}") for i in range(6)],
        )

        outcome = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            channel="cron",
            settings=_settings(cron_max_items=3),
        )

        assert len(outcome.shown) == 3
        assert append_event[0]["payload"]["count"] == 3

    async def test_empty_round_stays_silent(
        self,
        tmp_path: Path,
        append_event,
        memory_config,
    ):
        manager = FakeMemoryManager([])

        outcome = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            channel="cron",
            force_refresh=True,
            settings=_settings(),
        )

        assert outcome.pushed is False
        assert outcome.skip_reason == "empty"
        assert append_event == []
        assert not manager.feedback

    async def test_rejected_inbox_event_is_not_reported(
        self,
        tmp_path: Path,
        monkeypatch,
        memory_config,
    ):
        manager = FakeMemoryManager([agenda_entry("t-1")])

        async def _boom(**_kwargs):
            raise RuntimeError("inbox down")

        monkeypatch.setattr("qwenpaw.app.inbox_store.append_event", _boom)

        outcome = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=_settings(),
        )

        assert outcome.pushed is False
        assert outcome.skip_reason == "inbox_rejected"
        assert not manager.feedback

    async def test_delivered_items_are_not_pushed_again(
        self,
        tmp_path: Path,
        append_event,
        memory_config,
    ):
        manager = FakeMemoryManager(
            [agenda_entry("t-1"), agenda_entry("t-2")],
        )
        settings = _settings(refresh_min_interval_minutes=0)

        first = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=settings,
        )
        second = await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=settings,
        )

        assert first.pushed is True
        assert second.pushed is False
        assert second.hidden_total == 2
        assert len(append_event) == 1

    async def test_last_inbox_push_at_reads_the_ledger(
        self,
        tmp_path: Path,
        append_event,
        memory_config,
    ):
        del append_event
        settings = _settings()
        manager = FakeMemoryManager([agenda_entry("t-1")])
        assert (
            await pr.last_inbox_push_at(str(tmp_path), settings)
        ) is None

        await pr.deliver_proactive_round(
            agent_id="agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=manager,
            settings=settings,
        )

        assert (
            await pr.last_inbox_push_at(str(tmp_path), settings)
        ) is not None
