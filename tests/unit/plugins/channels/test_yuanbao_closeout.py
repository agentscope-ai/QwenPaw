# -*- coding: utf-8 -*-
"""Real released Yuanbao ZIP/Core/Agent and lifecycle regression entries."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "node",
    [
        "test_formal_yuanbao_zip_actual_agent_session_target_map_and_stop",
        "test_real_legacy_map_lock_does_not_block_worker_event_loop",
        "test_stop_cancels_pending_map_lock_before_holder_releases",
        "test_formal_two_workspaces_disable_and_enabled_activation_rollback",
        "test_formal_group_session_agent_reply_and_kickout",
    ],
)
def test_yuanbao_formal_closeout(tmp_path, node):
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/yuanbao_closeout_suite.py"
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
            str(suite) + "::" + node,
            "-q",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
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
