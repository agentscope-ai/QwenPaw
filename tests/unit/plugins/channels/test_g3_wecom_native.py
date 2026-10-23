# -*- coding: utf-8 -*-
"""Run native WeCom management outside repository SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_wecom_native_management_and_scoped_save(tmp_path):
    run_isolated_pytest(
        "g3wecom_native_suite.py",
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
