# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Tests for the advisor re-entry trigger."""
from __future__ import annotations

import pytest

from qwenpaw.modes.advisor import trigger as advisor_trigger
from qwenpaw.modes.advisor.trigger import (
    FailureDetector,
    InterventionTrigger,
    TriggerConfig,
)


@pytest.fixture
def detector():
    return FailureDetector()


# ── Layer 1: structured ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool,output",
    [
        (
            "execute_shell_command",
            "Command failed with exit code 1.\n[stderr]\nboom",
        ),
        (
            "write_file",
            "Input validation failed for tool 'write_file': "
            "'content' is a required property",
        ),
        ("read_file", "Error: The file /nope does not exist."),
        ("browser", '{\n  "ok": false,\n  "error": "Open failed"\n}'),
    ],
)
def test_structured_failures(detector, tool, output):
    verdict = detector.classify(tool, output)
    assert verdict.is_failure and verdict.layer == "structured"


def test_plain_success_is_not_a_failure(detector):
    assert not detector.classify("read_file", "line 1\nline 2")
    assert not detector.classify("write_file", '{"ok": true}')


# ── Layer 2: semantic ───────────────────────────────────────────────────


def test_shell_exit_zero_but_tests_failed(detector):
    """The harness ran fine, every case failed."""
    out = (
        "=== SVPWM Test Results ===\n"
        "[FAIL] T01: computed=(0,0,0)\n[FAIL] T02: ...\n"
    )
    verdict = detector.classify("execute_shell_command", out)
    assert verdict.is_failure and verdict.layer == "semantic"


def test_shell_stderr_error_without_nonzero_exit(detector):
    out = "Script written\n[stderr]\n/bin/sh: 2: lines.append: not found\n"
    assert detector.classify("execute_shell_command", out).is_failure


def test_search_zero_results(detector):
    assert detector.classify(
        "grep_search",
        "No matches found for pattern: def foo",
    ).is_failure


def test_browser_error_page(detector):
    """The tool is registered as "browser"; the historical "browser_use"
    name is not a tool anything calls, so the rule must not key to it."""
    out = '{"ok": true, "url": "https://x/404", "title": "404 Not Found"}'
    assert detector.classify("browser", out).is_failure
    assert not detector.classify("browser_use", out).is_failure


def test_404_page_body_is_not_a_failure(detector):
    """Regression: a *successful* snapshot whose CONTENT mentions
    'Not Found'. Only the structured status and tool-scoped rules may
    decide."""
    out = (
        '{\n  "ok": true,\n  "snapshot": "- document:\\n  - main:\\n'
        '      - img \\"404\\"\\n      - heading \\"Not Found\\" [ref=e9]\\n'
        '      - paragraph: The page you requested no longer exists"\n}'
    )
    assert not detector.classify("browser_use", out).is_failure


def test_semantic_rules_are_tool_scoped(detector):
    """'[FAIL]' is a failing test in shell output, plain text elsewhere."""
    out = "the log line reads [FAIL] but this is just a file we read"
    assert not detector.classify("read_file", out).is_failure
    assert detector.classify("execute_shell_command", out).is_failure


@pytest.mark.parametrize(
    "output",
    [
        "[RETRYABLE] browser worker terminated unexpectedly\n"
        "browser worker transport disconnected",
        "ToolNotFoundError: The tool named 'tavily_search' doesn't exist.",
        "web_search() got an unexpected keyword argument 'max_results'",
        "Approval for 'Write' timed out after 300s.",
        "governance: 'Bash' is denied by policy",
    ],
)
def test_tool_layer_failures_are_detected(detector, output):
    """Envelopes emitted by the tool layer itself count as failures."""
    assert detector.classify("execute_shell_command", output).is_failure


def test_content_mentioning_those_words_is_not_a_failure(detector):
    """The markers are emitted by the tool layer, never by returned
    content."""
    out = (
        '{"ok": true, "text": "The docs explain that a ToolNotFoundError is '
        "raised when a tool is missing, and that approval for writes may "
        'time out."}'
    )
    assert not detector.classify("read_file", out).is_failure


# ── Trigger policy ──────────────────────────────────────────────────────

FAIL = "Command failed with exit code 1."
OK = "done"


def _feed(trigger, outputs, tool="execute_shell_command", args=None):
    events = []
    for i, out in enumerate(outputs):
        call_args = args if args is not None else {"command": f"c{i}"}
        event = trigger.observe(tool, call_args, out)
        if event:
            events.append(event)
    return events


def test_consecutive_fires_on_third_failure():
    trigger = InterventionTrigger(
        TriggerConfig(consecutive_failures=3, window_failures=99),
    )
    events = _feed(trigger, [FAIL, FAIL, FAIL])
    assert len(events) == 1
    assert events[0].reason == "consecutive"
    assert events[0].step_index == 2


def test_two_failures_do_not_fire():
    trigger = InterventionTrigger(
        TriggerConfig(consecutive_failures=3, window_failures=99),
    )
    assert not _feed(trigger, [FAIL, FAIL, OK])


def test_window_fires_on_scattered_failures():
    """edit(ok) → build(fail), repeatedly. Never 3 in a row."""
    trigger = InterventionTrigger(
        TriggerConfig(
            consecutive_failures=3,
            window_size=10,
            window_failures=4,
        ),
    )
    events = _feed(trigger, [FAIL, OK, FAIL, OK, FAIL, OK, FAIL])
    assert len(events) == 1
    assert events[0].reason == "window"


def test_window_forgets_old_failures():
    trigger = InterventionTrigger(
        TriggerConfig(
            consecutive_failures=99,
            window_size=4,
            window_failures=3,
        ),
    )
    assert not _feed(trigger, [FAIL, OK, OK, OK, OK, FAIL, OK, OK])


def test_counters_reset_after_firing():
    """A fresh run of trouble is required — no re-firing on the same
    evidence."""
    trigger = InterventionTrigger(
        TriggerConfig(
            consecutive_failures=3,
            window_failures=99,
            max_interventions=99,
        ),
    )
    events = _feed(trigger, [FAIL, FAIL, FAIL, FAIL, FAIL])
    assert len(events) == 1, "5 straight failures must fire once"
    events += _feed(trigger, [FAIL])  # 6th → new run of 3 complete
    assert len(events) == 2


def test_max_interventions_cap():
    trigger = InterventionTrigger(
        TriggerConfig(
            consecutive_failures=3,
            window_failures=99,
            max_interventions=2,
        ),
    )
    events = _feed(trigger, [FAIL] * 12)
    assert len(events) == 2
    assert trigger.exhausted


def test_cooldown_suppresses_immediate_refire():
    trigger = InterventionTrigger(
        TriggerConfig(
            consecutive_failures=3,
            window_failures=99,
            cooldown_steps=5,
            max_interventions=99,
        ),
    )
    events = _feed(trigger, [FAIL] * 7)
    assert len(events) == 1, "cooldown must hold off the second fire"


# ── Severity ────────────────────────────────────────────────────────────


def test_severity_stuck_when_the_call_repeats_verbatim():
    """write_file emitted three times with identical args, no content."""
    trigger = InterventionTrigger(
        TriggerConfig(consecutive_failures=3, window_failures=99),
    )
    same = {"file_path": "backtest.py"}
    events = [
        event
        for out in [FAIL] * 3
        if (event := trigger.observe("write_file", same, out)) is not None
    ]
    assert events[0].severity == "stuck"


def test_severity_struggling_when_calls_differ():
    trigger = InterventionTrigger(
        TriggerConfig(consecutive_failures=3, window_failures=99),
    )
    events = _feed(trigger, [FAIL, FAIL, FAIL])  # distinct commands
    assert events[0].severity == "struggling"


def test_event_carries_recent_calls_for_the_advisor():
    trigger = InterventionTrigger(
        TriggerConfig(consecutive_failures=3, window_failures=99),
    )
    events = _feed(trigger, [OK, FAIL, FAIL, FAIL])
    recent = events[0].recent
    assert len(recent) == 3
    assert all(step.failed for step in recent)
    assert recent[-1].tool == "execute_shell_command"


# ── Config ──────────────────────────────────────────────────────────────


def test_config_defaults_to_the_module_constants():
    cfg = TriggerConfig()
    assert cfg.consecutive_failures == advisor_trigger._CONSECUTIVE_FAILURES
    assert cfg.window_size == advisor_trigger._WINDOW_SIZE
    assert cfg.window_failures == advisor_trigger._WINDOW_FAILURES
    assert cfg.cooldown_steps == advisor_trigger._COOLDOWN_STEPS
    assert cfg.max_interventions == advisor_trigger._MAX_INTERVENTIONS


def test_trigger_without_config_uses_defaults():
    assert InterventionTrigger().config == TriggerConfig()


def test_config_is_overridable_per_instance():
    cfg = TriggerConfig(
        consecutive_failures=5,
        window_size=20,
        max_interventions=1,
    )
    assert (
        cfg.consecutive_failures,
        cfg.window_size,
        cfg.max_interventions,
    ) == (5, 20, 1)
    assert InterventionTrigger(config=cfg).config is cfg


# ── recent window + manual reset ────────────────────────────────────────


def test_recent_exposes_the_last_steps_oldest_first():
    trigger = InterventionTrigger(history_size=2)
    _feed(trigger, [OK, FAIL, OK])
    recent = trigger.recent
    assert [s.output for s in recent] == [FAIL, OK]
    assert [s.failed for s in recent] == [True, False]


def test_reset_counters_forgets_the_current_run_but_not_the_budget():
    trigger = InterventionTrigger(
        TriggerConfig(consecutive_failures=3, window_failures=99),
    )
    _feed(trigger, [FAIL, FAIL])
    trigger.reset_counters()
    assert not _feed(trigger, [FAIL]), "the run restarted after the reset"
    assert trigger.interventions == 0
