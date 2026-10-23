# -*- coding: utf-8 -*-
"""Run host-state ownership tests without repository-wide SDK replacements."""

from tests.isolated_pytest import run_mapped_suite


def test_host_state_handoff(tmp_path):
    run_mapped_suite("host_state_handoff_suite.py", tmp_path)
