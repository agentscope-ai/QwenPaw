"""WeChat options compatibility: original request-to-native-manage boundary."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def test_actual_parsed_request_reaches_wechat_manage_and_effective_http(
    tmp_path,
):
    env = dict(os.environ)
    for key, name in [
        ("HOME", "home"),
        ("QWENPAW_WORKING_DIR", "work"),
        ("QWENPAW_SECRET_DIR", "secrets"),
        ("QWENPAW_BACKUP_DIR", "backups"),
    ]:
        path = tmp_path / name
        path.mkdir()
        env[key] = str(path)
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("g3fd_dd_wechat_manage_boundary.py")),
            str(ROOT),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stdout + process.stderr


# Actual host/runtime controls, queued behind the parsed-request regression.
import hashlib
from urllib.parse import urlsplit

import pytest
from g3fd_dd_native_support import g3_host_import_boundary, native_qr

__all__ = ["g3_host_import_boundary", "native_qr"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "temporary,expected_host",
    [
        ("https://temporary.invalid", "temporary.invalid"),
        ("", "ilinkai.weixin.qq.com"),
    ],
)
async def test_actual_wechat_options_effective_url_and_auth_custody(
    native_qr, temporary, expected_host
):
    qr = await native_qr("wechat", "https://saved.invalid")
    options = {"base_url": temporary}
    fetched = await qr.sessions.fetch(qr.scope, options)
    options["base_url"] = "https://mutated.invalid"
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert result.status == "confirmed"
    assert result.credentials["bot_token"] == "wechat-issued-token"
    assert len(qr.requests) == 2
    assert all(
        urlsplit(row["url"]).hostname == expected_host for row in qr.requests
    )
    held = qr.sessions._sessions[
        hashlib.sha256(fetched.poll_token.encode()).hexdigest()
    ]
    expected_scope = hashlib.sha256(
        (
            "credential\0https://"
            + expected_host
            + ":443\0wechat-issued-token"
        ).encode()
    ).hexdigest()
    assert expected_scope in {claim.key.name for claim in held.claims}
    assert all(
        claim in qr.loader.registry.runtime_owners.leases()
        for claim in held.claims
    )
    claims = held.claims
    await qr.sessions.cancel(qr.scope, fetched.poll_token)
    assert all(
        claim not in qr.loader.registry.runtime_owners.leases()
        for claim in claims
    )
    assert held.options == {}
