# -*- coding: utf-8 -*-
"""Retained SIP oracles through the isolated official plugin boundary.

Original bytes and assertions are indexed by sip-private-test-coverage.json.
"""

from tests.sip_isolated import run_sip_suite


def test_sip_legacy_memory_bounds(tmp_path):
    run_sip_suite("sip_legacy_memory_suite.py", tmp_path)
