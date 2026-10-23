# -*- coding: utf-8 -*-
"""Keep outbound budget tests outside global platform SDK mocks."""

import pytest

from tests.isolated_pytest import run_mapped_suite


@pytest.mark.parametrize(
    "suite",
    [
        "send_budget_suite.py",
        "send_budget_contract_suite.py",
        "send_budget_retry_suite.py",
    ],
)
def test_send_budget(tmp_path, suite):
    run_mapped_suite(suite, tmp_path)
