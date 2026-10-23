"""Real loopback QQ services; no replacement of Driver or native clients."""

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import threading

import pytest
import pytest_asyncio
from websockets.sync.server import serve

from g2_shared_response_suite import Peer
from qwenpaw.channel_protocol.models import IdentityParams, SendParams
from qwenpaw.channel_protocol.shared_worker import DriverContext

ROOT = Path(__file__).resolve().parents[3]


async def eventually(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class QQExternal:
    """Script only external HTTP bodies and QQ gateway wire messages."""

    def __init__(self, directory, *, tls=False):
        self.calls, self.frames, self.connections = [], [], []
        self.actions = defaultdict(deque)
        self.assets = {}
        self.lock = threading.Lock()
        self.body_entered, self.body_release = (
            threading.Event(),
            threading.Event(),
        )
        self.connection_closed = threading.Event()
        self.http_thread = self.ws_thread = None
        self.http = self.ws = None
        self.cert = None
        self.tls, self.directory = tls, directory

    def queue(self, method, path, *actions):
        with self.lock:
            self.actions[method, path].extend(actions)

    def rows(self, path=None):
        with self.lock:
            return [
                dict(r)
                for r in self.calls
                if path is None or r["path"] == path
            ]

    def api_rows(self):
        return [
            r for r in self.rows() if r["path"] not in {"/token", "/gateway"}
        ]

    def start(self):
        external = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def handle_request(self):
                raw = self.rfile.read(
                    int(self.headers.get("Content-Length", 0))
                )
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                row = {
                    "method": self.command,
                    "path": self.path,
                    "body": body,
                    "raw": raw,
                    "content_type": self.headers.get("Content-Type", ""),
                    "auth": self.headers.get("Authorization", ""),
                }
                with external.lock:
                    external.calls.append(row)
                    n = len(external.calls)
                    actions = external.actions[self.command, self.path]
                    action = actions.popleft() if actions else None
                if callable(action):
                    action = action(row)
                if action == "disconnect":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if action == "hold-body":
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    external.body_entered.set()
                    external.body_release.wait(5)
                    self.close_connection = True
                    return
                if action is not None:
                    status, payload = action
                elif self.path == "/token":
                    status, payload = 200, {
                        "access_token": "native-token",
                        "expires_in": 7200,
                    }
                elif self.path == "/gateway":
                    status, payload = 200, {"url": external.ws_url}
                elif self.path.endswith("/files"):
                    status, payload = 200, {"file_info": "native-file-info"}
                elif self.path in external.assets:
                    status, payload = 200, external.assets[self.path]
                else:
                    status, payload = 200, {"id": "native-" + str(n)}
                response = (
                    payload
                    if isinstance(payload, bytes)
                    else json.dumps(payload).encode()
                )
                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    (
                        "application/json"
                        if not isinstance(payload, bytes)
                        else "application/octet-stream"
                    ),
                )
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                try:
                    self.wfile.write(response)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_POST = do_GET = do_PUT = handle_request

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if self.tls:
            self._certificate()
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.cert, self.directory / "key.pem")
            self.http.socket = context.wrap_socket(
                self.http.socket, server_side=True
            )
        self.http_thread = threading.Thread(
            target=lambda: self.http.serve_forever(poll_interval=0.01),
            name="qq-test-http",
        )
        self.http_thread.start()
        if not self.tls:
            self.ws = serve(self._gateway, "127.0.0.1", 0, close_timeout=1)
            self.ws_thread = threading.Thread(
                target=self.ws.serve_forever, name="qq-test-ws"
            )
            self.ws_thread.start()
        return self

    def _certificate(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]
        )
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(1)
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        self.cert = self.directory / "cert.pem"
        self.cert.write_bytes(
            certificate.public_bytes(serialization.Encoding.PEM)
        )
        (self.directory / "key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )

    @property
    def base(self):
        return f"{'https' if self.tls else 'http'}://127.0.0.1:{self.http.server_port}"

    @property
    def ws_url(self):
        return f"ws://127.0.0.1:{self.ws.socket.getsockname()[1]}"

    def _gateway(self, connection):
        with self.lock:
            self.connections.append(connection)
        connection.send(
            json.dumps({"op": 10, "d": {"heartbeat_interval": 100}})
        )
        try:
            for raw in connection:
                value = json.loads(raw)
                with self.lock:
                    self.frames.append(value)
                if value["op"] == 2:
                    self.push(
                        {
                            "op": 0,
                            "s": 1,
                            "t": "READY",
                            "d": {"session_id": "native-session"},
                        },
                        connection,
                    )
                elif value["op"] == 6:
                    self.push({"op": 0, "t": "RESUMED", "d": {}}, connection)
                elif value["op"] == 1:
                    self.push({"op": 11}, connection)
        except Exception:
            pass
        finally:
            self.connection_closed.set()

    def push(self, payload, connection=None):
        (connection or self.connections[-1]).send(json.dumps(payload))

    def stop(self):
        self.body_release.set()
        for connection in self.connections:
            connection.close()
        if self.ws is not None:
            self.ws.shutdown()
        if self.http is not None:
            self.http.shutdown()
            self.http.server_close()
        for thread in (self.ws_thread, self.http_thread):
            if thread is not None:
                thread.join(3)
                assert not thread.is_alive(), thread.name


class HostBoundary(Peer):
    """Public state/admission fake; this is not Core or Agent evidence."""

    def __init__(self):
        super().__init__()
        self.methods, self.state, self.batches, self.notifications = (
            {},
            {},
            [],
            [],
        )
        self.admissions = deque()
        self.admission_entered = asyncio.Event()
        self.admission_release = None

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, name, params):
        if name.startswith("host.receipt."):
            return await super().call(name, params)
        if name == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if name == "host.state.put":
            self.state[params["key"]] = json.loads(json.dumps(params["value"]))
            return {}
        assert name == "event.batch", name
        self.batches.append(params)
        self.admission_entered.set()
        if self.admission_release is not None:
            await self.admission_release.wait()
        if self.admissions:
            result = self.admissions.popleft()
            if isinstance(result, Exception):
                raise result
            return {"batch_id": params["batch_id"], **result}
        return {
            "batch_id": params["batch_id"],
            "accepted_event_ids": [params["events"][0]["event_id"]],
        }

    async def notify(self, name, params):
        self.notifications.append((name, params))


@pytest.fixture
def external(tmp_path, monkeypatch):
    value = QQExternal(tmp_path).start()
    monkeypatch.setenv("QQ_API_BASE", value.base)
    monkeypatch.setenv("QQ_TOKEN_URL", value.base + "/token")
    try:
        yield value
    finally:
        value.stop()


@pytest_asyncio.fixture
async def native_driver(external, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/qq"))
    from qwenpaw_channel_qq.driver import QQDriver

    driver, peer = QQDriver(), HostBoundary()
    identity = IdentityParams("qq", "native-workspace-A", 1)
    descriptor = json.loads(
        (ROOT / "plugins/channel/qq/channel.json").read_text()
    )
    driver.bind(DriverContext(peer, identity, descriptor["capabilities"]))
    try:
        await driver.start(
            {
                "app_id": "local-app",
                "client_secret": "local-secret",
                "workspace_dir": str(tmp_path),
                "bot_prefix": "[Bot] ",
                "markdown_enabled": True,
            }
        )
        await eventually(lambda: driver._connected)
        yield driver, peer, identity.to_mapping(), external
    finally:
        if peer.admission_release is not None:
            peer.admission_release.set()
        await driver.stop()


async def open_route(peer, identity, target="qq:c2c:user-A", **meta):
    result = await peer.methods["channel.response.open"](
        {**identity, "to_handle": target, "meta": meta}, None
    )
    return result["response_handle"]


async def send(
    peer,
    identity,
    handle,
    parts,
    *,
    delivery="delivery-A",
    source="direct",
    **fields,
):
    params = SendParams.from_mapping(
        {
            **identity,
            "to_handle": handle,
            "delivery_id": delivery,
            "operation": "message.create",
            "content_parts": parts,
            "content_source": source,
            **fields,
        }
    )
    return await peer.methods["channel.send"](params, None)


@pytest.fixture
def portal(tmp_path, monkeypatch):
    value = QQExternal(tmp_path, tls=True).start()
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/qq"))
    monkeypatch.setenv("QQ_PORTAL_HOST", f"localhost:{value.http.server_port}")
    monkeypatch.setenv("SSL_CERT_FILE", str(value.cert))
    try:
        yield value
    finally:
        value.stop()
