"""Reuse native RSA/TLS service declarations without importing Azure in host.

The three external-only declarations below are copied from
azure_bot_native_support.py; production modules are never imported here.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.abc
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time
import venv
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import jwt
from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest
import pytest_asyncio

from g2_lifecycle_suite import copied_sdk

ISSUER = "https://api.botframework.com"
SERVICE = "https://connector.test"
APP = "test-azure-application"


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
    return key, other, server, client, cert


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


@pytest.fixture(autouse=True)
def azure_host_guard(monkeypatch):
    class NoAzure(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "msal" or fullname.startswith(
                ("msal.", "qwenpaw_channel_azure_bot")
            ):
                raise AssertionError(
                    "Azure runtime imported in host: " + fullname
                )

    assert not any(
        name == "msal"
        or name.startswith(("msal.", "qwenpaw_channel_azure_bot"))
        for name in sys.modules
    )
    monkeypatch.setattr(sys, "meta_path", [NoAzure(), *sys.meta_path])
    yield
    assert not any(
        name == "msal"
        or name.startswith(("msal.", "qwenpaw_channel_azure_bot"))
        for name in sys.modules
    )


@pytest_asyncio.fixture
async def formal_connector(rsa_material):
    connector = Connector(rsa_material[:4])
    connector.ca = rsa_material[4]
    connector.token_requests = []
    connector.auth_requests = []

    async def handle(request):
        if request.path == "/fixture-token":
            body = await request.json()
            assert body["app_id"] == APP
            assert body["scopes"] == ["https://api.botframework.com/.default"]
            connector.token_requests.append(body)
            return web.json_response(
                {"access_token": "local-issued-token", "expires_in": 3600}
            )
        if request.path in {"/v1/.well-known/openidconfiguration", "/keys"}:
            connector.auth_requests.append(request.path)
        return await connector.handle(request)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner, "127.0.0.1", 0, ssl_context=connector.server_ssl
    )
    await site.start()
    connector.port = site._server.sockets[0].getsockname()[1]
    try:
        yield connector
    finally:
        await runner.cleanup()


@pytest.fixture
# Offline exact installed distributions; no package download or fake metadata.
def azure_sdk_runtime(tmp_path, formal_connector):
    root = tmp_path / "sdk-runtime"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(root)
    python = root / "bin/python"
    site = next((root / "lib").glob("python*/site-packages"))
    pending = [
        "packaging",
        "jsonschema",
        "pydantic",
        "aiohttp",
        "PyJWT",
        "msal",
    ]
    copied = {}
    environment = {**default_environment(), "extra": ""}
    while pending:
        distribution = importlib.metadata.distribution(pending.pop())
        name = distribution.metadata["Name"].lower().replace("_", "-")
        if name in copied:
            continue
        copied[name] = distribution.version
        for requirement in distribution.requires or ():
            dependency = Requirement(requirement)
            if dependency.marker is None or dependency.marker.evaluate(
                environment
            ):
                pending.append(dependency.name)
        for relative in distribution.files or ():
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "__pycache__" in relative.parts
            ):
                continue
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                target = site / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    port, ca = formal_connector.port, str(formal_connector.ca)
    resolver = f"""
# Test-only external Azure HTTPS resolver. TLS and JWT remain real.
import socket as _socket
import ssl as _ssl
class _AzureResolver(abc.AbstractResolver):
    async def resolve(self, host, port=0, family=_socket.AF_INET):
        assert host in {{"login.botframework.com", "connector.test", "media.test"}}, host
        return [dict(hostname=host, host="127.0.0.1", port={port}, family=_socket.AF_INET, proto=0, flags=0)]
    async def close(self):
        pass
# Default DNS is an external boundary. The production attachment resolver still
# validates these public answers and hands numeric addresses to its connector.
from . import resolver as _azure_dns
import asyncio.selector_events as _azure_events
class _AzurePublicDNS(abc.AbstractResolver):
    async def resolve(self, host, port=0, family=_socket.AF_INET):
        assert host in {{"login.botframework.com", "connector.test", "media.test"}}, host
        return [dict(hostname=host, host="93.184.216.34", port=port, family=_socket.AF_INET, proto=_socket.IPPROTO_TCP, flags=0)]
    async def close(self):
        pass
_azure_dns.DefaultResolver = _AzurePublicDNS
_AzureConnect = _azure_events.BaseSelectorEventLoop.sock_connect
async def _azure_connect(self, sock, address):
    if address[0] == "93.184.216.34":
        assert address[1] == 443
        address = ("127.0.0.1", {port})
    return await _AzureConnect(self, sock, address)
_azure_events.BaseSelectorEventLoop.sock_connect = _azure_connect
_AzureSession = ClientSession
def ClientSession(*args, **kwargs):
    supplied = kwargs.pop("connector", None)
    context = _ssl.create_default_context(cafile={ca!r})
    if supplied is None:
        supplied = TCPConnector(resolver=_AzureResolver(), ssl=context)
    else:
        supplied._ssl = context
    return _AzureSession(*args, connector=supplied, **kwargs)
"""
    token = f"""
# Test-only external MSAL issuance; real synchronous TLS socket to local issuer.
class ConfidentialClientApplication:
    def __init__(self, client_id, **kwargs):
        assert kwargs["client_credential"] == "synthetic-azure-secret"
        assert kwargs["authority"] == "https://login.microsoftonline.com/test-tenant"
        self.client_id = client_id
    def acquire_token_for_client(self, *, scopes):
        import http.client, json, os, socket, ssl
        connection = http.client.HTTPSConnection("login.botframework.com", {port}, context=ssl.create_default_context(cafile={ca!r}))
        connection._create_connection = lambda address, *args, **kwargs: socket.create_connection(("127.0.0.1", {port}), *args, **kwargs)
        try:
            connection.request("POST", "/fixture-token", body=json.dumps({{"app_id": self.client_id, "scopes": scopes, "pid": os.getpid()}}), headers={{"Content-Type": "application/json"}})
            response = connection.getresponse()
            assert response.status == 200
            return json.loads(response.read())
        finally:
            connection.close()
"""
    # copied_sdk updates the real distribution RECORD for the boundary bytes.
    for dist, package, appended in (
        ("aiohttp", "aiohttp", resolver),
        ("msal", "msal", token),
    ):
        shutil.rmtree(site / package)
        info = next(site.glob(dist + "-*.dist-info"))
        shutil.rmtree(info)
        copied_sdk(
            tmp_path,
            dist,
            package,
            package + "/__init__.py",
            appended,
            site=site,
        )
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import json,platform,sys; from packaging.tags import sys_tags; print(json.dumps(dict(version=list(sys.version_info[:2]),implementation=sys.implementation.name,cache_tag=sys.implementation.cache_tag,sys_platform=sys.platform,system=platform.system(),machine=platform.machine(),supported_tags=[str(t) for t in sys_tags()])))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return SimpleNamespace(
        python=python,
        site=site,
        identity=json.loads(result.stdout),
        packages=copied,
    )
