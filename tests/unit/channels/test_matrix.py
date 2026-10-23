# -*- coding: utf-8 -*-
"""Retained Matrix pure and ingress oracles on the private platform.

Original source hashes and per-responsibility evidence: matrix-validation-map.
Native SDK/lifecycle suites retain their existing test_matrix_private entry.
"""
import pytest

from tests.matrix_isolated import run_matrix_suite


@pytest.mark.parametrize(
    "suite",
    ["matrix_pure_oracle_suite.py", "matrix_legacy_ingress_suite.py"],
)
def test_matrix_retained_platform_oracles(suite, tmp_path):
    run_matrix_suite(suite, tmp_path)
