# -*- coding: utf-8 -*-
"""Security boundary for raw managed-terminal input capability."""

from __future__ import annotations

import uuid
from typing import Any

from ..models import GuardFinding, GuardSeverity, GuardThreatCategory
from . import BaseToolGuardian


class TerminalCapabilityGuardian(BaseToolGuardian):
    """Require approval before a session accepts immediate raw input."""

    def __init__(self) -> None:
        super().__init__(name="terminal_capability_guardian", always_run=True)

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        if (
            tool_name != "execute_shell_command"
            or str(params.get("input_mode", "line")).lower() != "raw"
        ):
            return []
        return [
            GuardFinding(
                id=f"GUARD-{uuid.uuid4().hex}",
                rule_id="TERMINAL_RAW_INPUT_CAPABILITY",
                category=GuardThreatCategory.CODE_EXECUTION,
                severity=GuardSeverity.MEDIUM,
                title="Raw terminal input capability",
                description=(
                    "This managed session will deliver approved keystrokes "
                    "immediately. Input is not accumulated into complete "
                    "shell lines, so later fragments may form arbitrary "
                    "interactive commands."
                ),
                tool_name=tool_name,
                param_name="input_mode",
                matched_value="raw",
                remediation=(
                    "Approve only when the requested program needs single "
                    "keys, TUI controls, or control-character input."
                ),
                guardian=self.name,
                metadata={"capability": "terminal_raw_input"},
            ),
        ]
