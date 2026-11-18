# -*- coding: utf-8 -*-
"""WeCom native SDK over loopback TLS: stream, media, routing and shutdown."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import importlib
import json
import ssl
import sys
import threading
import pytest
import pytest_asyncio
from websockets.sync.server import serve
from qwenpaw.channel_protocol.models import SendParams
from tests.channel_support.driver import bind, module

pytestmark = pytest.mark.asyncio


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


class WeComExternal:
    def __init__(self, directory):
        self.directory = directory
        self.frames = []
        self.lock = threading.Lock()
        self.connection = None
        self.thread = self.server = None
        self.closed = threading.Event()

    def start(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "localhost")],
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
                    ],
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        self.cert = self.directory / "wecom-cert.pem"
        self.cert.write_bytes(
            certificate.public_bytes(serialization.Encoding.PEM),
        )
        private = self.directory / "wecom-key.pem"
        private.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, private)
        self.server = serve(
            self._gateway,
            "127.0.0.1",
            0,
            ssl=context,
            close_timeout=1,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="wecom-test-gateway",
        )
        self.thread.start()
        return self

    @property
    def url(self):
        return f"wss://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def rows(self, cmd=None):
        with self.lock:
            return [
                json.loads(json.dumps(row))
                for row in self.frames
                if cmd is None or row["cmd"] == cmd
            ]

    def _gateway(self, connection):
        with self.lock:
            self.connection = connection
        try:
            for raw in connection:
                frame = json.loads(raw)
                cmd = frame["cmd"]
                with self.lock:
                    self.frames.append(frame)
                body = {}
                if cmd == "aibot_upload_media_init":
                    body = {"upload_id": "native-upload"}
                elif cmd == "aibot_upload_media_finish":
                    body = {"media_id": "native-media"}
                if frame.get("headers", {}).get("req_id"):
                    connection.send(
                        json.dumps(
                            {
                                "headers": frame["headers"],
                                "errcode": 0,
                                "errmsg": "ok",
                                "body": body,
                            },
                        ),
                    )
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

    if not getattr(
        sys.modules.get("aibot"),
        "__file__",
        None,
    ) or not isinstance(
        getattr(sys.modules.get("aibot"), "__file__", None),
        str,
    ):
        monkeypatch.delitem(sys.modules, "aibot", raising=False)
    server = WeComExternal(tmp_path).start()
    # Trust only this test CA; SDK retains CERT_REQUIRED and hostname checks.
    monkeypatch.setattr(certifi, "where", lambda: str(server.cert))
    monkeypatch.setattr(certifi.core, "where", certifi.where)
    sdk_ws = importlib.import_module("aibot.ws")
    context = ssl.create_default_context(cafile=str(server.cert))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    # The SDK caches trust at import; replace only its test trust roots.
    monkeypatch.setattr(sdk_ws, "_SSL_CONTEXT", context)
    try:
        yield server
    finally:
        server.stop()


def text_frame(mid="native-msg", *, group=False, actor="sender-A"):
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "cb-" + mid},
        "body": {
            "msgtype": "text",
            "msgid": mid,
            "chatid": "group-A" if group else "chat-A",
            "chattype": "group" if group else "single",
            "from": {"userid": actor},
            "text": {"content": "hello native"},
        },
    }


async def ingress(native, frame=None):
    driver, peer, identity, server = native
    previous = len(peer.batches)
    server.push(frame or text_frame())
    await eventually(lambda: len(peer.batches) > previous)
    return peer.batches[-1]["events"][0]


async def send(
    native,
    handle,
    *,
    delivery="delivery-A",
    operation="message.create",
    **fields,
):
    driver, peer, identity, server = native
    params = SendParams.from_mapping(
        {
            **identity,
            "to_handle": handle,
            "delivery_id": delivery,
            "operation": operation,
            **fields,
        },
    )
    return await peer.methods["channel.send"](params, None)


async def prepare(native, handle):
    driver, peer, identity, server = native
    return await peer.methods["channel.response.prepare"](
        {
            **identity,
            "response_handle": handle,
            "delivery_id": hashlib.sha256(
                (handle + ":prepare").encode(),
            ).hexdigest(),
        },
        None,
    )


@pytest_asyncio.fixture
async def wecom_native(wecom_external, tmp_path):
    driver = module("wecom").WeComDriver()
    peer, identity = bind("wecom", driver, tmp_path)
    try:
        await driver.start(
            {
                "bot_id": "native-bot",
                "secret": "native-secret",
                "ws_url": wecom_external.url,
                "workspace_dir": str(tmp_path),
                "streaming_enabled": True,
            },
        )
        await eventually(lambda: driver._connected)
        yield driver, peer, identity.to_mapping(), wecom_external
    finally:
        if driver._platform is not None:
            await driver.stop()


async def test_native_subscribe_processing_first_stream_sid_and_final(
    wecom_native,
):
    driver, peer, identity, server = wecom_native
    assert server.rows("aibot_subscribe")[0]["body"] == {
        "bot_id": "native-bot",
        "secret": "native-secret",
    }
    event = await ingress(wecom_native)
    assert event["acl_sender_id"] == "sender-A"
    assert event["metadata"]["session_id"] == "wecom:sender-A"
    assert "frame" not in json.dumps(peer.batches)
    handle = event["response_handle"]
    assert (await prepare(wecom_native, handle))["state"] == "acknowledged"
    processing = server.rows("aibot_respond_msg")[-1]["body"]["stream"]
    assert (
        processing["content"] == "🤔 Thinking..."
        and processing["finish"] is False
    )
    assert (
        await send(
            wecom_native,
            handle,
            operation="stream.start",
            stream_type="message",
            sequence=0,
            accumulated_text="first",
        )
    )["state"] == "acknowledged"
    assert (
        await send(
            wecom_native,
            handle,
            delivery="end-A",
            operation="stream.end",
            target_delivery_id="delivery-A",
            stream_type="message",
            sequence=1,
            accumulated_text="final answer",
        )
    )["state"] == "acknowledged"
    streams = [r["body"]["stream"] for r in server.rows("aibot_respond_msg")]
    assert streams == [
        {"id": processing["id"], "finish": False, "content": "🤔 Thinking..."},
        {"id": processing["id"], "finish": False, "content": "first"},
        {"id": processing["id"], "finish": True, "content": "final answer"},
    ]
    assert driver._platform._keepalive_tasks == {}


async def test_native_upload_init_chunks_finish_ack_and_reply(
    wecom_native,
    tmp_path,
):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    data = b"ordinary-file\x00" * 10
    path = tmp_path / "upload.bin"
    path.write_bytes(data)
    result = await send(
        wecom_native,
        event["response_handle"],
        content_parts=[
            {"type": "file", "file_url": str(path), "filename": "upload.bin"},
        ],
    )
    assert result["state"] == "acknowledged"
    commands = [
        r for r in server.rows() if r["cmd"].startswith("aibot_upload_")
    ]
    assert [r["cmd"] for r in commands] == [
        "aibot_upload_media_init",
        "aibot_upload_media_chunk",
        "aibot_upload_media_finish",
    ]
    assert commands[0]["body"] == {
        "type": "file",
        "filename": "upload.bin",
        "total_size": len(data),
        "total_chunks": 1,
        "md5": hashlib.md5(data).hexdigest(),
    }
    assert [r["body"]["chunk_index"] for r in commands[1:2]] == [0]
    assert (
        b"".join(
            base64.b64decode(r["body"]["base64_data"]) for r in commands[1:2]
        )
        == data
    )
    assert commands[-1]["body"] == {"upload_id": "native-upload"}
    assert server.rows("aibot_respond_msg")[-1]["body"] == {
        "msgtype": "file",
        "file": {"media_id": "native-media"},
    }
    assert driver._platform._upload_ack_futures == {}


async def test_native_stop_settles_owned_sdk_thread_loop_and_keepalive(
    wecom_native,
):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    await prepare(wecom_native, event["response_handle"])
    platform = driver._platform
    thread, loop, client = (
        platform._ws_thread,
        platform._ws_loop,
        platform._client,
    )
    assert thread.is_alive() and loop.is_running()
    await driver.stop()
    assert not thread.is_alive() and loop.is_closed()
    assert (
        platform._sdk_tasks
        == platform._file_tasks
        == platform._bridges
        == set()
    )
    assert (
        platform._keepalive_tasks
        == platform._processing
        == platform._upload_ack_futures
        == {}
    )
    assert client._ws_manager._ws is None
    assert driver._platform is None
    await eventually(lambda: server.closed.is_set())


@pytest.mark.parametrize(
    "group,session,kind",
    [(False, "wecom:sender-A", "dm"), (True, "wecom:group:group-A", "group")],
)
async def test_native_dm_and_group_keep_authenticated_sender(
    wecom_native,
    group,
    session,
    kind,
):
    frame = text_frame(group=group)
    text = "@native-bot hello native" if group else "hello native"
    frame["body"]["text"]["content"] = text
    event = await ingress(wecom_native, frame)
    assert event["sender_id"] == event["acl_sender_id"] == "sender-A"
    assert event["metadata"]["session_id"] == session
    assert event["conversation"]["type"] == kind
    assert event["metadata"]["bot_mentioned"] is group
    assert event["content_parts"] == [{"type": "text", "text": text}]
