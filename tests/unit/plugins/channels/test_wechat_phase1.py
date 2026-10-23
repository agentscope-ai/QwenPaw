# -*- coding: utf-8 -*-
"""Bounded independent phase1 merge responsibility groups."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "suite_name,selection",
    [
        (
            "wechat_merge_runtime_suite.py",
            "old_owner or capability_is_required or same_recipient or "
            "media_flushes or proactive_scope or unknown_flush or "
            "consume_error or unknown_immediate",
        ),
        (
            "wechat_merge_runtime_suite.py",
            "aggregate_budget or adjacent_timer or cancel_discards or "
            "smaller_actual or stop_settles",
        ),
        (
            "wechat_merge_runtime_suite.py",
            "opted_in_text or stream_operation or structured_approval or "
            "actual_agent_completion or definite_sdk or "
            "repeated_cancellation or capability_without",
        ),
        ("wechat_merge_wire_suite.py", ""),
        ("wechat_merge_capacity_suite.py", ""),
        ("wechat_connection_contract_suite.py", ""),
        ("wechat_connection_runtime_suite.py", ""),
        ("wechat_connection_selection_suite.py", ""),
    ],
)
def test_wechat_phase1_contracts(tmp_path, suite_name, selection):
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins"
        / suite_name
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
            str(suite.parent),
            str(suite),
            "-k",
            selection,
            "-q",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
