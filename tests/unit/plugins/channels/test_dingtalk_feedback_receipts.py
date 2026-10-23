# -*- coding: utf-8 -*-
"""Run DingTalk receipt regression coverage without global SDK replacements."""

from tests.isolated_pytest import run_mapped_suite


def test_dingtalk_feedback_receipts(tmp_path):
    run_mapped_suite("feedback_receipts_dingtalk_suite.py", tmp_path)
