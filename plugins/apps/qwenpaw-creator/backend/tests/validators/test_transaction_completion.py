# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace

from services.validators.base import ValidationIssue, ValidationReport
from services.validators.transaction import (
    CompletionSnapshot,
    validate_completion,
)


VALID = CompletionSnapshot(
    transaction_id="tx-1",
    status="ACTIVE",
    current_working_head="head-4",
    expected_working_head="head-4",
    last_consumed_message_seq=12,
    user_message_high_water=12,
    queued_user_message_count=0,
    pending_outbox_count=0,
    specialist_run_statuses=("SUCCEEDED", "BLOCKED"),
    task_statuses=("SUCCEEDED", "QUARANTINED"),
    unimported_result_count=0,
    active_lease_count=0,
    requested_consistency_report_id="report-1",
    current_consistency_report_id="report-1",
    consistency_report_working_head="head-4",
    consistency_report_marker="SUCCESS",
    domain_reports=(ValidationReport(),),
    journal_matches_tree=True,
    seal_cas_unchanged=True,
)


def test_all_atomic_completion_checks_pass_together() -> None:
    assert validate_completion(VALID).valid


def test_completion_transaction_checks_are_disabled() -> None:
    broken = replace(
        VALID,
        current_working_head="head-5",
        last_consumed_message_seq=10,
        queued_user_message_count=1,
        pending_outbox_count=1,
        specialist_run_statuses=("RUNNING_MODEL",),
        task_statuses=("RUNNING",),
        unimported_result_count=1,
        active_lease_count=1,
        consistency_report_working_head="head-4",
        domain_reports=(
            ValidationReport(
                (ValidationIssue("R2V_STORYBOARD_REQUIRED", "missing"),),
            ),
        ),
        journal_matches_tree=False,
        seal_cas_unchanged=False,
    )
    assert validate_completion(broken).valid
