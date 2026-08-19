# -*- coding: utf-8 -*-
"""Review tier env overrides must be discoverable, never ghost state.

Field incident (2026-08-07): review ran with the settings-center toggles
off because stale ``CREATOR_*_REVIEW_ENABLED=1`` vars stayed injected in
the launch command. The resolver keeps env-wins semantics (CI and
emergency override), so the override set must be reportable for the
startup log and, later, the settings API.
"""
from __future__ import annotations

from models.config import forced_review_env_overrides


_ALL = (
    "CREATOR_SYNC_REVIEW_ENABLED",
    "CREATOR_MEDIA_REVIEW_ENABLED",
    "CREATOR_SELF_REVIEW_ENABLED",
)


def test_silent_environment_reports_no_overrides(monkeypatch) -> None:
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)
    assert forced_review_env_overrides() == {}


def test_explicit_values_are_reported_even_when_falsy(monkeypatch) -> None:
    """``0`` is still an override: it shadows a UI-enabled tier."""

    for name in _ALL:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "0")
    monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "1")
    assert forced_review_env_overrides() == {
        "CREATOR_MEDIA_REVIEW_ENABLED": "0",
        "CREATOR_SELF_REVIEW_ENABLED": "1",
    }


def test_blank_values_do_not_count_as_overrides(monkeypatch) -> None:
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "  ")
    assert forced_review_env_overrides() == {}
