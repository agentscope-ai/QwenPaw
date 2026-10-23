# -*- coding: utf-8 -*-
"""Private native and public order controls without duplicate pure tests."""

from tests.onebot_isolated import run_onebot_suite


def test_onebot_private_contracts(tmp_path):
    run_onebot_suite(
        ["onebot_native_suite.py", "onebot_delivery_suite.py"],
        tmp_path,
    )


def test_onebot_actual_host_order_contract(tmp_path):
    run_onebot_suite("onebot_host_order_suite.py", tmp_path)


def test_onebot_ordered_policy_controls(tmp_path):
    run_onebot_suite("onebot_ordered_controls_suite.py", tmp_path)
