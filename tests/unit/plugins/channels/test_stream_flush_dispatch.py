# -*- coding: utf-8 -*-
"""Run stream ownership regressions outside global platform SDK mocks."""

import pytest

from tests.isolated_pytest import run_mapped_suite


@pytest.mark.parametrize(
    "suite",
    ["stream_flush_dispatch_suite.py", "stream_flush_lifecycle_suite.py"],
)
def test_stream_flush_dispatch(tmp_path, suite):
    run_mapped_suite(suite, tmp_path)
