# -*- coding: utf-8 -*-
"""Normal bounded entrypoints for independently owned W2 responsibility tests."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "suite,selection",
    [
        ("wechat_qrcode_scope_suite.py", ""),
        ("wechat_w2_scope_suite.py", ""),
        ("wechat_w2_authclaims_suite.py", ""),
        ("wechat_w2_auth_domain_suite.py", ""),
        ("wechat_w2_symlink_context_suite.py", ""),
        ("wechat_w2_management_lease_suite.py", ""),
        ("wechat_w2_auth_reference_suite.py", ""),
        ("wechat_w2_admission_suite.py", ""),
        ("wechat_w2_g3_retained_suite.py", ""),
        ("wechat_w2_claim_stop_suite.py", ""),
        (
            "wechat_w2_session_suite.py",
            "real_fetch_poll or physical_slot_overlap or cancelled_poll_waiter or last_waiter",
        ),
        (
            "wechat_w2_session_suite.py",
            "delete_revokes or hard_ttl or authorize_save or owner_and_stop or "
            "confirmed_cancel_drops or terminal_cache",
        ),
        (
            "wechat_w2_session_suite.py",
            "authority_change or unknown_fetch or revoke_workspace or loader_disable",
        ),
    ],
)
def test_wechat_w2_responsibility_group(tmp_path, suite, selection):
    path = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins"
        / suite
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "--confcutdir",
            str(path.parent),
            str(path),
            "-k",
            selection,
            "-q",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
