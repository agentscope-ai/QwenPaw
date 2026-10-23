# -*- coding: utf-8 -*-
"""Retained OneBot responsibilities at the actual v2 plugin boundary.
"""

import pytest

from tests.onebot_isolated import run_onebot_suite


@pytest.mark.parametrize("suite", ["onebot_legacy_media_suite.py"])
def test_onebot_legacy_media(suite, tmp_path):
    run_onebot_suite(suite, tmp_path)
