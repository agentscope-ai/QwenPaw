# -*- coding: utf-8 -*-
"""Run outbound media regressions without repository-wide SDK replacements."""

from tests.isolated_pytest import run_mapped_suite


def test_outbound_media_snapshot(tmp_path):
    run_mapped_suite("outbound_media_snapshot_suite.py", tmp_path)
