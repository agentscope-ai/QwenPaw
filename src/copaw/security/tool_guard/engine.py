# -*- coding: utf-8 -*-
"""Tool guard engine – orchestrates all registered guardians.

:class:`ToolGuardEngine` follows the same lazy-singleton pattern used by
the skill scanner.  It discovers and runs all active :class:`BaseToolGuardian`
instances and aggregates their findings into a :class:`ToolGuardResult`.

Usage::

    engine = ToolGuardEngine()
    result = engine.guard("execute_shell_command", {"command": "rm -rf /"})
    if not result.is_safe:
        logger.warning("Tool guard found issues: %s", result.max_severity)

Custom guardians can be registered at construction time or later via
:meth:`register_guardian`.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from .guardians import BaseToolGuardian
from .guardians.rule_guardian import RuleBasedToolGuardian
from .models import ToolGuardResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-variable knobs
# ---------------------------------------------------------------------------
#  COPAW_TOOL_GUARD_ENABLED  – "true" (default) / "false"

_TRUE_STRINGS = {"true", "1", "yes"}


def _guard_enabled() -> bool:
    """Return whether tool-call guarding is enabled."""
    return os.environ.get("COPAW_TOOL_GUARD_ENABLED", "true").lower() in _TRUE_STRINGS


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ToolGuardEngine:
    """Orchestrates pre-tool-call security guarding.

    Parameters
    ----------
    guardians:
        Explicit list of guardians.  If *None* the default set
        (rule-based) is used.
    enabled:
        Override the ``COPAW_TOOL_GUARD_ENABLED`` env var.
    """

    def __init__(
        self,
        guardians: list[BaseToolGuardian] | None = None,
        *,
        enabled: bool | None = None,
    ) -> None:
        self._enabled = enabled if enabled is not None else _guard_enabled()

        if guardians is not None:
            self._guardians = list(guardians)
        else:
            self._guardians = self._default_guardians()

    # ------------------------------------------------------------------
    # Default guardians
    # ------------------------------------------------------------------

    @staticmethod
    def _default_guardians() -> list[BaseToolGuardian]:
        """Return the default set of guardians."""
        guardians: list[BaseToolGuardian] = []
        try:
            guardians.append(RuleBasedToolGuardian())
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to initialise RuleBasedToolGuardian: %s", exc)
        return guardians

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_guardian(self, guardian: BaseToolGuardian) -> None:
        """Register an additional guardian."""
        self._guardians.append(guardian)
        logger.debug("Registered tool guardian: %s", guardian.name)

    def unregister_guardian(self, name: str) -> bool:
        """Remove a guardian by name.  Returns True if found."""
        before = len(self._guardians)
        self._guardians = [g for g in self._guardians if g.name != name]
        return len(self._guardians) < before

    @property
    def guardian_names(self) -> list[str]:
        return [g.name for g in self._guardians]

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> ToolGuardResult | None:
        """Guard a tool call's parameters.

        Parameters
        ----------
        tool_name:
            Name of the tool being called.
        params:
            Keyword arguments that will be passed to the tool function.

        Returns
        -------
        ToolGuardResult or None
            ``None`` when guarding is disabled.
        """
        if not self._enabled:
            return None

        t0 = time.monotonic()
        result = ToolGuardResult(
            tool_name=tool_name,
            params=params,
        )

        for guardian in self._guardians:
            try:
                findings = guardian.guard(tool_name, params)
                result.findings.extend(findings)
                result.guardians_used.append(guardian.name)
            except Exception as exc:
                logger.warning(
                    "Tool guardian '%s' failed on tool '%s': %s",
                    guardian.name,
                    tool_name,
                    exc,
                )
                result.guardians_failed.append(
                    {"name": guardian.name, "error": str(exc)}
                )

        result.guard_duration_seconds = time.monotonic() - t0
        return result


# ---------------------------------------------------------------------------
# Lazy singleton (module-level)
# ---------------------------------------------------------------------------

_engine_instance: ToolGuardEngine | None = None


def get_guard_engine() -> ToolGuardEngine:
    """Return a lazily-initialised :class:`ToolGuardEngine` singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ToolGuardEngine()
    return _engine_instance
