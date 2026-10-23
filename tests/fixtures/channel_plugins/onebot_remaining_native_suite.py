"""Remaining original config/auth and bounded resource ownership oracles."""

import asyncio
import logging

import aiohttp
from aiohttp.test_utils import make_mocked_request
import pytest
from pydantic import ValidationError

from onebot_native_suite import OneBotPlatform, platform_at, ws_url
from qwenpaw.config.config import OneBotConfig


async def test_original_config_limit_host_table_and_runtime_units(tmp_path):
    base = OneBotConfig()
    assert base.media_base64_max_mb == 10
    assert base.media_download_max_mb == 50
    assert base.ws_host == "127.0.0.1"
    for field in ("media_base64_max_mb", "media_download_max_mb"):
        with pytest.raises(ValidationError):
            OneBotConfig(**{field: 0})
    configured = OneBotConfig(
        media_base64=True, media_base64_max_mb=3, media_download_max_mb=5
    )
    assert configured.media_base64_max_mb == 3
    assert configured.media_download_max_mb == 5
    for host, wanted in [
        (None, "127.0.0.1"),
        ("", "127.0.0.1"),
        ("   ", "127.0.0.1"),
        ("[::1]", "::1"),
    ]:
        platform = OneBotPlatform()
        config = configured.model_dump()
        config["workspace_dir"] = str(tmp_path)
        if host is None:
            config.pop("ws_host")
        else:
            config["ws_host"] = host
        await platform.prepare(config, {})
        assert platform._ws_host == wanted
        assert platform._auth_required is False
        assert platform._media_base64 is True
        assert platform._media_base64_max_bytes == 3_000_000
        assert platform._inbound_media._max_download_bytes == 5_000_000
        assert (
            platform._inbound_media._max_download_bytes
            != platform._media_base64_max_bytes
        )
        assert platform._media_dir == tmp_path / "media"
        assert not await platform._is_server_healthy()
        await platform.close()
    explicit = OneBotPlatform()
    await explicit.prepare(
        {
            "media_dir": str(tmp_path / "explicit"),
            "workspace_dir": str(tmp_path),
        },
        {},
    )
    assert explicit._media_dir == tmp_path / "explicit"
    await explicit.close()
    external = OneBotPlatform()
    await external.prepare(
        {"ws_host": "0.0.0.0", "workspace_dir": str(tmp_path)},
        {"access_token": "   "},
    )
    assert external._access_token == ""
    assert external._auth_required is True
    await external.close()


async def test_original_auth_parameter_table_logs_and_external_acceptance(
    tmp_path, caplog
):
    async with platform_at(tmp_path, host="0.0.0.0", token="s3cret-token") as (
        platform,
        _,
        _,
    ):
        for header in (
            "Bearer s3cret-token",
            "Token s3cret-token",
            "bearer s3cret-token",
        ):
            request = make_mocked_request(
                "GET", "/ws", headers={"Authorization": header}
            )
            assert platform._token_authorized(request) is True
        for header in (
            "Bearer wrong-token",
            "Basic s3cret-token",
            "s3cret-token",
            "Bearer",
            "",
        ):
            request = make_mocked_request(
                "GET", "/ws", headers={"Authorization": header}
            )
            assert platform._token_authorized(request) is False
        with caplog.at_level(logging.WARNING):
            response = await platform._handle_ws_connection(
                make_mocked_request("GET", "/ws?access_token=s3cret-token")
            )
        assert response.status == 401
        assert "Authorization header" in caplog.text
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(
                f"http://127.0.0.1:{platform.listen_port}/ws",
                headers={"Authorization": "Bearer s3cret-token"},
            ):
                assert platform.endpoint.bound_externally
                assert platform.endpoint.auth_required
                assert platform.endpoint.readiness == "ready"
    platform = OneBotPlatform()
    await platform.prepare(
        {"ws_host": "127.0.0.1", "workspace_dir": str(tmp_path)},
        {"access_token": "密钥-abc"},
    )
    assert (
        platform._token_authorized(
            make_mocked_request(
                "GET", "/ws", headers={"Authorization": "Bearer 密钥-abc"}
            )
        )
        is True
    )
    await platform.close()
    platform = OneBotPlatform()
    await platform.prepare(
        {"ws_host": "0.0.0.0", "workspace_dir": str(tmp_path)}, {}
    )
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        response = await platform._handle_ws_connection(
            make_mocked_request("GET", "/ws").clone(
                remote="1.2.3.4\nINFO onebot: client connected from 1.2.3.4"
            )
        )
    assert response.status == 401
    assert len(caplog.records) == 1
    assert "\n" not in caplog.records[0].getMessage()
    assert not platform._connections
    await platform.close()


class HangingConnection:
    def __init__(self):
        self.close_started = asyncio.Event()
        self.force_closed = False

    async def close(self):
        self.close_started.set()
        await asyncio.Event().wait()

    def force_close(self):
        self.force_closed = True


class RecordingTransport:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


async def test_original_bounded_concurrent_cancel_safe_native_close(tmp_path):
    platform = OneBotPlatform(watchdog_interval=60.0, shutdown_timeout=0.05)
    await platform.prepare(
        {"ws_host": "127.0.0.1", "ws_port": 0, "workspace_dir": str(tmp_path)},
        {},
    )
    await platform.start(
        lambda _: asyncio.sleep(0),
        lambda _operation, _endpoint: asyncio.sleep(0),
    )
    first, second = HangingConnection(), HangingConnection()
    first_transport, second_transport = (
        RecordingTransport(),
        RecordingTransport(),
    )
    platform._connections.update({first, second})
    platform._connection_transports.update(
        {first: first_transport, second: second_transport}
    )
    pending = asyncio.get_running_loop().create_future()
    platform._pending_calls["pending"] = pending
    watchdog = platform._watchdog_task
    close = asyncio.create_task(platform.close())
    try:
        await asyncio.wait_for(
            asyncio.gather(
                first.close_started.wait(), second.close_started.wait()
            ),
            0.2,
        )
        started = asyncio.get_running_loop().time()
        close.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close
        assert asyncio.get_running_loop().time() - started < 0.2
        assert first.close_started.is_set() and second.close_started.is_set()
        assert (
            first_transport.closed is True and second_transport.closed is True
        )
        assert pending.cancelled()
        assert platform.listen_port is None
        assert platform.health_snapshot()["connection_count"] == 0
        assert watchdog.done()
        assert all(task.done() for task in platform._cleanup_tasks)
    finally:
        await asyncio.gather(close, return_exceptions=True)
        await platform.close()


async def test_remaining_native_health_restart_and_start_error(
    tmp_path, monkeypatch
):
    async with platform_at(tmp_path) as (platform, _, _):
        assert await platform._is_server_healthy()
        original_site = platform._site
        await platform._watchdog_iteration()
        assert platform._site is original_site
        await original_site.stop()
        await platform._runner.cleanup()
        platform._site = platform._runner = platform._app = None
        await platform._watchdog_iteration()
        assert platform._site is not None and platform._runner is not None
        assert platform._app is not None
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(platform)):
                pass
    from aiohttp.web import TCPSite

    async def unexpected(_site):
        raise RuntimeError("unexpected error")

    platform = OneBotPlatform()
    await platform.prepare({"ws_port": 0, "workspace_dir": str(tmp_path)}, {})
    monkeypatch.setattr(TCPSite, "start", unexpected)
    try:
        with pytest.raises(RuntimeError, match="unexpected error"):
            await platform.start(
                lambda _: asyncio.sleep(0),
                lambda _operation, _endpoint: asyncio.sleep(0),
            )
    finally:
        await platform.close()
