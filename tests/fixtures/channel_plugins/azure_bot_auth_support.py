"""Auth-only external TLS/JWKS helpers; copied original boundary declarations.

No Driver, platform, shared response or Proxy import is needed for auth checks.
"""
from datetime import datetime, timedelta, timezone
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/azure_bot"))
APP = "test-azure-application"
ISSUER = "https://api.botframework.com"
SERVICE = "https://connector.test"
REAL_SESSION = aiohttp.ClientSession


@pytest.fixture(scope="module")
def rsa_material(tmp_path_factory):
    directory = tmp_path_factory.mktemp("azure-keys")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "test connector")]
    )
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
                    )
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
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
        assert host in {
            "login.botframework.com",
            "connector.test",
            "media.test",
        }, host
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
        key = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key())
        )
        self.keys = [
            {
                **key,
                "kid": "key-one",
                "use": "sig",
                "endorsements": ["msteams", "slack", "webchat"],
            }
        ]

    def token(
        self, *, overrides=None, signer=None, kid="key-one", algorithm="RS256"
    ):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": APP,
            "exp": now + 3600,
            "nbf": now - 10,
            "serviceurl": SERVICE,
        }
        claims.update(overrides or {})
        claims = {
            name: value for name, value in claims.items() if value is not None
        }
        return jwt.encode(
            claims,
            signer or self.key,
            algorithm=algorithm,
            headers={"kid": kid},
        )

    async def handle(self, request):
        if request.path == "/v1/.well-known/openidconfiguration":
            return web.json_response(
                {
                    "issuer": ISSUER,
                    "jwks_uri": "https://login.botframework.com/keys",
                }
            )
        if request.path == "/keys":
            return web.json_response({"keys": self.keys})
        if request.path.startswith("/download/"):
            self.requests.append(
                (
                    "download",
                    request.path,
                    request.headers.get("Authorization"),
                )
            )
            return web.Response(
                body=b"\x89PNG\r\n\x1a\nimage", content_type="image/png"
            )
        body = await request.json()
        self.requests.append(
            (request.raw_path, body, request.headers.get("Authorization"))
        )
        if request.path.endswith("/attachments"):
            return web.json_response(
                self.upload_body, status=self.upload_status
            )
        return web.json_response(
            {"id": "activity-" + str(len(self.requests))},
            status=self.activity_status,
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

    monkeypatch.setattr(aiohttp, "ClientSession", session)
    try:
        yield boundary
    finally:
        await runner.cleanup()
