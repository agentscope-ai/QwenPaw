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
import time
from typing import Any

from ...constant import EnvVarLoader
from .guardians import BaseToolGuardian
from .guardians.file_guardian import FilePathToolGuardian
from .guardians.rule_guardian import RuleBasedToolGuardian
from .guardians.shell_evasion_guardian import ShellEvasionGuardian
from .models import ToolGuardResult

logger = logging.getLogger(__name__)

_TRUE_STRINGS = {"true", "1", "yes"}


def _guard_enabled() -> bool:
    """Return whether tool-call guarding is enabled.

    Priority: env var > config.json > default (True).
    """
    env_val = EnvVarLoader.get_str("QWENPAW_TOOL_GUARD_ENABLED") or None
    if env_val is not None:
        return env_val.lower() in _TRUE_STRINGS

    try:
        from qwenpaw.config import load_config

        cfg = load_config()
        return cfg.security.tool_guard.enabled
    except Exception:
        return True


class ToolGuardEngine:
    """Orchestrates pre-tool-call security guarding.

    Parameters
    ----------
    guardians:
        Explicit list of guardians.  If *None* the default set
        (rule-based) is used.
    enabled:
        Override ``QWENPAW_TOOL_GUARD_ENABLED`` env var.
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

        self._reload_tool_sets()

    # ------------------------------------------------------------------
    # Default guardians
    # ------------------------------------------------------------------

    @staticmethod
    def _default_guardians() -> list[BaseToolGuardian]:
        """Return the default set of guardians."""
        guardians: list[BaseToolGuardian] = []
        try:
            guardians.append(FilePathToolGuardian())
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Failed to initialise FilePathToolGuardian: %s",
                exc,
            )
        try:
            guardians.append(RuleBasedToolGuardian())
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Failed to initialise RuleBasedToolGuardian: %s",
                exc,
            )
        try:
            guardians.append(ShellEvasionGuardian())
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Failed to initialise ShellEvasionGuardian: %s",
                exc,
            )
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

    @property
    def guarded_tools(self) -> set[str] | None:
        """Tools in the guard scope.  ``None`` means guard all tools."""
        return self._guarded_tools

    @property
    def denied_tools(self) -> set[str]:
        """Tools unconditionally denied (no approval offered)."""
        return self._denied_tools

    @property
    def auto_denied_rules(self) -> set[str]:
        """Rule IDs that unconditionally deny matched tool calls."""
        return self._auto_denied_rules

    def _reload_tool_sets(self) -> None:
        """Refresh guarded/denied tool and rule sets from config."""
        from .utils import (
            resolve_auto_denied_rules,
            resolve_denied_tools,
            resolve_guarded_tools,
        )

        self._guarded_tools: set[str] | None = resolve_guarded_tools()
        self._denied_tools: set[str] = resolve_denied_tools()
        self._auto_denied_rules: set[str] = resolve_auto_denied_rules()

    def reload_rules(self) -> None:
        """Reload guardian rules and refresh guarded/denied tool sets."""
        for g in self._guardians:
            if hasattr(g, "reload"):
                g.reload()
        self._reload_tool_sets()

    def is_denied(self, tool_name: str) -> bool:
        """``True`` when *tool_name* is unconditionally denied."""
        return tool_name in self._denied_tools

    def should_auto_deny_result(self, result: ToolGuardResult | None) -> bool:
        """``True`` when guard findings hit any configured auto-deny rule."""
        if (
            result is None
            or not result.findings
            or not self._auto_denied_rules
        ):
            return False
        return any(
            finding.rule_id in self._auto_denied_rules
            for finding in result.findings
        )

    def is_guarded(self, tool_name: str) -> bool:
        """``True`` when *tool_name* falls within the guard scope."""
        if self._guarded_tools is None:
            return True
        return tool_name in self._guarded_tools

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        only_always_run: bool = False,
    ) -> ToolGuardResult | None:
        """Guard a tool call's parameters.

        Parameters
        ----------
        tool_name:
            Name of the tool being called.
        params:
            Keyword arguments that will be passed to the tool function.
        only_always_run:
            When ``True``, only guardians with ``always_run=True`` are
            executed.  Used for tools outside the guarded scope that
            still need path-level checks.

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

        guardians = (
            [g for g in self._guardians if g.always_run]
            if only_always_run
            else self._guardians
        )

        for guardian in guardians:
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
                    {"name": guardian.name, "error": str(exc)},
                )

        result.guard_duration_seconds = time.monotonic() - t0
        return result


_engine_instance: ToolGuardEngine | None = None


def get_guard_engine() -> ToolGuardEngine:
    """Return a lazily-initialised :class:`ToolGuardEngine` singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ToolGuardEngine()
    return _engine_instance
