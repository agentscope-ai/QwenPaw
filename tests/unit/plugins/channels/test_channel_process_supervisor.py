# -*- coding: utf-8 -*-
"""Run B2 subprocess tests outside repository-wide SDK replacements."""

from tests.isolated_pytest import run_isolated_pytest


def test_channel_process_supervisor(tmp_path):
    """Collect supervisor tests in a new isolated interpreter."""
    run_isolated_pytest(
        "process_supervisor_suite.py",
        env={"QWENPAW_WORKING_DIR": str(tmp_path / "qwenpaw-b2")},
        timeout=180,
    )
