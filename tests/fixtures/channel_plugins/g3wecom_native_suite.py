"""Native WeCom QR HTTP, short-lived workers and scoped real config save."""

import hashlib
import json
import os
import time
from urllib.parse import parse_qs, urlsplit

import psutil
import pytest

from g3wecom_native_support import g3_host_import_boundary, wecom_qr

__all__ = ["g3_host_import_boundary", "wecom_qr"]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True).encode()
    ).hexdigest()


def assert_children_reaped(qr):
    assert qr.requests
    assert all(
        row["pid"] != os.getpid() and not psutil.pid_exists(row["pid"])
        for row in qr.requests
    )
    assert not any(
        lease.key.kind == "management"
        for lease in qr.loader.registry.runtime_owners.leases("wecom")
    )


@pytest.mark.asyncio
async def test_native_wecom_fetch_success_scoped_put_and_real_readback(
    wecom_qr,
):
    from qwenpaw.config.config import load_agent_config

    qr = wecom_qr
    qr.fetch_redirect = True
    qr.poll = {
        "data": {
            "status": "success",
            "bot_info": {
                "botid": "issued-test-bot",
                "secret": "issued-test-secret",
            },
        }
    }
    before_a = load_agent_config("A").channels.model_dump()["wecom"]
    before_b = (qr.paths["B"] / "agent.json").read_bytes()
    started_ms = int(time.time() * 1000)
    fetched = await qr.sessions.fetch(qr.scope, {})
    ended_ms = int(time.time() * 1000)
    assert fetched.scan_url == "https://work.weixin.qq.com/scan/test-only"
    assert fetched.poll_token != qr.scode
    assert len(qr.requests) == 2
    gen, redirected = qr.requests
    assert gen["method"] == redirected["method"] == "GET"
    assert gen["pid"] == redirected["pid"]
    assert gen["follow_redirects"] is redirected["follow_redirects"] is True
    assert urlsplit(gen["url"]).path == "/ai/qc/gen"
    assert urlsplit(redirected["url"]).path == "/ai/qc/final"
    query = parse_qs(urlsplit(gen["url"]).query)
    assert set(query) == {"source", "state", "timestamp"}
    assert query["source"] == ["qwenpaw"]
    assert len(query["state"][0]) >= 20
    assert started_ms <= int(query["timestamp"][0]) <= ended_ms
    assert set(gen["timeout"].values()) == {15}
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert result.status == "success"
    credentials = {"bot_id": "issued-test-bot", "secret": "issued-test-secret"}
    assert digest(result.credentials) == digest(credentials)
    assert len(qr.requests) == 3
    poll = qr.requests[-1]
    assert poll["pid"] != gen["pid"]
    assert poll["method"] == "GET" and poll["follow_redirects"] is False
    assert urlsplit(poll["url"]).path == "/ai/qc/query_result"
    assert parse_qs(urlsplit(poll["url"]).query) == {"scode": [qr.scode]}
    assert set(poll["timeout"].values()) == {10}
    assert_children_reaped(qr)
    body = {**qr.scope.config, **credentials}
    denied = await qr.client.put(
        "/config/channels/wecom",
        json=body,
        headers={
            "X-Agent-Id": "B",
            "X-Channel-Auth-Session": fetched.poll_token,
        },
    )
    assert denied.status_code == 403
    assert (qr.paths["B"] / "agent.json").read_bytes() == before_b
    assert qr.reloads == []
    saved = await qr.client.put(
        "/config/channels/wecom",
        json=body,
        headers={
            "X-Agent-Id": "A",
            "X-Channel-Auth-Session": fetched.poll_token,
        },
    )
    assert saved.status_code == 200
    actual = load_agent_config("A").channels.model_dump()["wecom"]
    assert digest({key: actual[key] for key in credentials}) == digest(
        credentials
    )
    assert actual["welcome_text"] == before_a["welcome_text"]
    assert actual["allow_from"] == before_a["allow_from"]
    assert actual["access_control_dm"] == before_a["access_control_dm"]
    assert actual["access_control_group"] == before_a["access_control_group"]
    persisted = json.loads((qr.paths["A"] / "agent.json").read_text())
    assert digest(persisted["channels"]["wecom"]) == digest(actual)
    reread = await qr.client.get(
        "/config/channels/wecom", headers={"X-Agent-Id": "A"}
    )
    assert reread.status_code == 200
    assert digest(reread.json()) == digest(actual)
    assert (qr.paths["B"] / "agent.json").read_bytes() == before_b
    assert qr.reloads == ["A"]
    assert len(qr.requests) == 3
    assert_children_reaped(qr)


@pytest.mark.asyncio
async def test_native_wecom_waiting_then_expired_never_issues_credentials(
    wecom_qr,
):
    qr = wecom_qr
    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.poll = {"data": {}}
    waiting = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert waiting.status == "waiting" and waiting.credentials == {}
    qr.poll = {"data": {"status": "expired", "bot_info": {}}}
    expired = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert expired.status == "expired" and expired.credentials == {}
    assert len(qr.requests) == 3
    assert len({row["pid"] for row in qr.requests}) == 3
    again = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert again.status == "expired" and again.credentials == {}
    assert len(qr.requests) == 3
    assert_children_reaped(qr)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["null_bot_info", "http_403"])
async def test_native_wecom_poll_errors_do_not_return_success_or_retry(
    wecom_qr, fault
):
    from qwenpaw.app.channels.management import ManagementError

    qr = wecom_qr
    fetched = await qr.sessions.fetch(qr.scope, {})
    if fault == "null_bot_info":
        qr.poll = {"data": {"status": "success", "bot_info": None}}
        reason = "PLATFORM_RESULT_UNKNOWN"
    else:
        qr.poll_status = 403
        reason = "PLATFORM_REJECTED"
    with pytest.raises(ManagementError) as caught:
        await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert caught.value.reason_code == reason
    assert len(qr.requests) == 2
    assert_children_reaped(qr)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "html",
    [
        "<html>No settings</html>",
        "<script>window.settings = "
        '{"auth_url":"https://scan.invalid"}</script>',
    ],
)
async def test_native_wecom_fetch_requires_actual_settings_and_scode(
    wecom_qr, html
):
    from qwenpaw.app.channels.management import ManagementError

    qr = wecom_qr
    qr.fetch_text = html
    with pytest.raises(ManagementError) as caught:
        await qr.sessions.fetch(qr.scope, {})
    assert caught.value.reason_code == "PLATFORM_RESULT_UNKNOWN"
    assert len(qr.requests) == 1
    assert_children_reaped(qr)


@pytest.mark.asyncio
async def test_native_wecom_poll_redirect_is_not_followed(wecom_qr):
    from qwenpaw.app.channels.management import ManagementError

    qr = wecom_qr
    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.poll_status = 302
    with pytest.raises(ManagementError) as caught:
        await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert caught.value.reason_code == "PLATFORM_REJECTED"
    assert len(qr.requests) == 2
    assert qr.requests[-1]["follow_redirects"] is False
    assert_children_reaped(qr)
