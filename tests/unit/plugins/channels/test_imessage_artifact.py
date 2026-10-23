# -*- coding: utf-8 -*-
"""Isolated entry for the two static iMessage payload contracts."""

from tests.isolated_pytest import run_isolated_pytest


def test_imessage_artifact_contracts(tmp_path):
    run_isolated_pytest(
        "imessage_artifact_suite.py",
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=60,
    )
