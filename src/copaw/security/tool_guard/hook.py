# -*- coding: utf-8 -*-
"""Pre-acting hook that guards sensitive tool parameters before execution.

This hook integrates with AgentScope's ``pre_acting`` hook point to
scan selected high-risk tool calls before the tool is invoked.  It
**never blocks** the call – it only logs warnings when suspicious
patterns are detected.

Usage::

    from copaw.security.tool_guard.hook import ToolGuardHook

    hook = ToolGuardHook()
    agent.register_instance_hook(
        hook_type="pre_acting",
        hook_name="tool_guard",
        hook=hook,
    )
"""
from __future__ import annotations

import logging
import os
import json
from pathlib import Path
from typing import Any, Iterable

from copaw.constant import CONFIG_FILE, WORKING_DIR

from .engine import get_guard_engine

logger = logging.getLogger(__name__)

_DEFAULT_GUARDED_TOOLS = frozenset(
    {
        "execute_shell_command",
        "execute_python_code",
        "browser_use",
        "desktop_screenshot",
        "read_file",
        "write_file",
        "edit_file",
        "append_file",
        "view_text_file",
        "write_text_file",
        "send_file_to_user",
    }
)

_CONFIG_NOT_SET = object()


def _parse_guarded_tokens(tokens: Iterable[str]) -> set[str] | None:
    """Parse guarded tool tokens into scope set.

    ``None`` means guard all tools.
    """
    normalized = {item.strip() for item in tokens if item and item.strip()}
    if not normalized:
        return set()

    lowered = {item.lower() for item in normalized}
    if "*" in lowered or "all" in lowered:
        return None
    if lowered.issubset({"none", "off", "false", "0"}):
        return set()

    return normalized


def _load_guarded_tools_from_config_file() -> object | set[str] | None:
    """Load guarded tools from working-dir ``config.json``.

    Supported keys (in priority order):
    1) ``security.tool_guard.guarded_tools``
    2) ``agents.running.tool_guard_tools`` (compat)

    Returns
    -------
    object | set[str] | None
        Parsed scope set / ``None`` (guard all) when configured;
        ``_CONFIG_NOT_SET`` when no usable key exists.
    """
    config_path = Path(WORKING_DIR) / CONFIG_FILE
    if not config_path.is_file():
        return _CONFIG_NOT_SET

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return _CONFIG_NOT_SET

    if not isinstance(data, dict):
        return _CONFIG_NOT_SET

    security = data.get("security")
    if isinstance(security, dict):
        tool_guard = security.get("tool_guard")
        if isinstance(tool_guard, dict):
            scoped_tools = tool_guard.get("guarded_tools")
            if isinstance(scoped_tools, list):
                parsed = _parse_guarded_tokens(
                    [str(item) for item in scoped_tools],
                )
                return parsed

    agents = data.get("agents")
    if isinstance(agents, dict):
        running = agents.get("running")
        if isinstance(running, dict):
            scoped_tools = running.get("tool_guard_tools")
            if isinstance(scoped_tools, list):
                parsed = _parse_guarded_tokens(
                    [str(item) for item in scoped_tools],
                )
                return parsed

    return _CONFIG_NOT_SET


def _resolve_guarded_tools(
    user_defined: set[str] | list[str] | tuple[str, ...] | None = None,
) -> set[str] | None:
    """Resolve guarded tools set.

    Priority:
    1) constructor-provided ``user_defined``
    2) ``COPAW_TOOL_GUARD_TOOLS`` env var
    3) built-in high-risk default set

    Returns
    -------
    set[str] | None
        ``None`` means guard all tools.
    """
    if user_defined is not None:
        return _parse_guarded_tokens(user_defined)

    raw = os.environ.get("COPAW_TOOL_GUARD_TOOLS")
    if raw is None:
        config_guarded_tools = _load_guarded_tools_from_config_file()
        if config_guarded_tools is not _CONFIG_NOT_SET:
            return config_guarded_tools
        return set(_DEFAULT_GUARDED_TOOLS)

    normalized = raw.strip().lower()
    if normalized in {"*", "all"}:
        return None
    if normalized in {"", "none", "off", "false", "0"}:
        return set()

    return _parse_guarded_tokens(raw.split(","))


class ToolGuardHook:
    """AgentScope ``pre_acting`` hook that guards tool-call parameters.

    The hook inspects the :class:`ToolUseBlock` passed into ``_acting``
    and runs the :class:`ToolGuardEngine` against it.  Findings are
    logged as warnings – the tool call is **never** blocked.

    Parameters
    ----------
    engine:
        Explicit engine instance.  When *None* (the default), the
        module-level lazy singleton is used.
    """

    def __init__(
        self,
        engine=None,
        *,
        guarded_tools: set[str] | None = None,
    ) -> None:
        self._engine = engine
        self._guarded_tools = _resolve_guarded_tools(guarded_tools)

    @property
    def engine(self):
        if self._engine is None:
            return get_guard_engine()
        return self._engine

    def _should_guard_tool(self, tool_name: str) -> bool:
        if self._guarded_tools is None:
            return True
        return tool_name in self._guarded_tools

    # ------------------------------------------------------------------
    # Hook callable  (async to match AgentScope's convention)
    # ------------------------------------------------------------------

    async def __call__(
        self,
        agent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Guard the tool call described by *kwargs* before execution.

        Parameters
        ----------
        agent:
            The agent instance (unused, but required by hook interface).
        kwargs:
            Keyword arguments to ``_acting``.  Expected to contain a
            ``tool_call`` key whose value is a ``ToolUseBlock`` dict
            with ``name`` and ``input`` fields.

        Returns
        -------
        None
            The hook never modifies kwargs – it only logs warnings.
        """
        try:
            tool_call = kwargs.get("tool_call")
            if tool_call is None:
                return None

            # ToolUseBlock is a TypedDict / dict with "name", "input", etc.
            tool_name: str = tool_call.get("name", "")
            tool_input: dict[str, Any] = tool_call.get("input", {})

            if not tool_name:
                return None

            if not self._should_guard_tool(tool_name):
                return None

            result = self.engine.guard(tool_name, tool_input)
            if result is None:
                # Guarding disabled
                return None

            if result.findings:
                _log_findings(tool_name, result)

        except Exception as exc:  # pragma: no cover
            # Never let guard failures disrupt the agent
            logger.debug(
                "Tool guard hook encountered an error (non-blocking): %s", exc
            )

        # Always return None – never modify kwargs, never block
        return None


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _log_findings(tool_name: str, result) -> None:
    """Emit structured warning logs for each finding."""
    from .models import GuardSeverity

    for finding in result.findings:
        # Choose log level based on severity
        if finding.severity in (GuardSeverity.CRITICAL, GuardSeverity.HIGH):
            log_fn = logger.warning
        else:
            log_fn = logger.info

        log_fn(
            "[TOOL GUARD] %s | tool=%s param=%s rule=%s | %s | matched=%r",
            finding.severity.value,
            tool_name,
            finding.param_name or "*",
            finding.rule_id,
            finding.description,
            finding.matched_value,
        )

    # Summary line
    logger.warning(
        "[TOOL GUARD] Summary for tool '%s': %d finding(s), "
        "max_severity=%s, duration=%.3fs. "
        "Execution NOT blocked.",
        tool_name,
        result.findings_count,
        result.max_severity.value,
        result.guard_duration_seconds,
    )
