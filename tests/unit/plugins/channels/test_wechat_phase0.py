# -*- coding: utf-8 -*-
"""Bounded isolated responsibility groups for the WeChat phase0 contracts."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "wechat_artifact_suite.py",
        "wechat_text_merge_contract_suite.py",
        "wechat_client_suite.py",
    ],
)
def test_wechat_phase0_contracts(tmp_path, suite_name):
    run_isolated_pytest(
        suite_name,
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
