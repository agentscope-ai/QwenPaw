# -*- coding: utf-8 -*-
"""Run finite C6 runtime acceptance without global SDK substitutes."""

from tests.isolated_pytest import run_isolated_pytest


def test_c6_runtime_acceptance(tmp_path):
    run_isolated_pytest(
        "c6_runtime_suite.py",
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_RUNNING_IN_CONTAINER": "true",
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        timeout=90,
    )
