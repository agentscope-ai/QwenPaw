# -*- coding: utf-8 -*-
"""Exercise session and crypto recovery using nio against a local HTTP API."""

# pylint: disable=protected-access,redefined-outer-name
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from nio.crypto import ENCRYPTION_ENABLED

from qwenpaw.app.channels.matrix.channel import MatrixChannel


@pytest.fixture
async def homeserver():
    """Keep server device keys independently of nio's persisted account."""
    state = {
        "logins": [],
        "whoami": [],
        "uploads": [],
        "device_keys": {},
        "user_id": "@bot:example.org",
        "device_id": "BOT",
        "whoami_errors": [],
        "query_failures": {},
        "upload_error": False,
    }

    async def handle(request):
        endpoint = request.path.rsplit("/", 1)[-1]
        if endpoint == "login":
            state["logins"].append(await request.json())
            return web.json_response(
                {
                    "user_id": state["user_id"],
                    "device_id": state["device_id"],
                    "access_token": f"session-{len(state['logins'])}",
                },
            )
        if endpoint == "whoami":
            state["whoami"].append(
                request.headers.get("Authorization", "").removeprefix(
                    "Bearer ",
                ),
            )
            if state["whoami_errors"]:
                code, status = state["whoami_errors"].pop(0)
                return web.json_response(
                    {"errcode": code, "error": code},
                    status=status,
                )
            return web.json_response(
                {
                    "user_id": state["user_id"],
                    "device_id": state["device_id"],
                },
            )
        if endpoint == "query":
            return web.json_response(
                {
                    "device_keys": {
                        state["user_id"]: state["device_keys"],
                    },
                    "failures": state["query_failures"],
                },
            )
        if endpoint == "upload":
            body = await request.json()
            state["uploads"].append(body)
            if state["upload_error"]:
                return web.json_response(
                    {"errcode": "M_FORBIDDEN", "error": "upload denied"},
                    status=403,
                )
            if "device_keys" in body:
                state["device_keys"][state["device_id"]] = body["device_keys"]
            return web.json_response(
                {
                    "one_time_key_counts": {
                        "signed_curve25519": len(body["one_time_keys"]),
                    },
                },
            )
        raise AssertionError(f"Unexpected Matrix request: {request.path}")

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    state["url"] = f"http://127.0.0.1:{runner.addresses[0][1]}"
    try:
        yield state
    finally:
        await runner.cleanup()


@pytest.fixture
def channel_factory(homeserver, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.app.channels.matrix.channel.WORKING_DIR",
        tmp_path,
    )

    def create(**overrides):
        config = {
            "process": AsyncMock(),
            "homeserver": homeserver["url"],
            "matrix_user_id": homeserver["user_id"],
            "password": "password",
            "device_id": "BOT",
        }
        config.update(overrides)
        channel = MatrixChannel(**config)
        channel._sync_loop = AsyncMock()
        return channel

    return create


async def test_password_session_is_reused_across_restarts(
    homeserver,
    channel_factory,
):
    first = channel_factory()
    await first.start()
    await first.stop()
    restarted = channel_factory()
    try:
        await restarted.start()
        assert len(homeserver["logins"]) == 1
        assert homeserver["whoami"] == ["session-1"]
        assert restarted._client.access_token == "session-1"
    finally:
        await restarted.stop()


async def test_localpart_login_reuses_canonical_identity(
    homeserver,
    channel_factory,
):
    first = channel_factory(matrix_user_id="bot")
    await first.start()
    await first.stop()
    restarted = channel_factory(matrix_user_id="bot")
    try:
        await restarted.start()
        assert len(homeserver["logins"]) == 1
        assert restarted._user_id == homeserver["user_id"]
        assert (await restarted.health_check())["status"] == "healthy"
    finally:
        await restarted.stop()


@pytest.mark.skipif(not ENCRYPTION_ENABLED, reason="nio E2EE backend required")
async def test_deleted_server_keys_are_reuploaded_from_persisted_account(
    homeserver,
    channel_factory,
):
    first = channel_factory(encryption=True)
    await first.start()
    original_keys = dict(first._client.olm.account.identity_keys)
    assert first._client.olm.account.shared
    await first.stop()
    homeserver["device_keys"].clear()
    homeserver["uploads"].clear()
    restarted = channel_factory(encryption=True)
    try:
        await restarted.start()
        assert homeserver["uploads"], "server lost keys, nio still says shared"
        uploaded = homeserver["uploads"][0]
        assert uploaded["device_keys"]["keys"] == {
            f"{kind}:BOT": value for kind, value in original_keys.items()
        }
        assert uploaded["one_time_keys"]
        assert restarted._client.olm.account.shared
        assert (await restarted.health_check())["status"] == "healthy"
    finally:
        await restarted.stop()


@pytest.mark.skipif(not ENCRYPTION_ENABLED, reason="nio E2EE backend required")
async def test_health_detects_server_key_loss(homeserver, channel_factory):
    channel = channel_factory(encryption=True)
    try:
        await channel.start()
        homeserver["device_keys"].clear()
        health = await channel.health_check()
        assert health["status"] == "unhealthy"
        assert "keys" in health["detail"]
    finally:
        await channel.stop()


async def test_restarting_the_same_instance_reuses_session(
    homeserver,
    channel_factory,
):
    channel = channel_factory()
    await channel.start()
    await channel.stop()
    assert (await channel.health_check())["status"] == "unhealthy"
    try:
        await channel.start()
        assert len(homeserver["logins"]) == 1
        assert homeserver["whoami"] == ["session-1"]
    finally:
        await channel.stop()


@pytest.mark.parametrize("login_user", ["bot", "@bot:example.org"])
async def test_expired_session_falls_back_to_password(
    homeserver,
    channel_factory,
    login_user,
):
    channel = channel_factory(matrix_user_id=login_user)
    await channel.start()
    await channel.stop()
    homeserver["whoami_errors"] = [("M_UNKNOWN_TOKEN", 401)]
    restarted = channel_factory(matrix_user_id=login_user)
    try:
        await restarted.start()
        assert len(homeserver["logins"]) == 2
        assert homeserver["whoami"] == ["session-1"]
        assert restarted._client.access_token == "session-2"
        assert (await restarted.health_check())["status"] == "healthy"
        persisted = json.loads(restarted._auth_state_path().read_text())
        assert persisted["access_token"] == "session-2"
        assert "password" not in persisted
        assert "password" not in persisted.values()
    finally:
        await restarted.stop()


@pytest.mark.parametrize("code", ["M_FORBIDDEN", "M_USER_DEACTIVATED"])
async def test_other_auth_rejections_do_not_relogin(
    homeserver,
    channel_factory,
    code,
):
    first = channel_factory()
    await first.start()
    await first.stop()
    homeserver["whoami_errors"] = [(code, 403)]
    restarted = channel_factory()
    try:
        await restarted.start()
        assert len(homeserver["logins"]) == 1
        assert restarted._sync_task is None
        assert (await restarted.health_check())["status"] == "unhealthy"
    finally:
        await restarted.stop()


async def test_transient_whoami_error_retries_the_cached_session(
    homeserver,
    channel_factory,
    monkeypatch,
):
    first = channel_factory()
    await first.start()
    await first.stop()
    homeserver["whoami_errors"] = [("M_UNKNOWN", 502)]
    monkeypatch.setattr(
        "qwenpaw.app.channels.matrix.channel._LOGIN_RETRY_INITIAL_DELAY",
        0,
    )
    restarted = channel_factory()
    try:
        await restarted.start()
        assert len(homeserver["logins"]) == 1
        assert homeserver["whoami"] == ["session-1", "session-1"]
    finally:
        await restarted.stop()


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "changed"},
        {"matrix_user_id": "@different:example.org"},
        {"device_id": "OTHER"},
        {"device_id": "", "device_name": "changed"},
    ],
)
async def test_config_changes_require_password_login(
    homeserver,
    channel_factory,
    changes,
):
    first = channel_factory()
    await first.start()
    await first.stop()
    restarted = channel_factory(**changes)
    try:
        await restarted.start()
        assert len(homeserver["logins"]) == 2
        assert homeserver["whoami"] == []
    finally:
        await restarted.stop()


async def test_cached_token_is_never_sent_to_another_homeserver(
    channel_factory,
):
    first = channel_factory()
    await first.start()
    await first.stop()
    other = channel_factory(homeserver="https://other.example.org")
    other._restore_auth_state_before_start(
        has_password_creds=True,
        has_token_cred=False,
    )
    assert other.access_token == ""
    assert other._cached_auth_identity is None


@pytest.mark.parametrize("cache", ["{}", "{broken", "[]", '{"scope": null}'])
async def test_incomplete_or_legacy_cache_uses_password(
    homeserver,
    channel_factory,
    cache,
):
    channel = channel_factory()
    channel._auth_state_path().write_text(cache)
    try:
        await channel.start()
        assert len(homeserver["logins"]) == 1
        assert homeserver["whoami"] == []
    finally:
        await channel.stop()


async def test_explicit_token_is_not_replaced(homeserver, channel_factory):
    first = channel_factory()
    await first.start()
    await first.stop()
    restarted = channel_factory(access_token="explicit", password="")
    try:
        await restarted.start()
        assert homeserver["whoami"] == ["explicit"]
        assert len(homeserver["logins"]) == 1
    finally:
        await restarted.stop()


@pytest.mark.parametrize("field", ["user_id", "device_id"])
async def test_changed_token_owner_or_device_is_rejected(
    homeserver,
    channel_factory,
    field,
):
    first = channel_factory()
    await first.start()
    await first.stop()
    homeserver[field] = "@other:example.org" if field == "user_id" else "OTHER"
    restarted = channel_factory(matrix_user_id="@bot:example.org")
    try:
        await restarted.start()
        assert len(homeserver["logins"]) == 1
        assert (await restarted.health_check())["status"] == "unhealthy"
    finally:
        await restarted.stop()


@pytest.mark.skipif(not ENCRYPTION_ENABLED, reason="nio E2EE backend required")
async def test_matching_keys_are_not_uploaded_again(
    homeserver,
    channel_factory,
):
    first = channel_factory(encryption=True)
    await first.start()
    await first.stop()
    homeserver["uploads"].clear()
    restarted = channel_factory(encryption=True)
    try:
        await restarted.start()
        assert homeserver["uploads"] == []
        assert (await restarted.health_check())["status"] == "healthy"
    finally:
        await restarted.stop()


@pytest.mark.skipif(not ENCRYPTION_ENABLED, reason="nio E2EE backend required")
async def test_query_failure_does_not_reset_crypto_account(
    homeserver,
    channel_factory,
):
    first = channel_factory(encryption=True)
    await first.start()
    await first.stop()
    homeserver["device_keys"].clear()
    homeserver["uploads"].clear()
    homeserver["query_failures"] = {"example.org": {"errcode": "M_UNKNOWN"}}
    restarted = channel_factory(encryption=True)
    try:
        await restarted.start()
        assert restarted._client.olm.account.shared
        assert homeserver["uploads"] == []
        assert (await restarted.health_check())["status"] == "unhealthy"
    finally:
        await restarted.stop()


@pytest.mark.skipif(not ENCRYPTION_ENABLED, reason="nio E2EE backend required")
async def test_failed_key_upload_is_retried_after_restart(
    homeserver,
    channel_factory,
):
    first = channel_factory(encryption=True)
    await first.start()
    original_keys = dict(first._client.olm.account.identity_keys)
    await first.stop()
    homeserver["device_keys"].clear()
    homeserver["upload_error"] = True
    failed = channel_factory(encryption=True)
    await failed.start()
    assert not failed._client.olm.account.shared
    # A later successful query cannot make an unstarted channel healthy.
    homeserver["device_keys"]["BOT"] = homeserver["uploads"][0]["device_keys"]
    assert (await failed.health_check())["status"] == "unhealthy"
    await failed.stop()
    homeserver["upload_error"] = False
    recovered = channel_factory(encryption=True)
    try:
        await recovered.start()
        assert recovered._client.olm.account.identity_keys == original_keys
        assert recovered._client.olm.account.shared
        assert (await recovered.health_check())["status"] == "healthy"
    finally:
        await recovered.stop()


@pytest.mark.skipif(not ENCRYPTION_ENABLED, reason="nio E2EE backend required")
async def test_conflicting_remote_identity_is_not_overwritten(
    homeserver,
    channel_factory,
):
    first = channel_factory(encryption=True)
    await first.start()
    await first.stop()
    homeserver["device_keys"]["BOT"]["keys"]["ed25519:BOT"] = "different"
    homeserver["uploads"].clear()
    restarted = channel_factory(encryption=True)
    try:
        await restarted.start()
        assert homeserver["uploads"] == []
        health = await restarted.health_check()
        assert health["status"] == "unhealthy"
        assert "conflict" in health["detail"]
    finally:
        await restarted.stop()


async def test_health_check_times_out_when_homeserver_is_unreachable(
    channel_factory,
    monkeypatch,
):
    channel = channel_factory()
    await channel.start()
    channel.encryption = True

    async def blocked_query(**_kwargs):
        await asyncio.Event().wait()

    channel._check_e2ee_device_keys = AsyncMock(side_effect=blocked_query)
    monkeypatch.setattr(
        "qwenpaw.app.channels.matrix.channel._E2EE_HEALTH_TIMEOUT",
        0.01,
    )
    try:
        health = await channel.health_check()
        assert health["status"] == "unhealthy"
        assert "timed out" in health["detail"]
    finally:
        await channel.stop()
