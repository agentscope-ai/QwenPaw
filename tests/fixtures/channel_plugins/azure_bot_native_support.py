"""External Connector/JWKS/MSAL boundary, real TLS/JWT and private Driver."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import socket
import ssl
import sys
import time

import aiohttp
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import jwt
import pytest
import pytest_asyncio

from azure_bot_network_boundary import install_attachment_network

from g2_shared_response_suite import Peer
from qwenpaw.channel_protocol.models import (
    IdentityParams,
    EventBatchParams,
    EventBatchAck,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext

SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/azure_bot"
sys.path.insert(0, str(SOURCE))
driver_module = importlib.import_module("qwenpaw_channel_azure_bot.driver")
platform_module = importlib.import_module("qwenpaw_channel_azure_bot.platform")
state_module = importlib.import_module("qwenpaw_channel_azure_bot.state")
REAL_SESSION = aiohttp.ClientSession
ISSUER = "https://api.botframework.com"
SERVICE = "https://connector.test"
APP = "test-azure-application"


@pytest.fixture(scope="module")
def rsa_material(tmp_path_factory):
    directory = tmp_path_factory.mktemp("azure-keys")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test connector")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(name)
                    for name in (
                        "login.botframework.com",
                        "connector.test",
                        "media.test",
                        "api.botframework.com",
                        "smba.trafficmanager.net",
                        "botapi.skype.com",
                        "api.botframework.com.attacker.test",
                        "tenant.blob.core.windows.net",
                    )
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert = directory / "ca.pem"
    private = directory / "tls.pem"
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, private)
    client = ssl.create_default_context(cafile=str(cert))
    return key, other, server, client


class LocalResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, port):
        self.port = port

    async def resolve(self, host, port=0, family=socket.AF_INET):
        assert host in {"login.botframework.com", "connector.test", "media.test"}, host
        return [
            {
                "hostname": host,
                "host": "127.0.0.1",
                "port": self.port,
                "family": socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
        ]

    async def close(self):
        pass


class Connector:
    def __init__(self, material):
        self.key, self.other, self.server_ssl, self.client_ssl = material
        self.requests, self.keys, self.port = [], [], None
        self.upload_status, self.activity_status = 201, 200
        self.upload_body = {"id": "attachment/id"}
        self.token_calls, self.token_apps = 0, []
        self.reads = []
        self.download_handler = None
        self.download_headers = []
        key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.keys = [
            {
                **key,
                "kid": "key-one",
                "use": "sig",
                "endorsements": ["msteams", "slack", "webchat"],
            }
        ]

    def token(self, *, overrides=None, signer=None, kid="key-one", algorithm="RS256"):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": APP,
            "exp": now + 3600,
            "nbf": now - 10,
            "serviceurl": SERVICE,
        }
        claims.update(overrides or {})
        claims = {name: value for name, value in claims.items() if value is not None}
        return jwt.encode(
            claims, signer or self.key, algorithm=algorithm, headers={"kid": kid}
        )

    async def handle(self, request):
        if request.path == "/v1/.well-known/openidconfiguration":
            return web.json_response(
                {"issuer": ISSUER, "jwks_uri": "https://login.botframework.com/keys"}
            )
        if request.path == "/keys":
            return web.json_response({"keys": self.keys})
        if request.path.startswith("/download/"):
            self.download_headers.append(request.headers.copy())
            self.requests.append(
                ("download", request.path, request.headers.get("Authorization"))
            )
            if self.download_handler is not None:
                return await self.download_handler(request)
            if request.path == "/download/redirect":
                raise web.HTTPFound("https://media.test/download/target")
            if request.path == "/download/missing":
                return web.Response(status=404)
            return web.Response(
                body=b"\x89PNG\r\n\x1a\nimage", content_type="image/png"
            )
        body = await request.json()
        self.requests.append(
            (request.raw_path, body, request.headers.get("Authorization"))
        )
        if request.path.endswith("/attachments"):
            return web.json_response(self.upload_body, status=self.upload_status)
        return web.json_response(
            {"id": "activity-" + str(len(self.requests))}, status=self.activity_status
        )


@pytest_asyncio.fixture
async def connector(monkeypatch, rsa_material):
    boundary = Connector(rsa_material)
    application = web.Application()
    application.router.add_route("*", "/{path:.*}", boundary.handle)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=boundary.server_ssl)
    await site.start()
    boundary.port = site._server.sockets[0].getsockname()[1]

    install_attachment_network(monkeypatch, boundary)

    def session(**kwargs):
        supplied = kwargs.pop("connector", None)
        if supplied is None:
            supplied = aiohttp.TCPConnector(
                resolver=LocalResolver(boundary.port), ssl=boundary.client_ssl
            )
        else:
            # Retain the production DNS validator/connector and real TLS/SNI.
            supplied._ssl = boundary.client_ssl
        return REAL_SESSION(connector=supplied, **kwargs)

    monkeypatch.setattr(platform_module.aiohttp, "ClientSession", session)

    class MsalBoundary:
        def __init__(self, app_id, **kwargs):
            boundary.token_apps.append((app_id, kwargs))

        def acquire_token_for_client(self, *, scopes):
            assert scopes == ["https://api.botframework.com/.default"]
            boundary.token_calls += 1
            return {
                "access_token": "access-" + str(boundary.token_calls),
                "expires_in": 3600,
            }

    monkeypatch.setattr(
        platform_module.msal, "ConfidentialClientApplication", MsalBoundary
    )
    original_read = web.Request.read

    async def observed_read(request):
        if request.path == "/api/messages":
            boundary.reads.append(request.headers.get("Authorization"))
        return await original_read(request)

    monkeypatch.setattr(web.Request, "read", observed_read)
    try:
        yield boundary
    finally:
        await runner.cleanup()


class HostBoundary(Peer):
    """Records only private context RPC; this is not an actual host/Agent test."""

    def __init__(self):
        super().__init__()
        self.methods, self.state, self.events, self.calls, self.notifications = (
            {},
            {},
            [],
            [],
            [],
        )
        self.bad_ack = False

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def notify(self, name, params):
        self.notifications.append((name, params))

    async def call(self, name, params):
        if name.startswith("host.receipt."):
            return await super().call(name, params)
        self.calls.append((name, params))
        if name == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if name == "host.state.put":
            self.state[params["key"]] = params["value"]
            return {"status": "stored"}
        if name == "event.batch":
            batch = EventBatchParams.from_mapping(params)
            self.events.extend(batch.events)
            return EventBatchAck(
                batch_id=batch.batch_id,
                accepted_event_ids=tuple(event.event_id for event in batch.events),
            ).to_mapping()
        if name.startswith("ingress.endpoint."):
            operation = name.rsplit(".", 1)[1]
            result = {
                "status": {
                    "register": "registered",
                    "update": "updated",
                    "unregister": "unregistered",
                }[operation],
                "generation": params["generation"],
            }
            if operation != "unregister":
                result["readiness"] = params["readiness"]
            if self.bad_ack and operation != "unregister":
                result["status"] = "wrong"
            return result
        raise AssertionError(name)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def azure(connector, tmp_path):
    drivers = []

    @asynccontextmanager
    async def create(**overrides):
        peer = HostBoundary()
        driver = driver_module.AzureBotDriver()
        identity = IdentityParams("azure_bot", "azure-test-" + str(len(drivers)), 1)
        driver.bind(
            DriverContext(
                peer,
                identity,
                (
                    "channel.generic.v1",
                    "media",
                    "ingress_endpoint",
                    "send.content_source.v1",
                ),
            )
        )
        config = {
            "enabled": True,
            "app_id": APP,
            "app_password": "dummy-secret",
            "tenant_id": "test-tenant",
            "workspace_dir": str(tmp_path / str(len(drivers))),
            "http_host": "127.0.0.1",
            "http_port": free_port(),
        }
        config.update(overrides)
        drivers.append(driver)
        await driver.start(config)
        try:
            yield driver, peer
        finally:
            if driver._platform is not None:
                await driver.stop()

    try:
        yield create
    finally:
        for driver in drivers:
            if driver._platform is not None:
                await driver.stop()


def activity(**changes):
    value = {
        "type": "message",
        "id": "native-activity-1",
        "channelId": "msteams",
        "serviceUrl": SERVICE,
        "from": {
            "id": "channel-user-000001",
            "aadObjectId": "aad-user-123456",
            "name": "Ada",
        },
        "recipient": {"id": "native-bot"},
        "conversation": {"id": "conversation-ABCDEFGHIJ"},
        "text": "hello",
    }
    value.update(changes)
    return value


async def post(driver, connector, body, *, token=None, path="/api/messages"):
    async with REAL_SESSION(timeout=aiohttp.ClientTimeout(total=5)) as session:
        async with session.post(
            "http://127.0.0.1:" + str(driver._platform.port) + path,
            json=body,
            headers={"Authorization": "Bearer " + (token or connector.token())},
        ) as response:
            return response.status, await response.text()
