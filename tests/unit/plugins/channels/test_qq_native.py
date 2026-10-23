# -*- coding: utf-8 -*-
"""Fixed-budget isolated entries for QQ native and static management tests."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    ["qq_native_driver_suite.py", "qq_management_native_suite.py"],
)
def test_qq_native_contracts(tmp_path, suite_name):
    run_isolated_pytest(
        suite_name,
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_RUNTIME_ID": "qq-native-test",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
