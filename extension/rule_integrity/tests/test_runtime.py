# -*- coding: utf-8 -*-
"""Tests for event-driven rule integrity runtime."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EXTENSION_DIR = Path(__file__).resolve().parents[2]
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from rule_integrity import enforcement
from rule_integrity.models import RuleIntegrityResult
from rule_integrity.runtime import RuleIntegrityRuntime
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


@pytest.mark.asyncio
async def test_runtime_publish_deduplicates_identical_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RuleIntegrityRuntime()
    monkeypatch.setattr(
        "rule_integrity.runtime.get_last_rule_integrity_status",
        lambda: RuleIntegrityResult(
            ok=True,
            status="ok",
            message="ok",
            checked_at="now",
            findings=[],
        ),
    )

    published_first = await runtime.publish_status_if_changed("test")
    published_second = await runtime.publish_status_if_changed("test")

    assert published_first is True
    assert published_second is False


@pytest.mark.asyncio
async def test_runtime_suppresses_recent_watch_events() -> None:
    runtime = RuleIntegrityRuntime()
    runtime.suppress_paths("dangerous_shell_commands.yaml", ttl_seconds=5.0)

    assert runtime.is_suppressed("dangerous_shell_commands.yaml") is True
    assert runtime.is_suppressed("rules_manifest.json") is False


def test_lockdown_inactive_before_first_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_last_rule_integrity_status",
        lambda: _UNKNOWN_RESULT,
    )

    assert enforcement.rule_integrity_lockdown_active() is False


@pytest.mark.asyncio
async def test_watchdog_passes_retry_after_abandon_to_auto_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RuleIntegrityRuntime()
    calls: list[bool] = []
    tampered = RuleIntegrityResult(
        ok=False,
        status="tampered",
        message="tampered",
        checked_at="now",
        findings=[],
    )

    async def _mock_auto_repair(*, retry_after_abandon: bool = False) -> None:
        calls.append(retry_after_abandon)

    monkeypatch.setattr(
        "rule_integrity.runtime.verify_default_builtin_rule_files",
        lambda: tampered,
    )
    monkeypatch.setattr(
        "rule_integrity.enforcement.get_last_rule_integrity_status",
        lambda: tampered,
    )
    monkeypatch.setattr(
        "rule_integrity.runtime.maybe_run_auto_repair",
        _mock_auto_repair,
    )

    async def _noop_publish(_source: str) -> bool:
        return True

    monkeypatch.setattr(runtime, "publish_status_if_changed", _noop_publish)

    await runtime.run_verify_and_react(source="watchdog")

    assert calls == [True]


@pytest.mark.asyncio
async def test_startup_does_not_force_retry_after_abandon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RuleIntegrityRuntime()
    calls: list[bool] = []
    tampered = RuleIntegrityResult(
        ok=False,
        status="tampered",
        message="tampered",
        checked_at="now",
        findings=[],
    )

    async def _mock_auto_repair(*, retry_after_abandon: bool = False) -> None:
        calls.append(retry_after_abandon)

    monkeypatch.setattr(
        "rule_integrity.runtime.verify_default_builtin_rule_files",
        lambda: tampered,
    )
    monkeypatch.setattr(
        "rule_integrity.enforcement.get_last_rule_integrity_status",
        lambda: tampered,
    )
    monkeypatch.setattr(
        "rule_integrity.runtime.maybe_run_auto_repair",
        _mock_auto_repair,
    )

    async def _noop_publish(_source: str) -> bool:
        return True

    monkeypatch.setattr(runtime, "publish_status_if_changed", _noop_publish)
    enforcement.mark_auto_repair_abandoned()

    await runtime.run_verify_and_react(source="startup")

    assert calls == [False]
