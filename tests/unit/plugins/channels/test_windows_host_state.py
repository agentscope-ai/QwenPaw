# -*- coding: utf-8 -*-
"""Run host-state filesystem regressions outside repository SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_windows_host_state_filesystem_contract(tmp_path):
    run_isolated_pytest(
        "windows_host_state_suite.py",
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=120,
    )
