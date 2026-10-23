# -*- coding: utf-8 -*-
"""Official QQ inherited and actual Agent/native session contracts."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "qq_closeout_formal_suite.py",
        "qq_closeout_lifecycle_suite.py",
        "qq_retired_helpers_suite.py",
    ],
)
def test_qq_official_closeout_groups(tmp_path, suite_name):
    run_isolated_pytest(
        suite_name,
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
