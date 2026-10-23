# -*- coding: utf-8 -*-
"""Retained QQ responsibilities on the private driver / official host.
Native transport and lifecycle proofs retain their existing normal entries.
"""
import pytest

from tests.qq_isolated import run_qq_suite


@pytest.mark.parametrize("suite", ["qq_closeout_media_suite.py"])
def test_qq_retained_responsibilities(suite, tmp_path):
    run_qq_suite(suite, tmp_path)
