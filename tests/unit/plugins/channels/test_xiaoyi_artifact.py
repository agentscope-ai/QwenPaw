# -*- coding: utf-8 -*-
"""Bounded isolated wrapper for the private XiaoYi payload contracts."""

from tests.isolated_pytest import run_isolated_pytest


def test_xiaoyi_artifact_contracts(tmp_path):
    run_isolated_pytest(
        "xiaoyi_artifact_suite.py",
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_RUNTIME_ID": "xiaoyi-artifact-test",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
