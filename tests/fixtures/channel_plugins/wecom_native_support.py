"""Actual aibot 1.0.2 over verified loopback TLS; only host/platform peers fake."""

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import ssl
import threading

import pytest
import pytest_asyncio
from websockets.sync.server import serve

from qwenpaw.channel_protocol.models import IdentityParams, SendParams
from qwenpaw.channel_protocol.shared_worker import DriverContext
from qq_native_support import HostBoundary

ROOT = Path(__file__).resolve().parents[3]


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


class WeComExternal:
    def __init__(self, directory):
        self.directory = directory
        self.frames, self.actions = [], defaultdict(deque)
        self.lock = threading.Lock()
        self.connection = None
        self.connections = []
        self.thread = self.server = None
        self.closed = threading.Event()

    def start(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]), critical=False).sign(key, hashes.SHA256())
        )
        self.cert = self.directory / "wecom-cert.pem"
        self.cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        private = self.directory / "wecom-key.pem"
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, private)
        self.server = serve(self._gateway, "127.0.0.1", 0, ssl=context, close_timeout=1)
        self.thread = threading.Thread(target=self.server.serve_forever, name="wecom-test-gateway")
        self.thread.start()
        return self

    @property
    def url(self):
        return f"wss://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def rows(self, cmd=None):
        with self.lock:
            return [json.loads(json.dumps(row)) for row in self.frames if cmd is None or row["cmd"] == cmd]

    def queue(self, cmd, action):
        with self.lock:
            self.actions[cmd].append(action)

    def _gateway(self, connection):
        with self.lock:
            self.connection = connection
            self.connections.append(connection)
        try:
            for raw in connection:
                frame = json.loads(raw)
                cmd = frame["cmd"]
                with self.lock:
                    self.frames.append(frame)
                    action = self.actions[cmd].popleft() if self.actions[cmd] else None
                if action == "disconnect":
                    connection.close()
                    break
                body = {}
                if cmd == "aibot_upload_media_init":
                    body = {"upload_id": "native-upload"}
                elif cmd == "aibot_upload_media_finish":
                    body = {"media_id": "native-media"}
                if isinstance(action, dict):
                    body = action
                if frame.get("headers", {}).get("req_id"):
                    connection.send(json.dumps({
                        "headers": frame["headers"], "errcode": 0,
                        "errmsg": "ok", "body": body,
                    }))
        finally:
            with self.lock:
                if self.connection is connection:
                    self.connection = None
            self.closed.set()

    def push(self, frame):
        with self.lock:
            connection = self.connection
        assert connection is not None
        connection.send(json.dumps(frame))

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
        if self.thread is not None:
            self.thread.join(3)
            assert not self.thread.is_alive()


@pytest.fixture
def wecom_external(tmp_path, monkeypatch):
    import certifi
    import certifi.core
    server = WeComExternal(tmp_path).start()
    # Trust only this test CA; SDK retains CERT_REQUIRED and hostname checks.
    monkeypatch.setattr(certifi, "where", lambda: str(server.cert))
    monkeypatch.setattr(certifi.core, "where", certifi.where)
    import aibot.ws
    context = ssl.create_default_context(cafile=str(server.cert))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    # SDK caches its trust context at import; replace only the test trust roots.
    monkeypatch.setattr(aibot.ws, "_SSL_CONTEXT", context)
    try:
        yield server
    finally:
        server.stop()


@pytest_asyncio.fixture
async def wecom_native(wecom_external, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/wecom"))
    from qwenpaw_channel_wecom.driver import WeComDriver
    driver, peer = WeComDriver(), HostBoundary()
    identity = IdentityParams("wecom", "native-wecom-A", 1)
    capabilities = json.loads((ROOT / "plugins/channel/wecom/channel.json").read_text(encoding="utf-8"))["capabilities"]
    driver.bind(DriverContext(peer, identity, capabilities))
    try:
        await driver.start({
            "bot_id": "native-bot", "secret": "native-secret",
            "ws_url": wecom_external.url, "workspace_dir": str(tmp_path),
            "streaming_enabled": True,
        })
        await eventually(lambda: driver._connected)
        yield driver, peer, identity.to_mapping(), wecom_external
    finally:
        if driver._platform is not None:
            await driver.stop()


def text_frame(mid="native-msg", *, group=False, actor="sender-A"):
    return {
        "cmd": "aibot_msg_callback", "headers": {"req_id": "cb-" + mid},
        "body": {
            "msgtype": "text", "msgid": mid,
            "chatid": "group-A" if group else "chat-A",
            "chattype": "group" if group else "single",
            "from": {"userid": actor}, "text": {"content": "hello native"},
        },
    }


async def ingress(native, frame=None):
    driver, peer, identity, server = native
    previous = len(peer.batches)
    server.push(frame or text_frame())
    await eventually(lambda: len(peer.batches) > previous)
    return peer.batches[-1]["events"][0]


async def send(native, handle, *, delivery="delivery-A", operation="message.create", **fields):
    driver, peer, identity, server = native
    params = SendParams.from_mapping({
        **identity, "to_handle": handle, "delivery_id": delivery,
        "operation": operation, **fields,
    })
    return await peer.methods["channel.send"](params, None)


async def prepare(native, handle):
    driver, peer, identity, server = native
    return await peer.methods["channel.response.prepare"]({
        **identity, "response_handle": handle,
        "delivery_id": hashlib.sha256((handle + ":prepare").encode()).hexdigest(),
    }, None)
