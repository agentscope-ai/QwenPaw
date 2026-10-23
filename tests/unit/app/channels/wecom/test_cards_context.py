# -*- coding: utf-8 -*-
"""Retained WeCom duties on the isolated official plugin boundaries.

This entry never imports a retired Core channel.
"""

import pytest

from tests.wecom_isolated import run_wecom_suite


@pytest.mark.parametrize(
    "suite",
    [
        "wecom_context_pure_suite.py",
        "wecom_stream_detail_suite.py",
        "wecom_keepalive_ownership_suite.py",
    ],
)
def test_wecom_context_and_owned_stream_contracts(suite, tmp_path):
    run_wecom_suite(suite, tmp_path)
