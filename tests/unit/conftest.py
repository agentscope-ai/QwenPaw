# -*- coding: utf-8 -*-
"""Shared fixtures for the unit tier."""

import pytest

from qwenpaw.providers.model_cooldown import reset_model_cooldowns


@pytest.fixture(autouse=True)
def isolate_model_cooldowns():
    """The cooldown registry is process-wide, so tests must not share it.

    It lives at the unit tier rather than under ``providers/`` because
    anything that builds a real fallback chain writes to it, including
    ``tests/unit/agents/test_reasoning_fallback_bridge.py``.
    """
    reset_model_cooldowns()
    yield
    reset_model_cooldowns()
