# -*- coding: utf-8 -*-
"""Run independent C5 transaction evidence without global SDK substitutions."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize("channel", ["feishu", "dingtalk"])
def test_c5_transactions(tmp_path, channel):
    run_isolated_pytest(
        "c5_transactions_suite.py",
        env={
            "QWENPAW_C5_CHANNEL": channel,
            "QWENPAW_WORKING_DIR": str(tmp_path / channel),
        },
        timeout=180,
    )
