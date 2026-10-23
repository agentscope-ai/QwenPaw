# -*- coding: utf-8 -*-
"""Run independent C6 static host contracts outside global SDK mocks."""

from tests.isolated_pytest import run_isolated_pytest


def test_c6_static_host_contracts(tmp_path):
    run_isolated_pytest(
        "c6_catalog_suite.py",
        env={"QWENPAW_WORKING_DIR": str(tmp_path / "host")},
        timeout=45,
    )
