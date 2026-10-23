# -*- coding: utf-8 -*-
"""Run MQTT TLS path regressions without global platform SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_mqtt_tls_paths(tmp_path):
    run_isolated_pytest(
        "mqtt_tls_paths_suite.py",
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "state"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        timeout=60,
        asyncio_plugin=True,
    )
