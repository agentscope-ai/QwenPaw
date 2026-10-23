# -*- coding: utf-8 -*-
"""Current owners for all66 preserved legacy XiaoYi responsibilities.

Original bytes/oracles and approved lifecycle changes remain in the frozen
XiaoYi oracle maps. Private, formal-host and generic semantic cases run in
separate interpreters; no old BaseChannel compatibility implementation.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest

TARGETS = [
    "xiaoyi_pure_suite.py",
    "xiaoyi_native_suite.py",
    "xiaoyi_remaining_native_suite.py",
    "xiaoyi_closeout_contract_suite.py",
    (
        "xiaoyi_closeout_suite.py::test_formal_zip_loader_worker_queue_"
        "runs_actual_agent_and_finishes_native_task"
    ),
    (
        "xiaoyi_closeout_suite.py::test_legacy_from_env_values_and_"
        "defaults_retarget_to_public_reader"
    ),
    (
        "xiaoyi_closeout_suite.py::test_doctor_public_entry_keeps_both_"
        "hosts_and_timeout_without_legacy_import"
    ),
    (
        "xiaoyi_closeout_suite.py::test_formal_two_workspaces_same_"
        "platform_account_isolate_workers_and_old_identity"
    ),
    (
        "xiaoyi_closeout_suite.py::test_formal_enabled_candidate_failure_"
        "rolls_back_source_and_actual_agent_delivery"
    ),
    (
        "xiaoyi_closeout_suite.py::test_original_proactive_target_native_"
        "destination_survives_generic_handle"
    ),
    (
        "xiaoyi_closeout_suite.py::test_formal_acl_rejects_before_agent_"
        "but_allowed_actor_reaches_real_queue"
    ),
    (
        "xiaoyi_closeout_suite.py::test_formal_uninstall_keeps_user_"
        "config_data_and_passive_public_api_without_worker"
    ),
    (
        "xiaoyi_closeout_suite.py::test_raw_legacy_allowlist_fixture_"
        "projection_diagnostic"
    ),
    (
        "xiaoyi_closeout_suite.py::test_missing_task_api_strict_but_"
        "ordinary_completed_response_tolerant"
    ),
    (
        "xiaoyi_closeout_suite.py::test_request_meta_session_or_user_"
        "fallback_reaches_exact_native_target"
    ),
    (
        "xiaoyi_last_oracles_suite.py::test_unique_backup_inbound_retains_"
        "backup_response_route"
    ),
    (
        "xiaoyi_last_oracles_suite.py::test_formal_native_session_"
        "metadata_prefix_sender_fallback_and_enabled_get"
    ),
    (
        "xiaoyi_last_oracles_suite.py::test_lifecycle_fences_api_media_"
        "and_ordinary_with_zero_native_effects"
    ),
    (
        "xiaoyi_last_oracles_suite.py::test_actual_host_dual_socket_"
        "refusal_strict_api_tolerant_ordinary"
    ),
    (
        "xiaoyi_open_failure_boundary_suite.py::test_generic_safe_target_"
        "failure_is_truthful_ordinary_failure_but_api_stays_rpc_error"
    ),
    (
        "xiaoyi_open_failure_boundary_suite.py::test_non_optin_uncertain_"
        "internal_or_malformed_open_failure_never_becomes_success"
    ),
    (
        "xiaoyi_open_failure_boundary_suite.py::test_approval_target_"
        "failure_never_uses_ordinary_tolerance"
    ),
    (
        "xiaoyi_open_failure_boundary_suite.py::test_cancel_actual_"
        "pending_open_preserves_cancellation_and_no_effect"
    ),
    (
        "xiaoyi_open_failure_boundary_suite.py::test_real_disable_retires_"
        "pending_open_without_tolerated_success"
    ),
    (
        "semantic_event_pure_suite.py::test_original_empty_content_"
        "retains_rendered_fallback"
    ),
    (
        "semantic_event_pure_suite.py::test_original_hidden_tool_results_"
        "keep_media_without_placeholder"
    ),
    (
        "semantic_event_pure_suite.py::test_original_scroll_headline_"
        "variants_do_not_escape"
    ),
    (
        "semantic_event_pure_suite.py::test_original_text_extraction_"
        "keeps_message_provenance"
    ),
]


@pytest.mark.parametrize("target", TARGETS)
def test_xiaoyi_current_business_oracles(tmp_path, target):
    directory = (
        Path(__file__).resolve().parents[2] / "fixtures/channel_plugins"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "--confcutdir",
            str(directory),
            str(directory / target),
            "-q",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
