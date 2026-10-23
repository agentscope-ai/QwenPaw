"""QR control notifications are safe and remain bound to the live worker."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import psutil
import pytest
import pytest_asyncio

from extension_process_suite import eventually
from wechat_w4_formal_support import (
    official_wechat_zip,
    runtime,
    wechat_host_import_guard,
)
from wechat_w4_waiting_support import native_ilink, qr_ilink

__all__ = ["runtime", "native_ilink", "qr_ilink", "wechat_host_import_guard"]


@pytest_asyncio.fixture
async def pending_login(runtime, qr_ilink, tmp_path, capfd):
    token_file = tmp_path / "fresh-auth/token"
    starting = asyncio.create_task(
        runtime(
            "wechat",
            source_factory=official_wechat_zip,
            bot_token="",
            bot_token_file=str(token_file),
            media_dir=str(tmp_path / "media"),
            base_url=qr_ilink.mock.base_url,
        )
    )
    await eventually(lambda: qr_ilink.qr_polls or starting.done())
    if starting.done():
        await starting
        pytest.fail("WeChat connected without waiting for a QR scan")
    workspace = runtime.workspaces[-1]
    manager = workspace.channel_manager
    channel = await manager.get_channel("wechat")
    assert channel is not None
    process = channel.channel_process
    assert process.health_snapshot()["platform_state"] == "connecting"
    try:
        yield SimpleNamespace(
            external=qr_ilink,
            task=starting,
            channel=channel,
            process=process,
            manager=manager,
            token_file=token_file,
            startup_terminal=capfd.readouterr(),
        )
    finally:
        qr_ilink.qr_expired = False
        qr_ilink.qr_confirmed = True
        async with asyncio.timeout(8):
            await asyncio.gather(starting, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("credentials", ["config", "cache"])
async def test_existing_credentials_do_not_fetch_or_print_a_new_qr(
    runtime, qr_ilink, tmp_path, capfd, credentials
):
    token_file = tmp_path / "existing-auth/token"
    if credentials == "cache":
        token_file.parent.mkdir()
        token_file.write_text("temporary-file-token")
    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token" if credentials == "config" else "",
        bot_token_file=str(token_file),
        media_dir=str(tmp_path / "media"),
        base_url=qr_ilink.mock.base_url,
    )
    assert rt.process.health_snapshot()["platform_state"] == "connected"
    assert qr_ilink.qr_fetches == 0 and not qr_ilink.qr_polls
    terminal = capfd.readouterr()
    assert qr_ilink.mock.base_url + "/scan" not in terminal.out + terminal.err
    assert "temporary-file-token" not in terminal.out + terminal.err


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["stop", "expired"])
async def test_unconfirmed_login_cleans_up_worker_and_auth_leases(
    pending_login, capfd, ending
):
    login = pending_login
    process = login.process
    pid = process.health_snapshot()["pid"]
    terminal = login.startup_terminal
    assert login.external.mock.base_url + "/scan" in terminal.err
    assert "temporary-file-token" not in terminal.out + terminal.err
    assert not login.token_file.exists()
    assert login.external.qr_fetches == 1
    owners = login.channel._owner_registry.runtime_owners
    assert owners.leases("wechat")
    if ending == "expired":
        login.external.qr_expired = True
        await eventually(lambda: login.task.done())
        assert login.task.exception() is not None
        assert login.external.qr_polls[-1]["status"] == "expired"
    else:
        receipt = await login.manager.stop_one("wechat")
        assert receipt.stopped and receipt.exited and not receipt.forced
        assert receipt.residual == ()
        await eventually(lambda: login.task.done())
    await eventually(lambda: not psutil.pid_exists(pid))
    assert not login.token_file.exists()
    assert owners.leases("wechat") == ()
    terminal = capfd.readouterr()
    assert "temporary-file-token" not in terminal.out + terminal.err


@pytest.mark.asyncio
async def test_invalid_or_stale_qr_notifications_are_silent_and_worker_survives(
    pending_login, capfd
):
    from qwenpaw.channel_protocol.models import (
        AUTH_QRCODE_CAPABILITY,
        RpcNotification,
    )

    login = pending_login
    channel, process = login.channel, login.process
    original = channel.descriptor
    identity = channel._identity().to_mapping()
    valid = {**identity, "scan_url": "https://login.example.test/scan"}
    capfd.readouterr()
    invalid = [
        {**valid, "scan_url": "javascript:alert(1)"},
        {**valid, "scan_url": "https://login.example.test/\x1b[31m"},
        {**valid, "scan_url": "https://user:secret@login.example.test/scan"},
        {**valid, "bot_token": "must-never-be-printed"},
        {**valid, "generation": identity["generation"] + 1},
        {**valid, "instance_id": "retired-instance"},
        {**valid, "channel_key": "another_chat"},
    ]
    for params in invalid:
        await process._peer._dispatch_notification(
            RpcNotification("channel.auth.required", params)
        )
    channel.descriptor = replace(
        original,
        capabilities=tuple(
            value
            for value in original.capabilities
            if value != AUTH_QRCODE_CAPABILITY
        ),
    )
    try:
        await process._peer._dispatch_notification(
            RpcNotification("channel.auth.required", valid)
        )
    finally:
        channel.descriptor = original
    terminal = capfd.readouterr()
    assert terminal.out == terminal.err == ""
    # A valid control notification is the positive control for registration.
    await process._peer._dispatch_notification(
        RpcNotification("channel.auth.required", valid)
    )
    assert valid["scan_url"] in capfd.readouterr().err
    login.external.qr_confirmed = True
    async with asyncio.timeout(8):
        rt = await login.task
    assert rt.process is process
    assert process.health_snapshot()["state"] == "ready"
    assert process.health_snapshot()["platform_state"] == "connected"
    capfd.readouterr()
    await process._peer._dispatch_notification(
        RpcNotification("channel.auth.required", valid)
    )
    assert valid["scan_url"] not in capfd.readouterr().err


@pytest.mark.parametrize(
    "scan_url",
    [
        "",
        "javascript:alert(1)",
        "file:///tmp/scan",
        "https:///scan",
        "https://user@example.test/scan",
        "https://example.test/a b",
        "https://example.test/\nscan",
        "https://example.test/\x1b[31m",
        "https://example.test/\x7f",
        "https://-invalid.example/scan",
        "https://example.test:bad/scan",
        "https://example.test/" + "x" * 4096,
    ],
)
def test_auth_required_rejects_unsafe_scan_url(scan_url):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.models import AuthRequiredParams

    with pytest.raises(ProtocolValidationError):
        AuthRequiredParams.from_mapping(
            {
                "channel_key": "wechat",
                "instance_id": "instance",
                "generation": 1,
                "scan_url": scan_url,
            }
        )


@pytest.mark.parametrize(
    "scan_url",
    [
        "https://login.example.test/scan?code=one",
        "http://127.0.0.1:9999/scan",
        "https://[::1]/scan",
    ],
)
def test_auth_required_round_trips_valid_scan_url(scan_url):
    from qwenpaw.channel_protocol.models import AuthRequiredParams

    params = {
        "channel_key": "wechat",
        "instance_id": "instance",
        "generation": 1,
        "scan_url": scan_url,
    }
    assert AuthRequiredParams.from_mapping(params).to_mapping() == params
