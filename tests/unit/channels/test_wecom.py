# -*- coding: utf-8 -*-
"""Retained WeCom duties on the isolated official plugin boundaries.

This entry never imports a retired Core channel.
"""

import pytest

from tests.wecom_isolated import run_wecom_suite


@pytest.mark.parametrize(
    "suite",
    [
        "wecom_config_target_closeout_suite.py",
        "wecom_host_legacy_edges_suite.py",
        "wecom_native_suite.py",
        "wecom_native_bounds_suite.py",
        "wecom_cancel_unknown_suite.py",
        "wecom_media_closeout_suite.py",
    ],
)
def test_wecom_private_business_contracts(suite, tmp_path):
    run_wecom_suite(suite, tmp_path)
