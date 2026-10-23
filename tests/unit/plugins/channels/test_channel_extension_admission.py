# -*- coding: utf-8 -*-
"""Keep G1/G2 tests outside global SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_channel_extension_admission(tmp_path):
    run_isolated_pytest(
        "extension_admission_suite.py",
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        timeout=120,
    )
