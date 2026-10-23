# -*- coding: utf-8 -*-
"""Run private Driver admission contracts outside global SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_real_private_drivers_keep_core_admission_counters(tmp_path):
    run_isolated_pytest(
        "shared_admission_counters_suite.py",
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=120,
        asyncio_plugin=True,
    )
