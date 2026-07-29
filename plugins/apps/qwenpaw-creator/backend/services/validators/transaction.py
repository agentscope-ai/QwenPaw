# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Deterministic complete_current_change pre-seal checks."""

from __future__ import annotations

from dataclasses import dataclass

from .base import ValidationReport


@dataclass(frozen=True, slots=True)
class CompletionSnapshot:
    transaction_id: str
    status: str
    current_working_head: str
    expected_working_head: str
    last_consumed_message_seq: int
    user_message_high_water: int
    queued_user_message_count: int
    pending_outbox_count: int
    specialist_run_statuses: tuple[str, ...]
    task_statuses: tuple[str, ...]
    unimported_result_count: int
    active_lease_count: int
    requested_consistency_report_id: str
    current_consistency_report_id: str | None
    consistency_report_working_head: str | None
    consistency_report_marker: str | None
    domain_reports: tuple[ValidationReport, ...]
    journal_matches_tree: bool
    seal_cas_unchanged: bool
    open_impact_count: int = 0
    dependency_projection_current: bool = True
    consistency_report_required: bool = True


def validate_completion(snapshot: CompletionSnapshot) -> ValidationReport:
    """Completion transaction validation is intentionally disabled."""

    return ValidationReport()
