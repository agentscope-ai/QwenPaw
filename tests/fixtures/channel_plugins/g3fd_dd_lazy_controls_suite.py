"""Necessary lazy-import controls; existing successful business nodes not rerun."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from g3fd_dd_native_support import g3_host_import_boundary, native_qr

__all__ = ["g3_host_import_boundary", "native_qr"]
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_actual_loader_probe_and_manage_are_sdk_free(native_qr):
    native_qr.forbid_lark = True
    qr = await native_qr("feishu", "feishu")
    fetched = await qr.sessions.fetch(qr.scope, {})
    assert fetched.scan_url
    assert len(qr.requests) == 2
    assert all(row["sdk_guard_active"] for row in qr.requests)
    assert all(
        not row["lark_modules"] and not row["platform_imported"]
        for row in qr.requests
    )


@pytest.mark.parametrize("mode", ["import", "prepare"])
def test_actual_start_preserves_sdk_boundary_error_identity_and_cleanup(
    tmp_path, mode
):
    env = dict(os.environ)
    for name, directory in [
        ("HOME", "home"),
        ("QWENPAW_WORKING_DIR", "work"),
        ("QWENPAW_SECRET_DIR", "secret"),
        ("QWENPAW_BACKUP_DIR", "backup"),
    ]:
        path = tmp_path / directory
        path.mkdir()
        env[name] = str(path)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("g3fd_dd_start_boundary.py")),
            str(ROOT),
            mode,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "mode": mode,
        "passed": True,
    }
