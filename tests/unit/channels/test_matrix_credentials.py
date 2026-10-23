# -*- coding: utf-8 -*-
"""Matrix credential input regressions using real matrix-nio HTTP requests."""

# pylint: disable=protected-access,redefined-outer-name

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from qwenpaw.app.channels.matrix import channel as matrix_module
from qwenpaw.app.channels.matrix.channel import MatrixChannel


USER_ID = "@bot:example.com"
ACCESS_TOKEN = "Local-Test_Token.1"
PASSWORD = "  preserve password whitespace \t"


async def unused_process(*_args, **_kwargs):
    """Authentication does not process agent messages."""
    raise AssertionError("No agent message expected")


@pytest.fixture
async def matrix_homeserver(tmp_path, monkeypatch):
    """Run a strict local homeserver and isolate persisted Matrix state."""
    monkeypatch.setattr(matrix_module, "WORKING_DIR", tmp_path)
    requests = []

    async def whoami(request):
        authorization = request.headers.get("Authorization", "")
        requests.append(authorization)
        if authorization != f"Bearer {ACCESS_TOKEN}":
            return web.json_response(
                {"errcode": "M_UNKNOWN_TOKEN", "error": "Invalid token"},
                status=401,
            )
        return web.json_response(
            {"user_id": USER_ID, "device_id": "TEST_DEVICE"},
        )

    async def login(request):
        payload = await request.json()
        requests.append(payload)
        if (
            payload.get("identifier", {}).get("user") != USER_ID
            or payload.get("password") != PASSWORD
        ):
            return web.json_response(
                {"errcode": "M_FORBIDDEN", "error": "Invalid credentials"},
                status=403,
            )
        return web.json_response(
            {
                "user_id": USER_ID,
                "access_token": ACCESS_TOKEN,
                "device_id": "TEST_DEVICE",
            },
        )

    async def sync(_request):
        return web.json_response({"next_batch": "test-batch", "rooms": {}})

    app = web.Application()
    app.router.add_get("/_matrix/client/v3/account/whoami", whoami)
    app.router.add_post("/_matrix/client/v3/login", login)
    app.router.add_get("/_matrix/client/v3/sync", sync)
    async with TestServer(app) as server:
        yield str(server.make_url("")).rstrip("/"), requests


@pytest.mark.parametrize(
    "user_id,access_token,padded_server",
    [
        (USER_ID, ACCESS_TOKEN, False),
        (f" {USER_ID} ", ACCESS_TOKEN, False),
        (USER_ID, f" {ACCESS_TOKEN} ", False),
        (f"\t{USER_ID}\n", f"\n{ACCESS_TOKEN}\t", True),
    ],
    ids=["clean", "pasted-user-id", "pasted-token", "pasted-all"],
)
async def test_pasted_credentials_start_real_matrix_client(
    matrix_homeserver,
    user_id,
    access_token,
    padded_server,
):
    """Pasted whitespace must not change authentication or owner checks."""
    homeserver, requests = matrix_homeserver
    channel = MatrixChannel.from_config(
        process=unused_process,
        config={
            "homeserver": f" {homeserver}/// \t"
            if padded_server
            else homeserver,
            "user_id": user_id,
            "access_token": access_token,
        },
    )
    try:
        await asyncio.wait_for(channel.start(), timeout=5)
        assert requests == [f"Bearer {ACCESS_TOKEN}"]
        assert channel._user_id == USER_ID
        assert channel._sync_task is not None
        assert channel.homeserver == homeserver
    finally:
        await channel.stop()


@pytest.mark.parametrize(
    "user_id,access_token",
    [("@other:example.com", ACCESS_TOKEN), (USER_ID, "Local- Test_Token.1")],
    ids=["different-owner", "internal-token-space"],
)
async def test_invalid_credentials_are_still_rejected(
    matrix_homeserver,
    user_id,
    access_token,
):
    """Boundary cleanup must preserve token and account identity checks."""
    homeserver, requests = matrix_homeserver
    channel = MatrixChannel(
        process=unused_process,
        homeserver=homeserver,
        matrix_user_id=user_id,
        access_token=access_token,
    )
    try:
        await asyncio.wait_for(channel.start(), timeout=5)
        assert requests == [f"Bearer {access_token}"]
        assert channel._user_id is None
        assert channel._sync_task is None
    finally:
        await channel.stop()


async def test_password_whitespace_is_preserved(matrix_homeserver):
    """A password's surrounding spaces remain part of the secret."""
    homeserver, requests = matrix_homeserver
    channel = MatrixChannel.from_config(
        process=unused_process,
        config={
            "homeserver": homeserver,
            "user_id": f" {USER_ID} ",
            "password": PASSWORD,
        },
    )
    try:
        await asyncio.wait_for(channel.start(), timeout=5)
        assert requests[0]["password"] == PASSWORD
        assert channel._user_id == USER_ID
        assert channel._sync_task is not None
    finally:
        await channel.stop()


async def test_pasted_environment_token(matrix_homeserver, monkeypatch):
    """Environment credentials share the constructor's input boundary."""
    homeserver, requests = matrix_homeserver
    monkeypatch.setenv("HICLAW_MATRIX_SERVER", f" {homeserver}/ ")
    monkeypatch.setenv("HICLAW_MATRIX_TOKEN", f" {ACCESS_TOKEN} ")
    channel = MatrixChannel.from_env(process=unused_process)
    try:
        await asyncio.wait_for(channel.start(), timeout=5)
        assert requests == [f"Bearer {ACCESS_TOKEN}"]
        assert channel._user_id == USER_ID
        assert channel._sync_task is not None
    finally:
        await channel.stop()
