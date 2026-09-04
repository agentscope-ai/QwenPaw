# -*- coding: utf-8 -*-
"""Detect when the agent is stuck, so the advisor can step back in.

Three separable pieces, so each can be tuned without touching the others:

* ``FailureDetector`` — decides whether one tool result counts as a failure.
  Two layers: a structured check (the tool reported an error) and a
  per-tool semantic check (the tool "succeeded" but the outcome is a
  failure — a compile that ran fine yet printed ``[FAIL]``, a fetch that
  returned a 404 page, a search that matched nothing).
* ``AdvisorInterventionConfig`` (from the agent config) — the thresholds.
* ``InterventionTrigger`` — the counters and the fire/reset policy.

The two conditions are OR'd: the window (by default 4 failures in 10
steps) tells struggling runs from healthy ones, and a consecutive streak
(by default 3 in a row) fires earlier when the agent is stuck on one call.
A streak also marks the harder failure — the same call repeated verbatim
rather than an edit→build oscillation — exposed as
``TriggerEvent.severity`` so the caller can escalate its wording.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ...config.config import AdvisorInterventionConfig

# ── Layer 1: structured failure signals ─────────────────────────────────
# Substring matches over the WHOLE tool output are unsafe: a browser
# snapshot of a 404 page legitimately contains "Not Found" while the tool
# call itself succeeded. These prefixes/markers are emitted by the tool
# layer itself, not by the content it returns.
STRUCTURED_FAILURE_PREFIXES: tuple[str, ...] = (
    "Command failed",
    "Input validation failed",
    "Error:",
    # The tool layer's retryable-failure envelope, and the three refusals it
    # does not cover. All four are emitted as the whole observation, so they
    # are matched as prefixes: a file whose CONTENT discusses
    # ToolNotFoundError is not a failed call, which is the same trap the
    # note above describes.
    "[RETRYABLE]",
    "ToolNotFoundError",
    "Approval for",
)

# Anchored patterns for the failures that do not start with a fixed string
# (browser worker crashes, approval timeouts, bad kwargs, unknown tools,
# policy denials).
STRUCTURED_FAILURE_PATTERNS: tuple[str, ...] = (
    # Right tool, wrong argument name: "web_search() got an unexpected ..."
    r"^\w+\(\) got an unexpected keyword argument",
    # "governance: 'Bash' is denied by policy"
    r"^governance:.*\bdenied by policy\b",
)

STRUCTURED_FAILURE_MARKERS: tuple[str, ...] = ('"ok": false',)


# ── Layer 2: per-tool semantic failure rules ────────────────────────────
@dataclass(frozen=True)
class SemanticRule:
    """A 'succeeded but did not work' pattern, scoped to one tool.

    Scoping to a tool is what keeps this safe — ``[FAIL]`` means a failing
    test under ``execute_shell_command`` but is just page text elsewhere.
    """

    tool: str
    pattern: str
    label: str
    flags: int = re.IGNORECASE

    def matches(self, output: str) -> bool:
        """Return whether *output* matches this rule's pattern."""
        return re.search(self.pattern, output, self.flags) is not None


SEMANTIC_RULES: tuple[SemanticRule, ...] = (
    # A test harness that runs cleanly (exit 0) while every case fails.
    SemanticRule(
        tool="execute_shell_command",
        pattern=(
            r"\[FAIL\]|\bFAILED\b|\bAssertionError\b"
            r"|Traceback \(most recent"
        ),
        label="shell:test-or-exception-in-output",
    ),
    # Compilers/linkers report through stderr without always exiting
    # non-zero.
    SemanticRule(
        tool="execute_shell_command",
        pattern=(
            r"\[stderr\][\s\S]*?"
            r"(?:error:|not found|Syntax error|undefined reference)"
        ),
        label="shell:stderr-error",
    ),
    # A fetch that "worked" but landed on an error page. Both browser
    # tracks register the tool as "browser".
    SemanticRule(
        tool="browser",
        pattern=(
            r'"(?:title|url)"\s*:\s*"[^"]*'
            r"\b(?:404|403|not found|forbidden|error)\b"
        ),
        label="browser:error-page",
    ),
    # A search that ran but matched nothing — repeated, it means the model
    # is guessing at names that do not exist.
    SemanticRule(
        tool="grep_search",
        pattern=r"\bNo matches found\b",
        label="search:zero-results",
    ),
    SemanticRule(
        tool="glob_search",
        pattern=r"\bNo files found\b|\bNo matches found\b",
        label="search:zero-results",
    ),
    SemanticRule(
        tool="web_search",
        pattern=r"\bno results\b|\brate limit\b|\b429\b|\bquota\b",
        label="web_search:no-results-or-throttled",
    ),
)


@dataclass
class FailureVerdict:
    """The outcome of classifying one tool result."""

    is_failure: bool
    layer: str = ""  # "structured" | "semantic" | ""
    label: str = ""

    def __bool__(self) -> bool:
        return self.is_failure


class FailureDetector:
    """Classify a single tool result as success or failure."""

    def __init__(
        self,
        rules: Iterable[SemanticRule] = SEMANTIC_RULES,
    ) -> None:
        self._by_tool: dict[str, list[SemanticRule]] = {}
        for rule in rules:
            self._by_tool.setdefault(rule.tool, []).append(rule)

    def classify(self, tool: str | None, output: Any) -> FailureVerdict:
        """Return a verdict for one tool result."""
        text = output if isinstance(output, str) else str(output)
        stripped = text.lstrip()

        for prefix in STRUCTURED_FAILURE_PREFIXES:
            if stripped.startswith(prefix):
                return FailureVerdict(True, "structured", prefix)
        for pattern in STRUCTURED_FAILURE_PATTERNS:
            if re.search(pattern, stripped, re.MULTILINE):
                return FailureVerdict(True, "structured", pattern)
        for marker in STRUCTURED_FAILURE_MARKERS:
            if marker in text:
                return FailureVerdict(True, "structured", marker)

        for rule in self._by_tool.get(tool or "", ()):
            if rule.matches(text):
                return FailureVerdict(True, "semantic", rule.label)

        return FailureVerdict(False)


# ── Trigger policy ──────────────────────────────────────────────────────


@dataclass
class ObservedStep:
    """One tool call and how it turned out — the payload sent to the
    advisor."""

    tool: str
    args: Any
    output: str
    failed: bool
    label: str = ""


@dataclass
class TriggerEvent:
    """Raised by :class:`InterventionTrigger` when the advisor should
    speak."""

    reason: str  # "consecutive" | "window"
    severity: str  # "stuck" (repeating itself) | "struggling"
    step_index: int
    intervention_index: int  # 1-based
    recent: list[ObservedStep] = field(default_factory=list)


class InterventionTrigger:
    """Track failures and decide when the advisor should speak again.

    Fires on ``consecutive_failures`` in a row OR ``window_failures``
    within the last ``window_size`` steps. Both counters reset on fire, so
    the next intervention needs a fresh run of trouble rather than
    re-firing on the failures that already triggered one.
    """

    def __init__(
        self,
        config: AdvisorInterventionConfig | None = None,
        detector: FailureDetector | None = None,
        history_size: int = 3,
    ) -> None:
        self.config = config or AdvisorInterventionConfig()
        self.detector = detector or FailureDetector()
        self._history_size = history_size
        self._consecutive = 0
        self._window: list[bool] = []
        self._recent: list[ObservedStep] = []
        self._steps_seen = 0
        self._interventions = 0
        self._last_fire_step: int | None = None

    @property
    def interventions(self) -> int:
        """How many times the trigger has fired so far."""
        return self._interventions

    @property
    def exhausted(self) -> bool:
        """Whether the intervention budget is used up."""
        return self._interventions >= self.config.max_interventions

    @property
    def recent(self) -> list[ObservedStep]:
        """The last few observed steps, oldest first."""
        return list(self._recent)

    def reset_counters(self) -> None:
        """Forget the current run of failures.

        Called after the agent consulted the advisor on its own, so the
        same failures are not immediately counted towards an automatic
        intervention as well. The intervention budget is untouched.
        """
        self._consecutive = 0
        self._window.clear()

    def _repeating(self) -> bool:
        """Are the recent failures the same call over and over?"""
        fails = [s for s in self._recent if s.failed]
        if len(fails) < 2:
            return False
        keys = {
            (s.tool, json.dumps(s.args, sort_keys=True, default=str))
            for s in fails
        }
        return len(keys) == 1

    def observe(
        self,
        tool: str | None,
        args: Any,
        output: Any,
    ) -> TriggerEvent | None:
        """Record one tool result and return an event if the advisor should
        run."""
        cfg = self.config
        verdict = self.detector.classify(tool, output)
        text = output if isinstance(output, str) else str(output)

        self._steps_seen += 1
        self._recent.append(
            ObservedStep(
                tool=tool or "unknown",
                args=args,
                output=text,
                failed=bool(verdict),
                label=verdict.label,
            ),
        )
        del self._recent[: -self._history_size]

        self._consecutive = self._consecutive + 1 if verdict else 0
        self._window.append(bool(verdict))
        del self._window[: -cfg.window_size]

        if self.exhausted:
            return None
        if (
            self._last_fire_step is not None
            and self._steps_seen - self._last_fire_step <= cfg.cooldown_steps
        ):
            return None

        reason = ""
        if self._consecutive >= cfg.consecutive_failures:
            reason = "consecutive"
        elif sum(self._window) >= cfg.window_failures:
            reason = "window"
        if not reason:
            return None

        event = TriggerEvent(
            reason=reason,
            severity="stuck" if self._repeating() else "struggling",
            step_index=self._steps_seen - 1,
            intervention_index=self._interventions + 1,
            recent=list(self._recent),
        )
        # Clear both counters so the next fire needs fresh evidence.
        self._consecutive = 0
        self._window.clear()
        self._interventions += 1
        self._last_fire_step = self._steps_seen
        return event


__all__ = [
    "FailureDetector",
    "FailureVerdict",
    "InterventionTrigger",
    "ObservedStep",
    "SEMANTIC_RULES",
    "STRUCTURED_FAILURE_MARKERS",
    "STRUCTURED_FAILURE_PATTERNS",
    "STRUCTURED_FAILURE_PREFIXES",
    "SemanticRule",
    "TriggerEvent",
]
