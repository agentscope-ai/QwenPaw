# -*- coding: utf-8 -*-
"""Unbuffered in-process ASGI client for the public integration host."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

import asyncio
import json
from typing import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, parse_qsl

from .errors import SDKError
from .apps import JSONBody


@dataclass(frozen=True)
class TestHttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode()

    def json(self) -> JSONBody:
        return json.loads(self.body)


class TestConnection:
    def __init__(
        self,
        host,
        method,
        path,
        *,
        workspace_id="test",
        user_id="test",
        headers=None,
        body=b"",
        websocket=False,
    ):
        self._host, self._method, self._path = host, method, path
        self._workspace_id, self._user_id = workspace_id, user_id
        self._headers, self._body, self._websocket = (
            headers or {},
            body,
            websocket,
        )
        self._incoming, self._outgoing = asyncio.Queue(), asyncio.Queue(
            maxsize=1,
        )
        self._task = None
        self._response_complete = False
        self.status, self.headers = 0, {}

    async def __aenter__(self):
        await self._host._workspace(self._workspace_id)
        parts = urlsplit(self._path)
        query = dict(parse_qsl(parts.query))
        query.setdefault("agent_id", self._workspace_id)
        scope = {
            "type": "websocket" if self._websocket else "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "method": self._method,
            "scheme": "ws" if self._websocket else "http",
            "path": parts.path,
            "raw_path": parts.path.encode(),
            "query_string": urlencode(query).encode(),
            "root_path": "",
            "headers": [
                (key.lower().encode(), value.encode())
                for key, value in self._headers.items()
            ],
            "server": ("sdk.test", 80),
            "client": ("127.0.0.1", 12345),
            "state": {"user": self._user_id},
            "subprotocols": [],
        }
        initial = (
            {"type": "websocket.connect"}
            if self._websocket
            else {
                "type": "http.request",
                "body": self._body,
                "more_body": False,
            }
        )
        await self._incoming.put(initial)
        self._task = asyncio.create_task(
            self._host._http_app(
                scope,
                self._incoming.get,
                self._outgoing.put,
            ),
        )
        self._host._connections.add(self)
        try:
            event = await self._next()
        except BaseException:
            await self.close()
            raise
        if event["type"] == "http.response.start":
            self.status = event["status"]
            self.headers = {
                key.decode(): value.decode()
                for key, value in event.get("headers", ())
            }
        elif event["type"] != "websocket.accept":
            await self.close()
            raise SDKError(f"Connection was not accepted: {event['type']}")
        return self

    async def _next(self):
        receiver = asyncio.create_task(self._outgoing.get())
        try:
            done, _ = await asyncio.wait(
                {receiver, self._task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                return receiver.result()
            self._task.result()
            raise SDKError("ASGI application ended without a response")
        finally:
            if not receiver.done():
                receiver.cancel()

    async def chunks(self) -> AsyncIterator[bytes]:
        while True:
            event = await self._next()
            if event["type"] != "http.response.body":
                raise SDKError(f"Unexpected ASGI event: {event['type']}")
            self._response_complete = not event.get("more_body", False)
            if event.get("body"):
                yield event["body"]
            if self._response_complete:
                return

    async def send(self, message: str | bytes) -> None:
        await self._incoming.put(
            {
                "type": "websocket.receive",
                "text" if isinstance(message, str) else "bytes": message,
            },
        )

    async def receive(self) -> str | bytes | None:
        event = await self._next()
        if event["type"] == "websocket.close":
            return None
        return event.get("text", event.get("bytes"))

    async def close(self):
        task = self._task
        if task is None:
            return
        from .custody import TASK_STOP_SECONDS, stop_task

        try:
            if self._response_complete:
                # The last body is not the end of the application's resource
                # cleanup. A normal response must not cancel that cleanup.
                _, pending = await asyncio.wait(
                    {task},
                    timeout=TASK_STOP_SECONDS,
                )
                if pending:
                    raise SDKError(
                        "HTTP response completed but request cleanup is "
                        "still running",
                    )
                task.result()
            else:
                await self._incoming.put(
                    {"type": "websocket.disconnect", "code": 1000}
                    if self._websocket
                    else {"type": "http.disconnect"},
                )
                await stop_task(task, "test HTTP/WebSocket connection")
        finally:
            # A finished ASGI task cannot own further connection work. Its
            # failure propagates once; failed scopes remain in the root ledger
            # so a subsequent Host.close can retry their actual cleanup.
            if task.done():
                self._host._connections.discard(self)
                self._task = None

    async def __aexit__(self, *_):
        await self.close()
