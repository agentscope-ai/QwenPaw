# -*- coding: utf-8 -*-
"""Tests for automatic rule integrity repair retries."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_EXTENSION_DIR = Path(__file__).resolve().parents[2]
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from rule_integrity import auto_repair, enforcement
from rule_integrity.constants import MAX_CONSECUTIVE_TIMEOUT_RETRIES
from rule_integrity.models import (
    RuleIntegrityFinding,
    RuleIntegrityRepairResult,
    RuleIntegrityResult,
)


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


def _tampered_status() -> RuleIntegrityResult:
    return RuleIntegrityResult(
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
    )


def _timeout_repair_result() -> RuleIntegrityRepairResult:
    return RuleIntegrityRepairResult(
        ok=False,
        message="timeout",
        source_url="https://example.test/rules.yaml",
        backup_path=None,
        integrity=_tampered_status(),
        connection_timeout=True,
    )


@pytest.mark.asyncio
async def test_auto_repair_abandons_after_five_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: _tampered_status(),
    )
    monkeypatch.setattr(
        auto_repair,
        "repair_default_builtin_rule_file",
        lambda: _timeout_repair_result(),
    )
    monkeypatch.setattr(auto_repair, "REPAIR_TIMEOUT_RETRY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(
        auto_repair,
        "reload_tool_guard_engine_rules",
        lambda: None,
    )

    calls: list[str] = []

    class _Runtime:
        async def publish_status_if_changed(self, source: str) -> bool:
            calls.append(source)
            return True

    monkeypatch.setattr(
        "rule_integrity.runtime.get_rule_integrity_runtime",
        lambda: _Runtime(),
    )

    await auto_repair.maybe_run_auto_repair()

    projection = enforcement.get_enforcement_projection()
    assert projection["auto_repair_abandoned"] is True
    assert projection["auto_repair_timeout_retry"] == MAX_CONSECUTIVE_TIMEOUT_RETRIES
    assert projection["auto_repair_in_progress"] is False
    assert "repair_abandoned" in calls


@pytest.mark.asyncio
async def test_auto_repair_skips_when_already_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: _tampered_status(),
    )
    enforcement.mark_auto_repair_abandoned()
    attempts = {"count": 0}

    def _repair() -> RuleIntegrityRepairResult:
        attempts["count"] += 1
        return _timeout_repair_result()

    monkeypatch.setattr(auto_repair, "repair_default_builtin_rule_file", _repair)

    await auto_repair.maybe_run_auto_repair()

    assert attempts["count"] == 0


@pytest.mark.asyncio
async def test_auto_repair_retries_when_forced_after_abandon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: _tampered_status(),
    )
    enforcement.mark_auto_repair_abandoned()
    attempts = {"count": 0}

    def _repair() -> RuleIntegrityRepairResult:
        attempts["count"] += 1
        return RuleIntegrityRepairResult(
            ok=True,
            message="repaired",
            source_url="https://example.test/rules.yaml",
            backup_path=None,
            integrity=RuleIntegrityResult(
                ok=True,
                status="ok",
                message="ok",
                checked_at="now",
                findings=[],
            ),
        )

    monkeypatch.setattr(auto_repair, "repair_default_builtin_rule_file", _repair)
    monkeypatch.setattr(
        auto_repair,
        "reload_tool_guard_engine_rules",
        lambda: None,
    )

    class _Runtime:
        async def publish_status_if_changed(self, _source: str) -> bool:
            return True

    monkeypatch.setattr(
        "rule_integrity.runtime.get_rule_integrity_runtime",
        lambda: _Runtime(),
    )

    result = await auto_repair.run_trusted_source_repair(retry_after_abandon=True)

    assert attempts["count"] == 1
    assert result is not None
    assert result.ok is True
    projection = enforcement.get_enforcement_projection()
    assert projection["auto_repair_abandoned"] is False
