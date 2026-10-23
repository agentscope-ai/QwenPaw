"""Host CA trust reaches real runtime and supported management workers."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import ssl
import threading
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from qwenpaw.app.channels.process_supervisor import (
    ChannelProcess,
    ChannelProcessError,
)
from qwenpaw.plugins.execution.bootstrap import BootstrapError
from management_process_suite import (
    eventually,
    management_request,
    management_sample_source,
    management_spec,
)


def certificate(directory, name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            False,
        )
        .sign(key, hashes.SHA256())
    )
    ca, private = directory / (name + ".pem"), directory / (name + ".key")
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca, private


@pytest.fixture
def local_https(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"trusted-local-response"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    ca, private = certificate(tmp_path, "host authority")
    wrong_ca, _ = certificate(tmp_path, "unrelated authority")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, private)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, ca, wrong_ca
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def tls_sample(tmp_path, url):
    sample = management_sample_source(tmp_path, run_driver=True)
    sample.observation = tmp_path / "tls-observation.json"
    (sample.source / "management_sample/driver.py").write_text(
        "URL = " + repr(url) + "\n"
        "MARKER = " + repr(str(sample.marker)) + "\n"
        "OBSERVATION = "
        + repr(str(sample.observation))
        + "\n"
        + """import json, os
from pathlib import Path
import httpx

Path(MARKER).write_text(str(os.getpid()))
observed = {
    'ca': os.environ.get('SSL_CERT_FILE'),
    'pid': os.getpid(),
    'cwd': os.getcwd(),
    'filtered': {name: os.environ.get(name) for name in (
        'HOST_SECRET', 'PYTHONPATH', 'PYTHONHOME', 'SSL_CERT_DIR',
        'REQUESTS_CA_BUNDLE')},
}
# Build the default TLS context during entrypoint import, before start/manage.
client = httpx.AsyncClient(timeout=3)

async def fetch():
    try:
        async with client:
            response = await client.get(URL)
        result = {'status': response.status_code, 'body': response.text}
    except httpx.ConnectError as error:
        result = {'error': str(error)}
    Path(OBSERVATION).write_text(json.dumps({**observed, **result}))

class Driver:
    def bind(self, context): self.context = context
    async def start(self, config):
        await fetch()
        await self.context.set_platform_state('connected')
    async def stop(self): pass
    @staticmethod
    async def manage(request):
        await fetch()
        data = request.to_mapping()
        fields = ('request_id', 'plugin_id', 'workspace_id', 'channel_key',
                  'instance_id', 'generation', 'source_revision', 'operation')
        return {**{key: data[key] for key in fields}, 'outcome': 'ok',
                'reason_code': None, 'result': {
                    'scan_url': 'https://example.invalid/scan',
                    'continuation': 'tls-observed'}}
"""
    )
    return sample


async def exercise(process, spec, mode):
    if mode == "run":
        await process.start(replace(spec, enabled=True))
        await eventually(
            lambda: process.health_snapshot()["platform_state"] == "connected"
        )
    else:
        await process.start_management(spec)
        request = management_request(
            spec, SimpleNamespace(host="127.0.0.1", port=9)
        )
        result = await process.call(
            "channel.management.execute", request.to_mapping(), timeout=5
        )
        assert result["outcome"] == "ok"
        assert result["result"]["continuation"] == "tls-observed"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["run", "manage"])
@pytest.mark.parametrize(
    "trust", ["absolute", "relative", "missing", "empty", "wrong", "hostname"]
)
async def test_real_workers_preserve_host_ca_and_tls_verification(
    tmp_path, monkeypatch, local_https, mode, trust
):
    server, ca, wrong_ca = local_https
    monkeypatch.chdir(tmp_path)
    value = {
        "absolute": str(ca),
        "relative": ca.name,
        "missing": None,
        "empty": "",
        "wrong": str(wrong_ca),
        "hostname": str(ca),
    }[trust]
    if value is None:
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    else:
        monkeypatch.setenv("SSL_CERT_FILE", value)
    for name in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    for name in (
        "HOST_SECRET",
        "PYTHONPATH",
        "PYTHONHOME",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
    ):
        monkeypatch.setenv(name, str(tmp_path / "host-only-canary"))
    host = "localhost" if trust == "hostname" else "127.0.0.1"
    sample = tls_sample(tmp_path, f"https://{host}:{server.server_port}/")
    process = ChannelProcess()
    try:
        await exercise(process, management_spec(sample), mode)
        observed = json.loads(sample.observation.read_text())
        assert (
            observed["pid"] == process.health_snapshot()["pid"] != os.getpid()
        )
        assert observed["cwd"] == str(sample.source)
        assert observed["filtered"] == dict.fromkeys(
            (
                "HOST_SECRET",
                "PYTHONPATH",
                "PYTHONHOME",
                "SSL_CERT_DIR",
                "REQUESTS_CA_BUNDLE",
            )
        )
        if trust in {"absolute", "relative"}:
            assert observed.get("status") == 200, observed
            assert observed["body"] == "trusted-local-response"
        else:
            assert "status" not in observed
            assert "CERTIFICATE_VERIFY_FAILED" in observed["error"]
            if trust == "hostname":
                assert "Hostname mismatch" in observed["error"]
        assert observed["ca"] == (str(ca) if trust == "relative" else value)
    finally:
        cleanup = await process.stop()
        assert cleanup.exited and not cleanup.residual


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["run", "manage"])
@pytest.mark.parametrize(
    "name", ["SSL_CERT_FILE", "ssl_cert_file", "Ssl_Cert_File"]
)
async def test_private_ca_override_is_rejected_before_entrypoint_import(
    tmp_path, mode, name
):
    sample = tls_sample(tmp_path, "https://127.0.0.1:9/")
    spec = management_spec(sample)
    # Mutable mappings must be revalidated at launch, even after construction.
    spec.private_env[name] = "private-ca-canary.pem"
    process = ChannelProcess()
    try:
        with pytest.raises((BootstrapError, ChannelProcessError)) as rejected:
            await exercise(process, spec, mode)
        assert rejected.value.reason_code == "LAUNCH_ENVIRONMENT_INVALID"
        assert "private-ca-canary" not in str(rejected.value)
        assert process.health_snapshot()["pid"] is None
        assert not sample.marker.exists()
        assert not sample.observation.exists()
    finally:
        cleanup = await process.stop()
        assert cleanup.exited and not cleanup.residual
