# -*- coding: utf-8 -*-
"""Voice responsibilities on actual private Driver and official shared host."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "voice_closeout_formal_suite.py",
        "voice_closeout_unavailable_suite.py",
        "voice_closeout_http_controls_suite.py",
        "voice_raw_completed_host_suite.py",
        "voice_unknown_identity_oracle_suite.py",
    ],
)
def test_voice_migrated_responsibilities(tmp_path, suite_name):
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
