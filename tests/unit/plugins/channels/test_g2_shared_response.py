# -*- coding: utf-8 -*-
"""Run G2 contracts outside repository-wide SDK mocks."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "g2_shared_response_suite.py",
        "g2_environment_suite.py",
        "response_receipt_archive_suite.py",
    ],
)
def test_g2_shared_response(tmp_path, suite_name):
    run_isolated_pytest(
        suite_name,
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        timeout=120,
    )
