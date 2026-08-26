# -*- coding: utf-8 -*-
"""Review tier env overrides must be discoverable, never ghost state.

Field incident (2026-08-07): review ran with the settings-center toggles
off because stale ``CREATOR_*_REVIEW_ENABLED=1`` vars stayed injected in
the launch command. Env keeps override power but must be reportable.
"""

from __future__ import annotations

from models.config import forced_review_env_overrides

_ALL = (
    "CREATOR_SYNC_REVIEW_ENABLED",
    "CREATOR_MEDIA_REVIEW_ENABLED",
    "CREATOR_SELF_REVIEW_ENABLED",
)


def test_explicit_values_are_reported_even_when_falsy(monkeypatch) -> None:
    """``0`` is still an override: it shadows a UI-enabled tier."""
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)
    assert forced_review_env_overrides() == {}
    # Blank values never count as overrides.
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "  ")
    assert forced_review_env_overrides() == {}
    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "0")
    monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "1")
    assert forced_review_env_overrides() == {
        "CREATOR_MEDIA_REVIEW_ENABLED": "0",
        "CREATOR_SELF_REVIEW_ENABLED": "1",
    }
