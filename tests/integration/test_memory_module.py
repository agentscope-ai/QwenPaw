# -*- coding: utf-8 -*-
"""Integration tests for Memory & ReMe module internals.

Covers src/qwenpaw/agents/memory/* (proactive helpers, base manager).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ------------------------------------------------------------------ #
# proactive helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_ensure_tz_aware_naive() -> None:
    """ensure_tz_aware attaches UTC to a naive datetime."""
    from qwenpaw.agents.memory.proactive.proactive_utils import (
        ensure_tz_aware,
    )

    naive = datetime(2026, 8, 26, 12, 0, 0)
    aware = ensure_tz_aware(naive)
    assert aware.tzinfo is not None


@pytest.mark.integration
@pytest.mark.p1
def test_ensure_tz_aware_already() -> None:
    """ensure_tz_aware keeps an aware datetime unchanged."""
    from qwenpaw.agents.memory.proactive.proactive_utils import (
        ensure_tz_aware,
    )

    aware = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
    assert ensure_tz_aware(aware) == aware


@pytest.mark.integration
@pytest.mark.p1
def test_proactive_agenda_item_label_fallbacks() -> None:
    """An agenda item always renders a usable heading."""
    from qwenpaw.agents.memory.proactive.proactive_agenda import AgendaItem

    assert AgendaItem(title="Title", opener="Opener").label == "Title"
    assert AgendaItem(opener="Opener").label == "Opener"
    assert AgendaItem(topic_id="t-1").label == "t-1"
    assert AgendaItem(kind="reminder").is_reminder is True


@pytest.mark.integration
@pytest.mark.p1
def test_proactive_ledger_lives_in_the_memory_metadata_dir() -> None:
    """The delivery ledger is per-agent state, next to ReMe's metadata."""
    from qwenpaw.agents.memory.proactive.proactive_delivery import (
        ledger_path,
    )

    relative = ledger_path("/ws/agent-1", "mem_metadata")
    absolute = ledger_path("/ws/agent-1", "/var/lib/reme")

    assert str(relative) == (
        "/ws/agent-1/mem_metadata/proactive_delivered.json"
    )
    assert str(absolute) == "/var/lib/reme/proactive_delivered.json"


# ------------------------------------------------------------------ #
# base memory manager
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_get_memory_manager_backend_unknown() -> None:
    """get_memory_manager_backend raises or falls back for unknown."""
    from qwenpaw.agents.memory.base_memory_manager import (
        get_memory_manager_backend,
    )

    try:
        backend = get_memory_manager_backend("integ-unknown-backend")
        assert backend is not None
    except (ValueError, KeyError):
        pass  # unknown backend may be rejected
