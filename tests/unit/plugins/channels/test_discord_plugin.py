# -*- coding: utf-8 -*-
"""Run Discord contracts outside repository-wide SDK mocks."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "discord_legacy_suite.py",
        "discord_suite.py",
        "discord_media_suite.py",
        "discord_stream_suite.py",
        "discord_platform_suite.py",
        "discord_reliability_suite.py",
        "discord_actual_agent_suite.py",
    ],
)
def test_discord_plugin(tmp_path, suite_name):
    run_isolated_pytest(
        suite_name,
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        timeout=120,
    )
