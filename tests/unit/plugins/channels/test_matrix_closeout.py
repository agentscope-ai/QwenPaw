# -*- coding: utf-8 -*-
"""Matrix formal Agent, C6 and lifecycle mapped isolated normal entries."""
import pytest

from tests.matrix_isolated import run_matrix_suite


@pytest.mark.parametrize(
    "suite",
    [
        "matrix_formal_agent_suite.py",
        "matrix_formal_delivery_suite.py",
        "matrix_formal_remaining_suite.py",
        "matrix_formal_lifecycle_suite.py",
        "matrix_c6_capture_suite.py",
        "matrix_c6_password_restore_suite.py",
    ],
)
def test_matrix_formal_and_capture(suite, tmp_path):
    run_matrix_suite(suite, tmp_path)
