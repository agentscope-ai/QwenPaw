# -*- coding: utf-8 -*-
"""Retained WeCom duties on the isolated official plugin boundaries.

This entry never imports a retired Core channel.
"""

import pytest

from tests.wecom_isolated import run_wecom_suite


@pytest.mark.parametrize(
    "suite",
    ["wecom_utils_suite.py"],
)
def test_wecom_table_and_image_contracts(suite, tmp_path):
    run_wecom_suite(suite, tmp_path)
