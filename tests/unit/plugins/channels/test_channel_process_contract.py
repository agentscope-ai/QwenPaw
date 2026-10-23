# -*- coding: utf-8 -*-
"""Run B1 shared contracts outside tests/conftest.py SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_channel_process_contract(tmp_path):
    """A new interpreter collects the import guard before production APIs."""
    run_isolated_pytest(
        "process_contract_suite.py",
        env={"QWENPAW_WORKING_DIR": str(tmp_path / "qwenpaw-b1")},
        timeout=60,
    )
