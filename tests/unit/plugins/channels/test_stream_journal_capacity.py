# -*- coding: utf-8 -*-
"""Run stream journal contracts outside repository-wide SDK mocks."""

import pytest

from tests.isolated_pytest import run_mapped_suite


@pytest.mark.parametrize(
    "suite",
    ["stream_journal_capacity_suite.py", "stream_preview_host_suite.py"],
)
def test_stream_journal_capacity(tmp_path, suite):
    run_mapped_suite(suite, tmp_path)
