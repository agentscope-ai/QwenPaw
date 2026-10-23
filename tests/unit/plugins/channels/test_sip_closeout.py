# -*- coding: utf-8 -*-
"""SIP native, raw text and formal lifecycle normal isolated entries."""

import pytest

from tests.sip_isolated import run_sip_suite


@pytest.mark.parametrize(
    "suite",
    [
        "sip_native_suite.py",
        "sip_completed_text_suite.py",
        "sip_process_suite.py",
        "sip_formal_closeout_suite.py",
        "sip_lifecycle_closeout_suite.py",
        "sip_registrar_socket_suite.py",
    ],
)
def test_sip_private_and_formal(suite, tmp_path):
    run_sip_suite(suite, tmp_path)
