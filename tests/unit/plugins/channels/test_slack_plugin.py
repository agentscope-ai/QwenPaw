# -*- coding: utf-8 -*-
"""Run Slack contracts outside repository-wide SDK mocks."""

import pytest

from tests.isolated_pytest import run_isolated_pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "slack_suite.py",
        "slack_route_suite.py",
        "slack_legacy_suite.py",
        "slack_config_suite.py",
        "slack_policy_suite.py",
        "slack_platform_suite.py",
        "slack_stream_suite.py",
        "slack_media_suite.py",
        "slack_reliability_suite.py",
        "slack_actual_agent_suite.py",
    ],
)
def test_slack_plugin(tmp_path, suite_name):
    run_isolated_pytest(
        suite_name,
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=120,
    )
