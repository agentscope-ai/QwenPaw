# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared plugin test isolation."""

import pytest

from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture(name="short_interrupt_timeout")
def bounded_interrupt_timeout(monkeypatch):
    """Exercise blocked lifecycle retries without the production 5s wait."""
    from qwenpaw.plugins import activity

    monkeypatch.setattr(activity, "INTERRUPT_TIMEOUT_SECONDS", 0.2)
    return activity.INTERRUPT_TIMEOUT_SECONDS


@pytest.fixture()
def short_stream_stop_timeout(monkeypatch, short_interrupt_timeout):
    """Scale nested stream stops with the outer interruption budget."""
    from qwenpaw.plugins import custody

    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", short_interrupt_timeout)


@pytest.fixture()
def fresh_registry():
    """Reset the singleton and restore it even if a test fails."""
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        yield PluginRegistry()
    finally:
        PluginRegistry._instance = old
