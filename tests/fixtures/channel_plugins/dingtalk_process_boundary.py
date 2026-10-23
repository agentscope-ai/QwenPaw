# -*- coding: utf-8 -*-
# pylint: disable=protected-access,wrong-import-position,unused-import
# pylint: disable=relative-beyond-top-level
"""Child-only network boundaries; real SDK models, Stream and Driver run."""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import threading

import aiohttp
from dingtalk_stream import stream
import requests
from alibabacloud_dingtalk.oauth2_1_0.client import Client as OAuthClient
from alibabacloud_dingtalk.oauth2_1_0 import models as oauth_models
from alibabacloud_dingtalk.robot_1_0.client import Client as RobotClient
from alibabacloud_dingtalk.robot_1_0 import models as robot_models
from alibabacloud_dingtalk.card_1_0.client import Client as CardClient
from alibabacloud_dingtalk.card_1_0 import models as card_models

work = Path(globals()["WORK"])
lock = threading.Lock()


def record(kind, **data):
    with lock:
        with (work / "ledger.jsonl").open("a", encoding="utf-8") as output:
            output.write(
                json.dumps({"kind": kind, "pid": os.getpid(), **data}) + "\n",
            )


def mode():
    path = work / "send-mode"
    return path.read_text() if path.exists() else ""


async def effect(kind):
    current = mode()
    if current == kind + "-exit":
        os._exit(27)
    if current == kind + "-unknown":
        raise TimeoutError("test-only-secret: remote may have committed")
    if current == kind + "-tea":
        from Tea.exceptions import UnretryableException
        from Tea.request import TeaRequest

        raise UnretryableException(TeaRequest(), TimeoutError("uncertain"))
    if current == kind + "-dara":
        from darabonba.exceptions import RetryError

        raise RetryError("uncertain")
    if current == kind + "-block":
        while not (work / (kind + "-release")).exists():
            await asyncio.sleep(0.01)
    if current == kind + "-reject":
        raise ValueError("known platform rejection")


class Socket:
    def __init__(self):
        cursor = work / "inbox.cursor"
        self.offset = int(cursor.read_text()) if cursor.exists() else 0
        self.closed = False
        self.open = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        while not self.closed:
            path = work / "inbox.jsonl"
            lines = path.read_text().splitlines() if path.exists() else []
            if self.offset < len(lines):
                value = json.loads(lines[self.offset])
                self.offset += 1
                (work / "inbox.cursor").write_text(str(self.offset))
                if value.get("disconnect"):
                    raise StopAsyncIteration
                record("callback", message_id=value["headers"]["messageId"])
                return json.dumps(value)
            await asyncio.sleep(0.01)
        raise StopAsyncIteration

    async def ping(self):
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future

    async def send(self, value):
        record("ack", frame=json.loads(value))

    async def close(self):
        record("socket-close")
        while (
            mode() == "close-block" and not (work / "close-release").exists()
        ):
            await asyncio.sleep(0.01)
        self.closed, self.open = True, False


class Connection:
    def __init__(self, *_args, **_kwargs):
        self.socket = Socket()

    async def __aenter__(self):
        assert "qwenpaw.app.channels.base" not in sys.modules
        record("connected", imported_base=False)
        return self.socket

    async def __aexit__(self, *_args):
        await self.socket.close()


def sync_post(url, **kwargs):
    record("sync-http", url=url, timeout=kwargs.get("timeout"))
    if mode() == "gateway-fail":
        raise requests.ConnectionError("controlled gateway failure")
    if mode() == "gateway-block":
        while not (work / "gateway-release").exists():
            threading.Event().wait(0.01)
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(
        {
            "endpoint": "wss://gateway.test/ws",
            "ticket": "test",
            "accessToken": "stream-token",
            "expireIn": 7200,
        },
    ).encode()
    return response


class HttpResponse:
    status = 200
    headers = {}

    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.release()

    async def read(self):
        return (
            self.data
            if isinstance(self.data, bytes)
            else json.dumps(self.data).encode()
        )

    async def text(self):
        if mode() == "webhook-payload":
            raise aiohttp.ClientPayloadError("acknowledgement truncated")
        if mode() == "webhook-json":
            return '{"errcode":'
        if mode() == "webhook-empty":
            return ""
        return json.dumps(self.data)

    async def json(self, **_kwargs):
        return self.data

    def release(self):
        pass

    async def wait_for_close(self):
        pass


async def http_request(session, verb, url, **kwargs):
    assert not session.closed
    data = kwargs.get("data")
    fields = []
    if isinstance(data, aiohttp.FormData):
        for info, headers, value in data._fields:
            fields.append(
                {
                    "filename": info.get("filename"),
                    "bytes": list(value),
                    "headers": dict(headers),
                },
            )
    record(
        "http",
        method=verb,
        url=str(url),
        payload=kwargs.get("json"),
        fields=fields,
    )
    if str(url) == "https://download.test/image":
        response = HttpResponse(b"\x89PNG\r\n\x1a\noriginal image")
        response.headers = {"Content-Type": "image/png"}
        return response
    if "/media/upload" in str(url):
        return HttpResponse({"errcode": 0, "media_id": "@media-one"})
    if (
        mode() == "file-unknown"
        and (kwargs.get("json") or {}).get("msgtype") == "file"
    ):
        raise TimeoutError("file acknowledgement lost")
    await effect("webhook")
    return HttpResponse(
        {"errcode": 310000 if mode() == "webhook-rejected" else 0},
    )


async def token(self, request):
    record("token", endpoint=self._endpoint, request=request.to_map())
    return oauth_models.GetAccessTokenResponse(
        body=oauth_models.GetAccessTokenResponseBody(
            access_token="api-token",
            expire_in=7200,
        ),
    )


def endpoint(kind):
    async def call(self, request, headers, options):
        record(
            kind,
            endpoint=self._endpoint,
            request=request.to_map(),
            headers=headers.to_map(),
            options=options.to_map(),
        )
        if (
            kind == "update"
            and mode() == "finalize-block"
            and request.is_finalize
        ):
            while not (work / "update-release").exists():
                await asyncio.sleep(0.01)
        await effect(kind)
        if kind == "download":
            return robot_models.RobotMessageFileDownloadResponse(
                body=robot_models.RobotMessageFileDownloadResponseBody(
                    download_url="https://download.test/image",
                ),
            )
        if kind == "deliver":
            return card_models.DeliverCardResponse(
                body=card_models.DeliverCardResponseBody(),
            )
        return None

    return call


close_http = aiohttp.ClientSession.close


async def tracked_close(session):
    if mode() == "close-unreapable":
        record("close-unreapable")
        while not (work / "close-release").exists():
            threading.Event().wait(0.01)
    await close_http(session)
    record("http-close", closed=session.closed)


socket.socket.connect = lambda *_args: None
requests.post = sync_post
stream.websockets.connect = Connection
aiohttp.ClientSession._request = http_request
aiohttp.ClientSession.close = tracked_close
OAuthClient.get_access_token_async = token
for target, method, name in [
    (RobotClient, "robot_reply_emotion_with_options_async", "emotion"),
    (RobotClient, "robot_recall_emotion_with_options_async", "recall"),
    (RobotClient, "org_group_send_with_options_async", "group"),
    (RobotClient, "batch_send_otowith_options_async", "dm"),
    (
        RobotClient,
        "robot_message_file_download_with_options_async",
        "download",
    ),
    (CardClient, "create_card_with_options_async", "create"),
    (CardClient, "deliver_card_with_options_async", "deliver"),
    (CardClient, "streaming_update_with_options_async", "update"),
]:
    setattr(target, method, endpoint(name))

from .driver import DingTalkDriver  # noqa: E402,F401
