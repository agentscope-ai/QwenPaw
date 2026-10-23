# -*- coding: utf-8 -*-
"""Isolated entry for native WeChat group admission regressions."""

from tests.isolated_pytest import run_isolated_pytest


def test_wechat_group_identity_contract(tmp_path):
    run_isolated_pytest(
        "wechat_group_identity_suite.py",
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
