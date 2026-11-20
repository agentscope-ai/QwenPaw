"""In-process, backpressured Console events for an authorized PawApp."""

import asyncio
import json
from contextlib import aclosing
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from uuid import UUID

import httpx

from ..app.console_delegation import is_terminal_response
from ..schemas import AgentResponse, Message


@dataclass
class PawAppRun:
    """A single internal request may stop only the run that it created."""

    user_id: UUID
    stop: Callable[[], Awaitable] | None = None
    terminal: bool = False


@dataclass(frozen=True)
class PawAppConsoleBinding:
    session_id: UUID
    user_id: UUID
    agent_id: str
    plugin_id: str

    async def events(self, app, target_agent, message, session_id):
        if target_agent != self.agent_id:
            raise PermissionError("PawApp agent authorization unavailable")
        body = json.dumps(
            {
                "input": [
                    {"role": "user", "content": [{"type": "text", "text": message}]}
                ],
                "user_id": str(self.user_id),
                "session_id": session_id or f"pawapp:{self.plugin_id}:{self.user_id}",
            }
        ).encode()
        run = PawAppRun(self.user_id)
        async with aclosing(self._chunks(app, body, run)) as chunks:
            response = httpx.Response(200, content=chunks)
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                if is_terminal_response(event):
                    run.terminal = True
                    if event["status"] != "completed":
                        raise RuntimeError("PawApp Console run did not complete")
                    yield AgentResponse.model_validate(event)
                elif event.get("object") == "message":
                    yield Message.model_validate(event)
        if not run.terminal:
            raise RuntimeError("PawApp Console stream ended without a final result")

    async def _chunks(self, app, body, run):
        path = "/api/console/chat"
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "server": ("console.internal", 80),
            "client": None,
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-agent-id", self.agent_id.encode()),
            ],
            "qwenpaw.pawapp_console": self,
            "qwenpaw.pawapp_run": run,
        }
        queue = asyncio.Queue(maxsize=1)
        disconnected = asyncio.Event()
        read_body = False

        async def receive():
            nonlocal read_body
            if not read_body:
                read_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(frame):
            if frame["type"] == "http.response.start":
                if frame["status"] != 200:
                    await queue.put(
                        RuntimeError(f"PawApp Console HTTP {frame['status']}")
                    )
            elif frame["type"] == "http.response.body" and frame.get("body"):
                await queue.put(frame["body"])

        async def serve():
            try:
                await app(scope, receive, send)
            except Exception as exc:
                await queue.put(exc)
            else:
                await queue.put(None)

        producer = asyncio.create_task(serve())
        try:
            while (chunk := await queue.get()) is not None:
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk
        finally:
            disconnected.set()
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            if run.stop is not None and not run.terminal:
                await run.stop()
