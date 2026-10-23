# -*- coding: utf-8 -*-
"""Run standard Channel contracts outside repository-wide SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_channel_extension_contract(tmp_path):
    run_isolated_pytest(
        "extension_contract_suite.py",
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        timeout=120,
    )
