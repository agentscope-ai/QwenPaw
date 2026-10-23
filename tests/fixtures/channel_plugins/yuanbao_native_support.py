"""Real loopback HTTP, verified TLS COS and binary protobuf WS boundaries."""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import socket
import ssl
import sys

import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractResolver
from google.protobuf import json_format
import pytest_asyncio

from g2_shared_response_suite import Peer

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/yuanbao"))

from qwenpaw_channel_yuanbao import codec  # noqa: E402
from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform  # noqa: E402


async def eventually(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def decode(type_name, data):
    message = codec._get_message_class(type_name)()
    message.ParseFromString(data)
    return json_format.MessageToDict(message, preserving_proto_field_name=True)


class COSResolver(AbstractResolver):
    def __init__(self, port):
        self.port = port

    async def resolve(self, host, port=0, family=socket.AF_INET):
        assert host == "test-bucket.cos.test-region.myqcloud.com", host
        return [{"hostname": host, "host": "127.0.0.1", "port": self.port,
                 "family": socket.AF_INET, "proto": 0, "flags": 0}]

    async def close(self):
        pass


class YuanbaoExternal:
    """Script external replies only; native clients, signing and codec stay real."""

    def __init__(self, directory):
        self.directory = directory
        self.calls, self.frames, self.sends, self.uploads = [], [], [], []
        self.signatures_valid = []
        self.connections = []
        self.ws = None
        self.runner = None
        self.http = self.cos = None
        self.base = self.ws_url = None
        self.behaviors = deque()
        self.sign_behaviors = deque()
        self.upload_info_status = 200
        self.assets = {"/assets/voice.mp3": b"native-audio", "/assets/image.jpg": b"native-image"}
        self._tasks = set()

    async def start(self):
        app = web.Application()
        app.router.add_get("/wss/connection", self.gateway)
        app.router.add_route("*", "/{path:.*}", self.http_request)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.http = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.http.start()
        port = self.http._server.sockets[0].getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        self.ws_url = f"ws://127.0.0.1:{port}/wss/connection"
        return self

    async def enable_verified_cos(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Yuanbao Test CA")])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("test-bucket.cos.test-region.myqcloud.com")
            ]), critical=False)
            .sign(key, hashes.SHA256())
        )
        cert_path, key_path = self.directory / "cos-ca.pem", self.directory / "cos-key.pem"
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert_path, key_path)
        self.cos = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=server_context)
        await self.cos.start()
        port = self.cos._server.sockets[0].getsockname()[1]
        trusted = ssl.create_default_context(cafile=str(cert_path))
        assert trusted.verify_mode == ssl.CERT_REQUIRED and trusted.check_hostname
        # Only DNS destination and the independent test CA differ from the network.
        return aiohttp.ClientSession(connector=aiohttp.TCPConnector(
            resolver=COSResolver(port), ssl=trusted,
        ))

    async def http_request(self, request):
        raw = await request.read()
        body = json.loads(raw) if request.content_type == "application/json" and raw else None
        row = {"method": request.method, "path": request.path, "query": dict(request.query),
               "headers": dict(request.headers), "body": body, "raw": raw}
        self.calls.append(row)
        if request.path == "/api/v5/robotLogic/sign-token":
            expected = hmac.new(b"local-secret", (
                body["nonce"] + body["timestamp"] + "local-app" + "local-secret"
            ).encode(), hashlib.sha256).hexdigest()
            self.signatures_valid.append(hmac.compare_digest(body["signature"], expected))
            assert body["app_key"] == "local-app" and self.signatures_valid[-1]
            if self.sign_behaviors:
                return web.json_response(self.sign_behaviors.popleft())
            return web.json_response({"code": 0, "data": {
                "bot_id": "native-bot", "token": "native-token", "source": "bot",
                "duration": 7200, "product": "yuanbao",
            }})
        if request.path == "/api/resource/genUploadInfo":
            if self.upload_info_status != 200:
                return web.Response(status=self.upload_info_status, text="native upload refusal")
            return web.json_response({"data": {
                "bucketName": "test-bucket", "region": "test-region",
                "location": "/uploads/" + body["fileId"],
                "encryptTmpSecretId": "cos-id", "encryptTmpSecretKey": "cos-key",
                "encryptToken": "cos-token", "startTime": 1700000000,
                "expiredTime": 1700003600,
                "resourceUrl": self.base + "/assets/uploaded", "resourceID": "resource-1",
            }})
        if request.method == "PUT" and request.path.startswith("/uploads/"):
            self.uploads.append(row)
            return web.Response(status=204)
        if request.path == "/api/resource/v1/download":
            return web.json_response({"data": {"realUrl": self.base + "/assets/voice.mp3"}})
        if request.path in self.assets:
            return web.Response(body=self.assets[request.path], content_type="application/octet-stream")
        return web.Response(status=404)

    async def gateway(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws = ws
        self.connections.append(ws)
        try:
            async for message in ws:
                assert message.type == aiohttp.WSMsgType.BINARY
                frame = codec.decode_conn_msg(message.data)
                assert frame is not None
                self.frames.append(frame)
                head, data = frame["head"], frame["data"]
                if head["cmd"] == codec.CMD_AUTH_BIND:
                    auth = decode(codec.AUTH_BIND_REQ, data)
                    assert auth["authInfo"] == {"uid": "native-bot", "source": "bot", "token": "native-token"}
                    await self.respond(head, codec.AUTH_BIND_RSP, {"code": 0, "message": "ok"}, ws=ws)
                elif head["cmd"] == codec.CMD_PING:
                    await self.respond(head, codec.PING_RSP, {"heartInterval": 7}, ws=ws)
                elif head.get("cmdType") == codec.CMD_TYPE_PUSH_ACK:
                    pass
                elif head["cmd"] in {codec.BIZ_CMD_SEND_C2C, codec.BIZ_CMD_SEND_GROUP}:
                    name = codec.SEND_C2C_REQ if head["cmd"] == codec.BIZ_CMD_SEND_C2C else codec.SEND_GROUP_REQ
                    row = {"head": head, "body": decode(name, data)}
                    self.sends.append(row)
                    behavior = self.behaviors.popleft() if self.behaviors else "ok"
                    if behavior == "close":
                        await ws.close(code=4012)
                    elif behavior == "reject":
                        await self.respond(head, codec.SEND_C2C_RSP, {"code": 403, "message": "denied"}, ws=ws)
                    elif behavior == "invalid":
                        await self.respond(head, raw=b"\xff\xff\xff", ws=ws)
                    elif behavior != "hold":
                        await self.respond(head, codec.SEND_C2C_RSP, {"code": 0, "message": "ok"}, ws=ws)
        finally:
            if self.ws is ws:
                self.ws = None
        return ws

    async def respond(self, head, type_name=None, body=None, *, raw=None, ws=None, **changes):
        response = {**head, "cmdType": codec.CMD_TYPE_RESPONSE, **changes}
        payload = raw if raw is not None else codec.encode_pb(type_name, body or {})
        await (ws or self.ws).send_bytes(codec.encode_conn_msg(response, payload))

    async def push(self, value, *, frame_id="push-frame", need_ack=True):
        head = {"cmdType": codec.CMD_TYPE_PUSH, "cmd": "native.push", "seqNo": 17,
                "msgId": frame_id, "module": codec.MODULE_BIZ, "needAck": need_ack}
        await self.ws.send_bytes(codec.encode_conn_msg(head, json.dumps(value).encode()))

    async def stop(self):
        for ws in self.connections:
            await ws.close()
        if self.runner is not None:
            await self.runner.cleanup()


def inbound(*, msg_id="native-message", sender="native-user-12345678", group=None, text="hello"):
    return {"callback_command": "Group.AfterSendMsg" if group else "C2C.AfterSendMsg",
            "from_account": sender, "sender_nickname": "灰", "msg_id": msg_id,
            "group_code": group or "", "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": text}}
            ]}


@pytest_asyncio.fixture
async def external(tmp_path):
    value = await YuanbaoExternal(tmp_path).start()
    try:
        yield value
    finally:
        await value.stop()


@pytest_asyncio.fixture
async def native_platform(external, tmp_path):
    events, states = [], []

    async def event(value):
        events.append(value)
        return True

    async def state(value):
        states.append(value)
    platform = YuanbaoPlatform({
        "enabled": True, "app_id": "local-app", "app_secret": "local-secret",
        "api_domain": external.base, "ws_url": external.ws_url,
        "workspace_dir": str(tmp_path / "workspace"),
    }, event, state)
    try:
        await platform.start()
        await eventually(lambda: platform._connected)
        yield platform, events, states, external
    finally:
        await platform.stop()


class HostBoundary(Peer):
    """Controlled state/admission RPC endpoint; this is not a full Core proof."""

    def __init__(self):
        super().__init__()
        self.methods, self.state = {}, {}
        self.batches, self.notifications = [], []

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, method, params):
        if method.startswith("host.receipt."):
            return await super().call(method, params)
        if method == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if method == "host.state.put":
            self.state[params["key"]] = json.loads(json.dumps(params["value"]))
            return {}
        assert method == "event.batch", method
        self.batches.append(params)
        return {"batch_id": params["batch_id"], "accepted_event_ids": [params["events"][0]["event_id"]]}

    async def notify(self, method, params):
        self.notifications.append((method, params))


@pytest_asyncio.fixture
async def native_driver(external, tmp_path):
    from qwenpaw.channel_protocol.models import IdentityParams
    from qwenpaw.channel_protocol.shared_worker import DriverContext
    from qwenpaw_channel_yuanbao.driver import YuanbaoDriver

    peer, driver = HostBoundary(), YuanbaoDriver()
    identity = IdentityParams("yuanbao", "native-workspace", 1)
    descriptor = json.loads((ROOT / "plugins/channel/yuanbao/channel.json").read_text())
    driver.bind(DriverContext(peer, identity, descriptor["capabilities"]))
    try:
        await driver.start({
            "enabled": True, "app_id": "local-app", "app_secret": "local-secret",
            "api_domain": external.base, "ws_url": external.ws_url,
            "workspace_dir": str(tmp_path / "workspace"), "bot_prefix": "[Bot] ",
        })
        await eventually(lambda: driver._connected)
        yield driver, peer, identity.to_mapping(), external
    finally:
        await driver.stop()


async def open_route(peer, identity, target="short-session", **meta):
    result = await peer.methods["channel.response.open"](
        {**identity, "to_handle": target, "meta": meta}, None,
    )
    return result["response_handle"]


async def send(peer, identity, handle, *, delivery="delivery-A", text="native answer", source="direct"):
    from qwenpaw.channel_protocol.models import SendParams
    value = SendParams.from_mapping({
        **identity, "to_handle": handle, "delivery_id": delivery,
        "operation": "message.create", "content_source": source,
        "content_parts": [{"type": "text", "text": text}],
    })
    return await peer.methods["channel.send"](value, None)
