# -*- coding: utf-8 -*-
"""Retained WeCom duties on the isolated official plugin boundaries.

This entry never imports a retired Core channel.
"""

import pytest

from tests.wecom_isolated import run_wecom_suite


@pytest.mark.parametrize(
    "suite",
    [
        "wecom_cards_pure_suite.py",
        "wecom_card_effect_closeout_suite.py",
        "wecom_card_handoff_suite.py",
        "wecom_card_final_edges_suite.py",
    ],
)
def test_wecom_pure_and_typed_card_contracts(suite, tmp_path):
    run_wecom_suite(suite, tmp_path)
