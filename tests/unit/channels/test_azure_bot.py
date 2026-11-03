# -*- coding: utf-8 -*-
"""Azure validates signed Activity JWTs before native webhook admission."""

import asyncio
import json
import socket
import time

import aiohttp
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import send

REAL_SESSION = aiohttp.ClientSession
SERVICE = "https://connector.test"
APP_ID = "azure-test-app"


class Response:
    status = 200

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def json(self):
        return self.value

    async def read(self):
        return json.dumps(self.value).encode()


class ConnectorSession:
    """Connector HTTP boundary with real JWT validation."""

    def __init__(self, key):
        self.key, self.requests, self.closed = key, [], False

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        if url.endswith("/keys"):
            return Response({"keys": [self.key]})
        return Response(
            {
                "issuer": "https://api.botframework.com",
                "jwks_uri": "https://login.botframework.com/keys",
            },
        )

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return Response({"id": "native-reply-id"})

    async def close(self):
        self.closed = True


class Credentials:
    def __init__(self, app_id, authority, client_credential):
        assert app_id == APP_ID and client_credential == "local-secret"
        assert (
            authority == "https://login.microsoftonline.com/botframework.com"
        )

    def acquire_token_for_client(self, scopes):
        assert scopes == ["https://api.botframework.com/.default"]
        return {"access_token": "connector-token", "expires_in": 3600}


@pytest.fixture
async def azure(tmp_path, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = {
        **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())),
        "kid": "test-key",
        "endorsements": ["msteams"],
    }
    external = ConnectorSession(key)
    native = module("azure_bot", "platform")
    monkeypatch.setattr(
        native.aiohttp,
        "ClientSession",
        lambda **kwargs: external,
    )
    monkeypatch.setattr(
        native.msal,
        "ConfidentialClientApplication",
        Credentials,
    )
    # Reserve a free loopback port; Driver owns the actual aiohttp listener.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    driver = module("azure_bot").AzureBotDriver()
    peer, identity = bind("azure_bot", driver, tmp_path)
    try:
        await driver.start(
            dict(
                enabled=True,
                app_id=APP_ID,
                app_password="local-secret",
                workspace_dir=str(tmp_path),
                http_host="127.0.0.1",
                http_port=port,
                require_mention=True,
                share_session_in_group=True,
            ),
        )
        yield driver, peer, identity, private, external
    finally:
        await driver.stop()


def activity(group=False, mentioned=False):
    return {
        "type": "message",
        "id": "activity-A",
        "channelId": "msteams",
        "serviceUrl": SERVICE,
        "from": {
            "id": "channel-user",
            "aadObjectId": "aad-user-123456",
            "name": "Ada",
        },
        "recipient": {"id": "native-bot"},
        "conversation": {"id": "conversation-ABCDEFGHIJ", "isGroup": group},
        "text": "<at>Paw</at> hello" if mentioned else "hello",
        "entities": (
            [
                {
                    "type": "mention",
                    "mentioned": {"id": "native-bot"},
                    "text": "<at>Paw</at>",
                },
            ]
            if mentioned
            else []
        ),
    }


def token(private, **changes):
    now = int(time.time())
    claims = {
        "iss": "https://api.botframework.com",
        "aud": APP_ID,
        "nbf": now - 10,
        "exp": now + 3600,
        "serviceurl": SERVICE,
        **changes,
    }
    return jwt.encode(
        claims,
        private,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


async def post(value, body, auth=None):
    driver, _, _, private, _ = value
    async with REAL_SESSION() as client:
        async with client.post(
            f"http://127.0.0.1:{driver._platform.port}/api/messages",
            json=body,
            headers={"Authorization": "Bearer " + (auth or token(private))},
        ) as response:
            return response.status


async def test_signed_activity_keeps_acl_identity_and_conversation(
    azure,
):
    _, peer, identity, _, external = azure
    assert await post(azure, activity()) == 200
    event = peer.batches[0]["events"][0]
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert (
        event["acl_sender_id"] == "aad-user-123456"
        and event["sender_name"] == "Ada"
    )
    assert event["conversation"] == {
        "id": "conversation-ABCDEFGHIJ",
        "type": "dm",
        "thread_id": None,
    }
    assert event["event_id"] == "msteams:conversation-ABCDEFGHIJ:activity-A"
    assert [request[0] for request in external.requests] == ["GET", "GET"]
    assert identity.instance_id == event["instance_id"]


@pytest.mark.parametrize(
    "group,mentioned,admitted",
    [(True, False, False), (True, True, True)],
)
async def test_group_requires_native_mention_and_uses_shared_group_identity(
    azure,
    group,
    mentioned,
    admitted,
):
    _, peer, identity, _, external = azure
    assert await post(azure, activity(group, mentioned)) == 200
    assert bool(peer.batches) is admitted
    if admitted:
        event = peer.batches[0]["events"][0]
        assert (
            event["sender_id"] == "group"
            and event["acl_sender_id"] == "aad-user-123456"
        )
        assert event["conversation"]["type"] == "group"
        assert event["metadata"]["bot_mentioned"] is True
        assert event["content_parts"] == [{"type": "text", "text": "hello"}]

        handle = peer.batches[0]["events"][0]["response_handle"]
        assert (await send(peer, identity, handle))["state"] == "acknowledged"
        method, url, kwargs = external.requests[-1]
        assert (
            method == "POST"
            and url
            == SERVICE + "/v3/conversations/conversation-ABCDEFGHIJ/activities"
        )
        assert kwargs["headers"] == {"Authorization": "Bearer connector-token"}
        assert kwargs["json"] == {
            "type": "message",
            "from": {"id": "native-bot"},
            "text": "native answer",
        }
        assert kwargs["allow_redirects"] is False


async def test_invalid_audience_or_service_binding_never_admits(azure):
    _, peer, _, private, _ = azure
    assert (
        await post(azure, activity(), token(private, aud="foreign-app")) == 401
    )
    assert (
        await post(
            azure,
            activity(),
            token(private, serviceurl="https://other.test"),
        )
        == 403
    )
    assert not peer.batches


async def test_stop_releases_webhook_watchdog_and_unregisters_endpoint(azure):
    driver, peer, _, _, external = azure
    platform = driver._platform
    watchdog, port = platform.watchdog, platform.port
    await driver.stop()
    assert external.closed and watchdog.done() and platform.runner is None
    assert driver._platform is None
    assert peer.calls[-1][0] == "ingress.endpoint.unregister"
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", port)
