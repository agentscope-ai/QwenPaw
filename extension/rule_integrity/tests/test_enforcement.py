# -*- coding: utf-8 -*-
"""Tests for built-in rule integrity fail-closed enforcement."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EXTENSION_DIR = Path(__file__).resolve().parents[2]
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from rule_integrity import enforcement
from rule_integrity.models import RuleIntegrityFinding, RuleIntegrityResult
from rule_integrity.verifier import _UNKNOWN_RESULT


@pytest.fixture(autouse=True)
def _reset_enforcement_state() -> None:
    enforcement._auto_repair_in_progress = False
    enforcement._auto_repair_completed_until = None
    enforcement._auto_repair_timeout_retry = 0
    enforcement._auto_repair_abandoned = False
    yield
    enforcement._auto_repair_in_progress = False
    enforcement._auto_repair_completed_until = None
    enforcement._auto_repair_timeout_retry = 0
    enforcement._auto_repair_abandoned = False


def test_lockdown_inactive_for_unknown_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: _UNKNOWN_RESULT,
    )

    assert enforcement.rule_integrity_lockdown_active() is False
    assert enforcement.get_enforcement_projection()["rules_disabled"] is False


def test_lockdown_active_for_tampered_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: RuleIntegrityResult(
            ok=False,
            status="tampered",
            message="tampered",
            checked_at="now",
            findings=[
                RuleIntegrityFinding(
                    file="dangerous_shell_commands.yaml",
                    reason="sha256_mismatch",
                ),
            ],
        ),
    )

    assert enforcement.rule_integrity_lockdown_active() is True
    projection = enforcement.get_enforcement_projection()
    assert projection["rules_disabled"] is True
    assert projection["auto_repair_in_progress"] is False


def test_timeout_retry_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: RuleIntegrityResult(
            ok=False,
            status="tampered",
            message="tampered",
            checked_at="now",
            findings=[],
        ),
    )

    enforcement.mark_auto_repair_started()
    enforcement.mark_auto_repair_timeout_retry(3)
    projection = enforcement.get_enforcement_projection()

    assert projection["auto_repair_in_progress"] is True
    assert projection["auto_repair_timeout_retry"] == 3
    assert projection["auto_repair_timeout_max"] == 5
    assert projection["auto_repair_abandoned"] is False


def test_abandoned_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: RuleIntegrityResult(
            ok=False,
            status="tampered",
            message="tampered",
            checked_at="now",
            findings=[],
        ),
    )

    enforcement.mark_auto_repair_started()
    enforcement.mark_auto_repair_abandoned()
    projection = enforcement.get_enforcement_projection()

    assert projection["rules_disabled"] is True
    assert projection["auto_repair_abandoned"] is True
    assert projection["auto_repair_in_progress"] is False
    assert projection["auto_repair_timeout_retry"] == 5


def test_auto_repair_completed_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: RuleIntegrityResult(
            ok=True,
            status="ok",
            message="ok",
            checked_at="now",
            findings=[],
        ),
    )

    enforcement.mark_auto_repair_finished(succeeded=True)
    projection = enforcement.get_enforcement_projection()

    assert projection["rules_disabled"] is False
    assert projection["auto_repair_completed"] is True
