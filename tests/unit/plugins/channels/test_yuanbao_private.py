# -*- coding: utf-8 -*-
"""Isolated entries for current private Yuanbao business oracles."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "yuanbao_native_wire_suite.py",
        "yuanbao_native_state_suite.py",
        "yuanbao_native_driver_suite.py",
    ],
)
def test_yuanbao_private_contracts(tmp_path, suite_name):
    run_isolated_pytest(
        suite_name,
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_RUNTIME_ID": "yuanbao-private-test",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
