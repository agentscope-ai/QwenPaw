"""Remaining legacy QR branches through native manage/worker/Session.

Only the external HTTP transport is controlled. Copied instrumentation is not
an unchanged published ZIP acceptance run.
"""
import hashlib
import os

import psutil
import pytest

from g3fd_dd_native_support import g3_host_import_boundary, native_qr
from qwenpaw.app.channels.management import ManagementError

__all__ = ["g3_host_import_boundary", "native_qr"]


def assert_native_boundary(qr, actions):
    assert [row["action"] for row in qr.requests] == actions
    assert all(row["pid"] != os.getpid() for row in qr.requests)
    assert all(not psutil.pid_exists(row["pid"]) for row in qr.requests)
    for name, digest in qr.original_functions_sha.items():
        assert (
            hashlib.sha256(
                (qr.instrumented_source / qr.namespace / name).read_bytes()
            ).hexdigest()
            == digest
        )


def assert_gateway_error(error, reason):
    from qwenpaw.app.routers.config import _management_http_error

    assert error.reason_code == reason
    public_error = _management_http_error(error)
    assert public_error.status_code == 502
    assert public_error.detail == reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "responses,reason,actions",
    [
        (
            {"init": {"body": {"supported_auth_methods": ["other_method"]}}},
            "PLATFORM_REJECTED",
            ["init"],
        ),
        (
            {
                "begin": {
                    "body": {
                        "verification_uri_complete": "https://example.com/qr"
                    }
                }
            },
            "PLATFORM_RESULT_UNKNOWN",
            ["init", "begin"],
        ),
        (
            {"begin": {"body": {"device_code": "device-123"}}},
            "PLATFORM_RESULT_UNKNOWN",
            ["init", "begin"],
        ),
    ],
    ids=["unsupported-auth", "missing-device-code", "missing-qr-url"],
)
async def test_feishu_fetch_rejects_unusable_platform_result(
    native_qr, responses, reason, actions
):
    qr = await native_qr("feishu", responses=responses)
    with pytest.raises(ManagementError) as caught:
        await qr.sessions.fetch(qr.scope, {})
    assert_gateway_error(caught.value, reason)
    assert_native_boundary(qr, actions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,credentials",
    [
        ("authorization_pending", "waiting", {}),
        ("slow_down", "waiting", {}),
        ("expired_token", "expired", {"fail_reason": "QR code expired"}),
        ("invalid_grant", "expired", {"fail_reason": "QR code expired"}),
        (
            "access_denied",
            "fail",
            {"fail_reason": "User denied authorization"},
        ),
    ],
)
async def test_feishu_poll_preserves_legacy_status_and_reason(
    native_qr, error, status, credentials
):
    qr = await native_qr(
        "feishu", responses={"poll": {"body": {"error": error}}}
    )
    fetched = await qr.sessions.fetch(qr.scope, {})
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert result.status == status
    assert result.credentials == credentials
    assert_native_boundary(qr, ["init", "begin", "poll"])


@pytest.mark.asyncio
async def test_feishu_poll_transport_failure_is_gateway_error(native_qr):
    qr = await native_qr(
        "feishu", responses={"poll": {"transport_error": "read"}}
    )
    fetched = await qr.sessions.fetch(qr.scope, {})
    with pytest.raises(ManagementError) as caught:
        await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert_gateway_error(caught.value, "PLATFORM_RESULT_UNKNOWN")
    assert_native_boundary(qr, ["init", "begin", "poll"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,status,credentials",
    [
        (
            {
                "status": "SUCCESS",
                "client_id": "ding6qfjtrjlehq3rmee",
                "client_secret": "secret-value",
                "robot_code": "ding6qfjtrjlehq3rmee",
                "mode": "STREAM",
            },
            "success",
            {
                "client_id": "ding6qfjtrjlehq3rmee",
                "client_secret": "secret-value",
            },
        ),
        ({"status": "WAITING"}, "waiting", {}),
        ({"status": "BRAND_NEW"}, "waiting", {}),
        (
            {"status": "WAITING", "client_id": None, "client_secret": None},
            "waiting",
            {},
        ),
        (
            {
                "status": "SUCCESS",
                "client_id": "ding6qfjtrjlehq3rmee",
                "client_secret": "",
            },
            "waiting",
            {},
        ),
        (
            {"status": "FAIL", "fail_reason": "user denied"},
            "fail",
            {"fail_reason": "user denied"},
        ),
        (
            {"status": "EXPIRED", "fail_reason": "user denied"},
            "expired",
            {"fail_reason": "user denied"},
        ),
    ],
    ids=["success", "waiting", "unknown", "null", "half", "fail", "expired"],
)
async def test_dingtalk_remaining_native_poll_oracles(
    native_qr, body, status, credentials
):
    qr = await native_qr(
        "dingtalk",
        responses={"poll": {"body": {"errcode": 0, "errmsg": "ok", **body}}},
    )
    fetched = await qr.sessions.fetch(qr.scope, {})
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert result.status == status
    assert result.credentials == credentials
    assert_native_boundary(qr, ["init", "begin", "poll"])
