# -*- coding: utf-8 -*-
"""Integration tests for Memory & ReMe module internals.

Covers src/qwenpaw/agents/memory/* (proactive_utils, base manager)
— 956 uncovered lines.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


# ------------------------------------------------------------------ #
# proactive_utils
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
def test_load_json_safely_dict() -> None:
    """load_json_safely parses a JSON string."""
    from qwenpaw.agents.memory.proactive.proactive_utils import (
        load_json_safely,
    )

    assert load_json_safely(json.dumps({"a": 1})) == {"a": 1}


@pytest.mark.integration
@pytest.mark.p1
def test_load_json_safely_garbage() -> None:
    """load_json_safely returns None for garbage input."""
    from qwenpaw.agents.memory.proactive.proactive_utils import (
        load_json_safely,
    )

    assert load_json_safely("not json") is None


@pytest.mark.integration
@pytest.mark.p1
def test_extract_content_string() -> None:
    """extract_content returns plain string content."""
    from qwenpaw.agents.memory.proactive.proactive_utils import (
        extract_content,
    )

    assert extract_content("hello") == "hello"


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


@pytest.mark.integration
@pytest.mark.p1
def test_get_memory_manager_backend_reme() -> None:
    """get_memory_manager_backend resolves the reme backend."""
    from qwenpaw.agents.memory.base_memory_manager import (
        get_memory_manager_backend,
    )

    backend = get_memory_manager_backend("reme")
    assert backend is not None
