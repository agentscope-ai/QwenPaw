# -*- coding: utf-8 -*-
"""Isolated WeCom stale stream retirement contracts."""

from tests.isolated_pytest import run_mapped_suites


def test_wecom_stale_stream_lifecycle(tmp_path):
    run_mapped_suites("wecom_stale_stream_suite.py", tmp_path)


def test_wecom_stale_stream_native(tmp_path):
    run_mapped_suites("wecom_stale_stream_native_suite.py", tmp_path)
