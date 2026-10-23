# -*- coding: utf-8 -*-
"""Collect public G3 DTO contracts before tests/conftest.py SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_channel_management_contract(tmp_path):
    run_isolated_pytest(
        "management_contract_suite.py",
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
