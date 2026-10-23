# -*- coding: utf-8 -*-
"""Canonical isolated entry points for existing channel and execution regressions.

Each suite retains its own fixtures and assertions in a fresh subprocess.
"""

from pathlib import Path

import pytest

from tests.isolated_pytest import run_isolated_pytest

ROOT = Path(__file__).resolve().parents[4]

# Explicit repository paths and budgets keep each existing suite independently
# selectable; generic execution suites use their own fixture directory.
SUITES = [
    ("tests/fixtures/channel_plugins/anonymous_identity_suite.py", 180),
    ("tests/fixtures/channel_plugins/azure_bot_capture_suite.py", 180),
    ("tests/fixtures/channel_plugins/azure_bot_formal_aad_suite.py", 180),
    ("tests/fixtures/channel_plugins/azure_bot_formal_agent_suite.py", 180),
    (
        "tests/fixtures/channel_plugins/azure_bot_formal_lifecycle_suite.py",
        180,
    ),
    ("tests/fixtures/channel_plugins/azure_bot_identity_suite.py", 180),
    ("tests/fixtures/channel_plugins/azure_bot_legacy_auth_suite.py", 180),
    ("tests/fixtures/channel_plugins/azure_bot_legacy_refs_suite.py", 180),
    ("tests/fixtures/channel_plugins/azure_bot_media_closeout_suite.py", 180),
    ("tests/fixtures/channel_plugins/azure_bot_native_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3fd_dd_contract_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3fd_dd_lazy_controls_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3fd_dd_native_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3fd_dd_options_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3fd_dd_remaining_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3fd_dd_session_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3fd_dd_wechat_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3qq_native_roles_suite.py", 180),
    ("tests/fixtures/channel_plugins/g3qq_save_suite.py", 180),
    ("tests/fixtures/channel_plugins/g4_ingress_boundary_suite.py", 120),
    ("tests/fixtures/channel_plugins/g4_ingress_native_suite.py", 120),
    ("tests/fixtures/channel_plugins/g4_ingress_overlay_suite.py", 120),
    ("tests/fixtures/channel_plugins/g4_ingress_signature_suite.py", 120),
    (
        "tests/fixtures/channel_plugins/g4_ingress_ws_origin_probe_suite.py",
        120,
    ),
    (
        "tests/fixtures/channel_plugins/g4_shared_endpoint_boundary_suite.py",
        120,
    ),
    ("tests/fixtures/channel_plugins/g4_shared_endpoint_suite.py", 120),
    ("tests/fixtures/channel_plugins/official_g1_all_channels_suite.py", 180),
    ("tests/fixtures/channel_plugins/official_g1_azure_form_suite.py", 180),
    ("tests/fixtures/channel_plugins/official_g1_azure_save_suite.py", 180),
    ("tests/fixtures/channel_plugins/official_g1_context_suite.py", 180),
    (
        "tests/fixtures/channel_plugins/official_g1_readers_resources_suite.py",
        180,
    ),
    ("tests/fixtures/channel_plugins/raw_actor_capacity_suite.py", 180),
    ("tests/fixtures/channel_plugins/raw_actor_contract_suite.py", 180),
    ("tests/fixtures/channel_plugins/raw_actor_host_suite.py", 180),
    ("tests/fixtures/channel_plugins/semantic_event_failure_suite.py", 180),
    ("tests/fixtures/channel_plugins/semantic_event_host_suite.py", 180),
    ("tests/fixtures/channel_plugins/trusted_context_channel_suite.py", 120),
    ("tests/fixtures/channel_plugins/trusted_context_policy_suite.py", 120),
    (
        "tests/fixtures/channel_plugins/workspace_channel_admission_suite.py",
        120,
    ),
    ("tests/fixtures/plugin_execution/payload_classification_suite.py", 120),
    ("tests/fixtures/plugin_execution/payload_io_lifetime_suite.py", 120),
    ("tests/fixtures/plugin_execution/payload_limits_suite.py", 120),
    ("tests/fixtures/plugin_execution/payload_process_suite.py", 120),
    ("tests/fixtures/plugin_execution/payload_publication_suite.py", 120),
    ("tests/fixtures/plugin_execution/payload_store_suite.py", 120),
    ("tests/fixtures/plugin_execution/trusted_context_boundary_suite.py", 120),
    ("tests/fixtures/plugin_execution/trusted_context_suite.py", 120),
    (
        "tests/fixtures/channel_plugins/execution_transitive_extras_suite.py",
        120,
    ),
    (
        "tests/fixtures/channel_plugins/g4_endpoint_authority_unit_suite.py",
        120,
    ),
    ("tests/fixtures/channel_plugins/g4_forwarding_contract_suite.py", 120),
    (
        "tests/fixtures/channel_plugins/imessage_numeric_descriptor_suite.py",
        120,
    ),
    ("tests/fixtures/channel_plugins/official_g1_form_metadata_suite.py", 180),
    (
        "tests/fixtures/channel_plugins/official_g1_normalizer_edges_suite.py",
        180,
    ),
    ("tests/fixtures/channel_plugins/official_g1_normalizer_suite.py", 180),
]


@pytest.mark.parametrize("suite, timeout", SUITES)
def test_existing_core_regression_suite(suite, timeout, tmp_path):
    target = ROOT / suite
    for name in ("home", "work", "secret", "backup", "tmp"):
        (tmp_path / name).mkdir()

    run_isolated_pytest(
        target,
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "TMP": str(tmp_path / "tmp"),
            "TEMP": str(tmp_path / "tmp"),
            "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        timeout=timeout,
        asyncio_plugin=True,
        short_traceback=True,
        confcutdir=target.parent,
    )
