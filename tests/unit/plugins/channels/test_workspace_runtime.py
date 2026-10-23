# -*- coding: utf-8 -*-
"""C2 runtime contracts use isolated hosts without global SDK mocks."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize("channel", ["feishu", "dingtalk"])
def test_real_workspace_channel_process(channel, tmp_path):
    run_isolated_pytest(
        "workspace_runtime_suite.py",
        env={
            "QWENPAW_C2_CHANNEL": channel,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
        },
        timeout=300,
    )


def test_workspace_queue_admission(tmp_path):
    run_isolated_pytest(
        "workspace_admission_suite.py",
        env={"QWENPAW_WORKING_DIR": str(tmp_path / "host")},
        timeout=45,
    )
