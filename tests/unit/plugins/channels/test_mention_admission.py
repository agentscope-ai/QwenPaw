# -*- coding: utf-8 -*-
"""Run real WeCom SDK regressions outside the global SDK mocks."""

from tests.isolated_pytest import run_mapped_suite


def test_wecom_mention_admission(tmp_path):
    run_mapped_suite("mention_admission_suite.py", tmp_path)
