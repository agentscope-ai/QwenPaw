# -*- coding: utf-8 -*-
"""Confirmed Health Check doctor fix execution."""
from __future__ import annotations

from pathlib import Path

from qwenpaw.cli.doctor_fix_runner import run_doctor_fix
from qwenpaw.security.integrity_protection import HealthCheckFixResult

from .constants import CONSOLE_FIX_IDS


def run_confirmed_health_fix(
    *,
    fix_id: str,
    working_dir: Path | None = None,
    selected_repair: str | None = None,
    confirmation_phrase: str | None = None,
    expected_confirmation_phrase: str | None = None,
) -> HealthCheckFixResult:
    """Run one doctor fix after the console user confirmed the action."""

    del confirmation_phrase, expected_confirmation_phrase  # legacy API compat

    repair_label = selected_repair or f"repair_{fix_id}"
    normalized_fix_id = (fix_id or "").strip()
    if not normalized_fix_id or normalized_fix_id not in CONSOLE_FIX_IDS:
        return HealthCheckFixResult(
            confirmed=False,
            selected_repair=repair_label,
            fix_id=normalized_fix_id,
            executed=False,
            exit_code=1,
            output=(f"fix_id not allowed for console repair: {normalized_fix_id!r}",),
        )

    output: list[str] = []

    def _echo(message: str) -> None:
        output.append(message)

    code = run_doctor_fix(
        dry_run=False,
        yes=True,
        only=normalized_fix_id,
        no_backup=False,
        backup_dir=None,
        working_dir=working_dir,
        echo=_echo,
        echo_err=_echo,
        confirm_fn=lambda _message: True,
        argv=["qwenpaw", "doctor", "fix", "--only", normalized_fix_id, "--yes"],
        non_interactive=True,
    )
    return HealthCheckFixResult(
        confirmed=True,
        selected_repair=repair_label,
        fix_id=normalized_fix_id,
        executed=True,
        exit_code=code,
        output=tuple(output),
    )
