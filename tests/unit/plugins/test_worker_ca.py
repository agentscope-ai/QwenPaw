# -*- coding: utf-8 -*-
"""Collect real TLS workers without repository-wide platform SDK mocks."""

from tests.isolated_pytest import run_mapped_suite


def test_worker_ca(tmp_path):
    run_mapped_suite("worker_ca_suite.py", tmp_path)
