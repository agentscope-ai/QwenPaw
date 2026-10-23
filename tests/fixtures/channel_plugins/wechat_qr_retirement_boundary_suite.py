"""QR host retirement: real dispatch and resource boundaries."""

import asyncio
import base64
import importlib.abc
from importlib import import_module
import sys

from fastapi import FastAPI
import httpx
import psutil
import pytest

from management_process_suite import (
    KEY,
    active_management,
    eventually,
    local_management_http,
    management_runtime,
)
from wechat_w2_session_suite import qr, qr_leases, narrow_legacy_test_guard
from wechat_w3_router_suite import api_http

__all__ = [
    "local_management_http",
    "management_runtime",
    "qr",
    "narrow_legacy_test_guard",
    "api_http",
]


@pytest.fixture(autouse=True)
def no_platform_implementation_import(monkeypatch):
    attempts = []
    legacy = tuple(
        "qwenpaw.app.channels." + name
        for name in ("wechat", "qq", "wecom", "feishu", "dingtalk")
    )

    def blocked(name):
        return (
            name.startswith("qwenpaw_channel_")
            or any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in legacy
            )
            or name.split(".")[0]
            in {"lark_oapi", "dingtalk_stream", "wecom_aibot_sdk", "qqbot"}
        )

    assert not any(blocked(name) for name in sys.modules)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if blocked(fullname):
                attempts.append(fullname)
                raise AssertionError("QR host imported platform: " + fullname)

    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    yield
    assert attempts == []
    assert not any(blocked(name) for name in sys.modules)


def test_formal_qr_discovery_is_exact_five_descriptor_owners():
    from qwenpaw.channel_protocol.management import MANAGEMENT_CAPABILITIES
    from qwenpaw.plugins.official_channel_catalog import (
        official_channel_owners,
    )
    from qwenpaw.plugins.official_channels import bundled_channel_description

    actual = {}
    for key, owner in official_channel_owners().items():
        descriptor = bundled_channel_description(owner).descriptor
        capabilities = set(descriptor.capabilities)
        if MANAGEMENT_CAPABILITIES["qrcode.fetch"] in capabilities:
            assert MANAGEMENT_CAPABILITIES["qrcode.poll"] in capabilities
            assert descriptor.channel_key == key
            actual[key] = owner
    assert actual == {
        "wechat": "wechat",
        "wecom": "wecom",
        "qq": "qq",
        "feishu": "feishu",
        "dingtalk": "dingtalk",
    }


def test_qr_host_exports_only_shared_results_and_image_not_platform_handlers():
    module = import_module("qwenpaw.app.channels.qrcode_auth_handler")
    assert module.QRCodeResult("scan", "opaque").poll_token == "opaque"
    assert module.PollResult("waiting", {}).credentials == {}
    assert callable(module.generate_qrcode_image)
    for name in (
        "QRCODE_AUTH_HANDLERS",
        "QRCodeAuthHandler",
        "WeChatQRCodeAuthHandler",
        "WecomQRCodeAuthHandler",
        "QQQRCodeAuthHandler",
        "FeishuQRCodeAuthHandler",
        "DingtalkQRCodeAuthHandler",
        "_encode_poll_token",
        "_decode_poll_token",
        "_decrypt_secret",
    ):
        assert not hasattr(module, name)


@pytest.mark.asyncio
async def test_qr_http_unsupported_and_missing_service():
    app = FastAPI()
    app.include_router(import_module("qwenpaw.app.routers.config").router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://host.test"
    ) as client:
        for key in ("unknown_qr_owner", "console"):
            for suffix in ("qrcode", "qrcode/status?token=opaque"):
                result = await client.get(f"/config/channels/{key}/{suffix}")
                assert result.status_code == 404
                assert result.json()["detail"] == (
                    "QR code not supported for channel: " + key
                )
        for key in ("wechat", "wecom", "qq", "feishu", "dingtalk"):
            for suffix in ("qrcode", "qrcode/status?token=opaque"):
                result = await client.get(f"/config/channels/{key}/{suffix}")
                assert result.status_code == 503
                assert result.json() == {"detail": "MANAGEMENT_CLOSED"}


@pytest.mark.asyncio
async def test_real_managed_http_dispatch_and_cancel_reap_exact_child(
    api_http,
):
    fixture = api_http
    fetched = await fixture.client.get(f"/config/channels/{KEY}/qrcode")
    assert fetched.status_code == 200, fetched.text
    data = fetched.json()
    assert set(data) == {"qrcode_img", "poll_token"}
    assert base64.b64decode(data["qrcode_img"])[:8] == b"\x89PNG\r\n\x1a\n"
    token = data["poll_token"]
    assert token != "fixture-continuation"
    polled = await fixture.client.get(
        f"/config/channels/{KEY}/qrcode/status", params={"token": token}
    )
    assert polled.status_code == 200, polled.text
    assert polled.json() == {
        "status": "confirmed",
        "credentials": {"api_token": "fixture-result-secret"},
    }
    removed = await fixture.client.delete(
        f"/config/channels/{KEY}/qrcode", params={"token": token}
    )
    assert removed.status_code == 204
    fetched = await fixture.client.get(f"/config/channels/{KEY}/qrcode")
    assert fetched.status_code == 200, fetched.text
    token = fetched.json()["poll_token"]
    fixture.qr.http.reply_gate.clear()
    task = asyncio.create_task(
        fixture.client.get(
            f"/config/channels/{KEY}/qrcode/status", params={"token": token}
        )
    )
    try:
        await eventually(lambda: len(fixture.qr.http.requests) == 4)
        (lease,) = active_management(fixture.qr.rt)
        child = fixture.qr.rt.owners.resource(lease)
        pid = child.health_snapshot()["pid"]
        assert psutil.pid_exists(pid)
        removed = await fixture.client.delete(
            f"/config/channels/{KEY}/qrcode", params={"token": token}
        )
        assert removed.status_code == 204
        cancelled = await task
        assert cancelled.status_code == 400
        assert cancelled.json() == {"detail": "QR session is no longer active"}
        assert not psutil.pid_exists(pid)
        assert not active_management(fixture.qr.rt)
        assert not qr_leases(fixture.qr)
        assert len(fixture.qr.http.requests) == 4
        assert all(
            not psutil.pid_exists(row["pid"])
            for row in fixture.qr.http.requests
        )
    finally:
        fixture.qr.http.reply_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
