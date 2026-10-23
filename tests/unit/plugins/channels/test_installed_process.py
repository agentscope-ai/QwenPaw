# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring,duplicate-code
"""Installed candidates run in isolated hosts with actual installed SDKs."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize("channel", ["feishu", "dingtalk"])
def test_installed_channel_process(channel, tmp_path):
    run_isolated_pytest(
        "installation_process_suite.py",
        env={
            "QWENPAW_B5_CHANNEL": channel,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
        },
        timeout=60,
    )
