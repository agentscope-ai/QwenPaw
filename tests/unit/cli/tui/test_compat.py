# -*- coding: utf-8 -*-
"""Regression tests for Textual compatibility fixes."""

from __future__ import annotations

# Tests exercise the private wrapper and its one-time installation state.
# pylint: disable=protected-access

from textual.geometry import Offset
from textual.screen import Screen
from textual.widget import Widget

from qwenpaw.cli.tui import compat


def test_hit_testing_ignores_detached_widget(monkeypatch):
    """A stale compositor hit must not reach Textual's selection path."""
    detached = Widget()
    monkeypatch.setattr(
        compat,
        "_ORIGINAL_GET_WIDGET_AND_OFFSET_AT",
        lambda _screen, _x, _y: (detached, Offset(0, 0)),
    )

    assert compat._safe_get_widget_and_offset_at(Screen(), 1, 1) == (
        None,
        None,
    )


def test_hit_testing_preserves_attached_widget(monkeypatch):
    """Normal text selection keeps the original hit-testing result."""
    screen = Screen()
    attached = Widget()
    attached._parent = screen  # pylint: disable=protected-access
    expected = (attached, Offset(2, 3))
    monkeypatch.setattr(
        compat,
        "_ORIGINAL_GET_WIDGET_AND_OFFSET_AT",
        lambda _screen, _x, _y: expected,
    )

    assert compat._safe_get_widget_and_offset_at(screen, 1, 1) == expected


def test_apply_textual_compat_is_idempotent(monkeypatch):
    """Repeated setup leaves the same wrapper installed."""
    monkeypatch.setattr(compat, "_COMPAT_APPLIED", False)
    monkeypatch.setattr(
        Screen,
        "get_widget_and_offset_at",
        compat._ORIGINAL_GET_WIDGET_AND_OFFSET_AT,
    )

    compat.apply_textual_compat()
    compat.apply_textual_compat()

    assert (
        Screen.get_widget_and_offset_at
        is compat._safe_get_widget_and_offset_at
    )
