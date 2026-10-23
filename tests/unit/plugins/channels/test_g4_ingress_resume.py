# -*- coding: utf-8 -*-
"""Run manager quiesce recovery through real workers and native ingress."""

from tests.isolated_pytest import run_isolated_pytest


def test_g4_ingress_resume(tmp_path):
    run_isolated_pytest(
        "g4_ingress_resume_suite.py",
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
