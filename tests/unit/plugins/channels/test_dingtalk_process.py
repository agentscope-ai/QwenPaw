# -*- coding: utf-8 -*-
"""Run B4 in an isolated parent without repository-wide SDK replacements."""

from tests.isolated_pytest import run_isolated_pytest


def test_dingtalk_actual_process(tmp_path):
    run_isolated_pytest(
        "dingtalk_process_suite.py",
        env={"QWENPAW_WORKING_DIR": str(tmp_path / "b4-host")},
        timeout=300,
    )
