# -*- coding: utf-8 -*-
"""Child-only SDK/network substitutes; no production methods are replaced.

The suite prefixes WORK. Real SDK request builders, platform, Driver, RPC,
worker and host proxy execute normally. A file mailbox represents the network.
"""

import asyncio
import io
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace as NS

import httpx
import lark_oapi as lark
import lark_oapi.ws.client as lark_ws
from lark_oapi.core.token import TokenManager

work = Path(globals()["WORK"])
lock = threading.Lock()


def record(kind, **data):
    with lock:
        with (work / "ledger.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"kind": kind, "pid": os.getpid(), **data}) + "\n",
            )


def namespace(value):
    if isinstance(value, list):
        return [namespace(item) for item in value]
    if isinstance(value, dict):
        return NS(**{key: namespace(item) for key, item in value.items()})
    return value


def ok(**data):
    return NS(success=lambda: True, data=NS(**data), code=0, msg="")


class Api:
    def __init__(self, kind):
        self.kind = kind

    async def acreate(self, request):
        body = request.request_body
        data = {
            key: getattr(body, key, None)
            for key in ("receive_id", "msg_type", "content", "data", "type")
        }
        data["receive_id_type"] = getattr(request, "receive_id_type", None)
        if self.kind in {"image", "file"}:
            upload = getattr(body, self.kind, None)
            data["uploaded_bytes"] = list(upload.read()) if upload else None
        record(self.kind, **data)
        mode_path = work / "send-mode"
        mode = mode_path.read_text() if mode_path.exists() else ""
        if self.kind == "create" and mode == "definite-failure":
            return NS(
                success=lambda: False,
                data=None,
                code=400,
                msg="rejected",
            )
        if self.kind == "create" and mode == "commit-exit":
            os._exit(27)
        if self.kind == "create" and mode == "commit-hang":
            await asyncio.Event().wait()
        if self.kind == "create" and mode == "unknown":
            raise TimeoutError("platform may have committed")
        count = sum(
            1
            for line in (work / "ledger.jsonl").read_text().splitlines()
            if json.loads(line)["kind"] == self.kind
        )
        return ok(
            message_id=f"sent-{count}",
            image_key="img-uploaded",
            file_key="file-uploaded",
            card_id=f"card-{count}",
        )

    async def areply(self, request):
        record(
            "reply",
            message_id=request.message_id,
            msg_type=request.request_body.msg_type,
            content=request.request_body.content,
        )
        return ok(message_id="reply-1")

    async def aget(self, request):
        record(
            "download",
            message_id=request.message_id,
            file_key=request.file_key,
            resource_type=request.type,
        )
        return NS(success=lambda: True, file=io.BytesIO(b"media-content"))

    async def acontent(self, request):
        record(
            "update",
            card_id=request.card_id,
            content=request.request_body.content,
            sequence=request.request_body.sequence,
        )
        mode = (
            (work / "send-mode").read_text()
            if (work / "send-mode").exists()
            else ""
        )
        if mode == "update-exit":
            os._exit(28)
        if mode == "update-unknown":
            raise TimeoutError("card update may have committed")
        if mode == "update-block":
            while not (work / "update-release").exists():
                await asyncio.sleep(0.01)
        return ok()

    async def asettings(self, request):
        record(
            "settings",
            card_id=request.card_id,
            settings=request.request_body.settings,
            sequence=request.request_body.sequence,
        )
        mode = (
            (work / "send-mode").read_text()
            if (work / "send-mode").exists()
            else ""
        )
        if mode == "settings-unknown":
            raise TimeoutError("card finalization may have committed")
        return ok()


class ClientBuilder:
    def __init__(self):
        self.values = {}

    def __getattr__(self, name):
        def set_value(value):
            self.values[name] = value
            return self

        return set_value

    def build(self):
        record("client", domain=self.values["domain"])
        return NS(
            _config=NS(**self.values),
            im=NS(
                v1=NS(
                    message=Api("create"),
                    image=Api("image"),
                    file=Api("file"),
                    message_resource=Api("download"),
                    message_reaction=Api("reaction"),
                ),
            ),
            cardkit=NS(v1=NS(card=Api("card"), card_element=Api("update"))),
        )


class Dispatcher:
    def __init__(self):
        self.callbacks = {}

    def __getattr__(self, name):
        def register(callback):
            self.callbacks[name] = callback
            return self

        return register

    def build(self):
        return self


class Connection:
    def __init__(self):
        cursor = work / "inbox.cursor"
        self.offset = int(cursor.read_text()) if cursor.exists() else 0
        self.closed = False

    async def recv(self):
        while not self.closed:
            path = work / "inbox.jsonl"
            lines = path.read_text().splitlines() if path.exists() else []
            if self.offset < len(lines):
                item = json.loads(lines[self.offset])
                self.offset += 1
                (work / "inbox.cursor").write_text(str(self.offset))
                if item["kind"] == "disconnect":
                    raise ConnectionError("controlled network disconnect")
                return item
            await asyncio.sleep(0.01)
        raise ConnectionError("closed")

    async def close(self):
        self.closed = True


class WebSocket:
    previous = None
    latest = None

    def __init__(self, *_args, event_handler, domain, **_kwargs):
        WebSocket.previous, WebSocket.latest = WebSocket.latest, self
        self.handler = event_handler
        self.domain = domain
        self._conn = None

    async def _connect(self):
        self._conn = Connection()
        asyncio.get_running_loop().create_task(self._receive_message_loop())
        record("connected", domain=self.domain)

    async def _ping_loop(self):
        # Real SDK ping sleeps; the timer retains this otherwise unowned task.
        await asyncio.sleep(3600)

    async def _handle_message(self, item):
        key = (
            "register_p2_card_action_trigger"
            if item["kind"] == "card"
            else "register_p2_im_message_receive_v1"
        )
        value = namespace(item["value"])
        if item["kind"] == "card":
            value.event.action.value = item["value"]["event"]["action"][
                "value"
            ]
        handler = (
            WebSocket.previous.handler
            if item["kind"] == "old-message"
            else self.handler
        )
        handler.callbacks[key](value)
        record("callback", event_id=item["value"]["header"]["event_id"])

    async def _disconnect(self):
        if self._conn is not None:
            await self._conn.close()
        self._conn = None
        record("disconnected")


class HttpClient:
    def __init__(self, **kwargs):
        pass

    async def get(self, url, **_kwargs):
        record("http", url=url)
        return NS(
            headers={},
            json=lambda: {"code": 0, "bot": {"open_id": "ou_bot"}},
        )

    async def aclose(self):
        record("http-close")


lark.Client.builder = staticmethod(ClientBuilder)
lark.EventDispatcherHandler.builder = staticmethod(lambda *_: Dispatcher())
lark_ws.Client = WebSocket
TokenManager.get_self_tenant_token = staticmethod(lambda _: "fixture-token")
httpx.AsyncClient = HttpClient

# Alias the unchanged production entrypoint. There is no test Driver.
# This file is copied into the candidate package, which supplies .driver.
# pylint: disable=relative-beyond-top-level,wrong-import-position,unused-import
from .driver import FeishuDriver  # noqa: E402,F401
