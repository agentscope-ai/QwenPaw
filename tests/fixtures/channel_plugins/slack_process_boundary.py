"""Only Slack's external WebAPI/WS/HTTP effects are controlled.  Bolt
dispatch and the native SocketModeClient's receiver/monitor/processor
tasks run unchanged. The three native task exits are observable in the
ledger."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

from aiohttp import WSMessage, WSMsgType
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_slack_response import AsyncSlackResponse

WORK = Path(__file__).with_name("slack-test-work").read_text().strip()
ACTIVE_TOKEN = "local-A"
POSTS = {}
AUTH_FAILURES = {}


def directory(token=None):
    path = Path(WORK) / (token or ACTIVE_TOKEN)
    path.mkdir(parents=True, exist_ok=True)
    return path


def record(kind, token=None, **values):
    with (directory(token) / "ledger.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"kind": kind, "pid": os.getpid(), **values}) + "\n"
        )


def mode(token=None):
    path = directory(token) / "mode"
    return path.read_text() if path.exists() else ""


async def effect(kind, token=None):
    value = mode(token)
    if value == "ws-close-residual" and kind == "ws-close":
        globals()["_g2_retain_child"]()
        raise OSError(
            "controlled external close failure with owned descendant"
        )
    if kind == "auth.test" and value == "auth.test-transient-twice":
        AUTH_FAILURES[token] = AUTH_FAILURES.get(token, 0) + 1
        if AUTH_FAILURES[token] <= 2:
            raise TimeoutError("controlled transient auth service failure")
        (directory(token) / "mode").unlink()
    if value == kind + "-fail-once":
        (directory(token) / "mode").unlink()
        raise OSError("controlled one-shot external connection failure")
    if value == kind + "-block":
        try:
            while mode(token) == value:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            record(kind + "-cancelled", token)
            raise
    if value == kind + "-unknown":
        raise TimeoutError("controlled uncertain Slack result")
    if value == kind + "-cancel":
        raise asyncio.CancelledError()
    if value in {kind + "-reject", kind + "-server", kind + "-rate"}:
        status = {"reject": 400, "server": 503, "rate": 429}[
            value.rsplit("-", 1)[-1]
        ]
        response = NS(
            status_code=status,
            headers={"Retry-After": "0"},
            get=lambda key, default=None: (
                "invalid_arguments" if key == "error" else default
            ),
        )
        raise SlackApiError("controlled rejection", response)


async def api_call(self, api_method, *, http_verb="POST", **kwargs):
    global ACTIVE_TOKEN
    ACTIVE_TOKEN = self.token or ACTIVE_TOKEN
    token = ACTIVE_TOKEN
    arguments = {
        **(kwargs.get("params") or {}),
        **(kwargs.get("data") or {}),
        **(kwargs.get("json") or {}),
    }
    record(
        api_method,
        token,
        arguments=arguments,
        proxy=self.proxy,
        retry_handlers=[
            type(handler).__name__ for handler in self.retry_handlers
        ],
        proxy_environment={
            name: os.environ.get(name)
            for name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "no_proxy",
            )
        },
        unrelated_secret_present="QWENPAW_TEST_UNRELATED_SECRET" in os.environ,
        excluded_environment={
            name: name in os.environ
            for name in ("PYTHONHOME", "PYTHONPATH", "Http_Proxy")
        },
        sdk_source=__import__("slack_sdk").__file__,
    )
    await effect(api_method, token)
    result = {"ok": True}
    if api_method == "auth.test":
        result.update(
            user_id="U999", bot_id="B999", team_id="T999", user="bot"
        )
        profile = directory(token) / "auth.json"
        if profile.exists():
            result.update(json.loads(profile.read_text()))
    elif api_method == "apps.connections.open":
        result["url"] = "wss://wss-primary.slack.com/local"
    elif api_method == "users.info":
        name = directory(token) / "users.json"
        profiles = json.loads(name.read_text()) if name.exists() else {}
        user = arguments["user"]
        result["user"] = profiles.get(
            user,
            {
                "id": user,
                "name": "testuser",
                "profile": {"display_name": "Testy", "real_name": "Real"},
            },
        )
    elif api_method == "conversations.replies":
        path = directory(token) / "history.json"
        result["messages"] = (
            json.loads(path.read_text()) if path.exists() else []
        )
    elif api_method == "chat.postMessage":
        POSTS[token] = POSTS.get(token, 0) + 1
        result["ts"] = f"2000000000.{POSTS[token]:06d}"
        record("post-result", token, ts=result["ts"], arguments=arguments)
        if mode(token) == "post-second-server" and POSTS[token] == 2:
            raise TimeoutError("second chunk result lost")
    elif api_method in {"chat.update", "chat.delete"}:
        result["ts"] = arguments.get("ts")
    elif api_method == "files.getUploadURLExternal":
        result.update(
            upload_url="https://files.slack.com/upload/v1", file_id="F12345"
        )
    elif api_method == "files.completeUploadExternal":
        result["files"] = [{"id": "F12345", "title": "uploaded"}]
    elif api_method == "files.uploadV2":
        result["file"] = {"id": "F12345"}
    return AsyncSlackResponse(
        client=self,
        http_verb=http_verb,
        api_url=api_method,
        req_args=kwargs,
        data=result,
        headers={},
        status_code=200,
    )


class WebSocket:
    def __init__(self, token):
        self.token, self.closed, self.offset = token, False, 0

    async def ping(self, _data):
        return None

    async def pong(self, _data):
        return None

    async def receive(self):
        try:
            while not self.closed:
                path = directory(self.token) / "inbox.jsonl"
                lines = path.read_text().splitlines() if path.exists() else []
                if self.offset < len(lines):
                    data = json.loads(lines[self.offset])
                    self.offset += 1
                    record("ws-inbound", self.token, envelope=data)
                    return WSMessage(WSMsgType.TEXT, json.dumps(data), "")
                await asyncio.sleep(0.01)
            return WSMessage(WSMsgType.CLOSED, None, "")
        except asyncio.CancelledError:
            if mode(self.token) == "receiver-cleanup-block":
                record("receiver-cleanup-start", self.token)
                try:
                    while mode(self.token) == "receiver-cleanup-block":
                        await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    record("receiver-cleanup-interrupted", self.token)
                    raise
                record("receiver-cleanup-complete", self.token)
            raise

    async def send_str(self, text):
        record("platform-ack", self.token, payload=json.loads(text))

    async def close(self, *args, **kwargs):
        record("ws-close", self.token)
        await effect("ws-close", self.token)
        self.closed = True


async def ws_connect(self, url, **kwargs):
    token = ACTIVE_TOKEN
    record("ws-connect", token, url=url, arguments=kwargs)
    await effect("ws-connect", token)
    return WebSocket(token)


class HTTPResponse:
    def __init__(self, method, url, kwargs):
        self.method, self.url, self.kwargs = method, url, kwargs
        self.status, self.headers = 200, {
            "content-type": "application/octet-stream"
        }
        self.content_type = "text/plain"

    async def __aenter__(self):
        body = self.kwargs.get("data")
        if hasattr(body, "read"):
            body = body.read()
        record(
            "http-" + self.method,
            url=self.url,
            proxy=self.kwargs.get("proxy"),
            headers=self.kwargs.get("headers"),
            timeout=getattr(self.kwargs.get("timeout"), "total", None),
            bytes=list(body) if isinstance(body, bytes) else None,
        )
        value = mode()
        if value == "http-get-html":
            self.headers = {"content-type": "text/html"}
        if value == "http-get-503-once":
            self.status = 503
            (directory() / "mode").unlink()
        await effect("http-" + self.method)
        return self

    async def __aexit__(self, *_args):
        return None

    async def read(self):
        return b"file content"

    async def text(self):
        return "ok"


def install_http():
    import aiohttp

    original_close = aiohttp.ClientSession.close

    async def close(self):
        await original_close(self)
        record("http-session-close", closed=self.closed)
        if mode() == "receiver-cleanup-block":
            await asyncio.sleep(0)

    aiohttp.ClientSession.close = close
    aiohttp.ClientSession.ws_connect = ws_connect
    aiohttp.ClientSession.get = lambda self, url, **kw: HTTPResponse(
        "get", url, kw
    )
    aiohttp.ClientSession.post = lambda self, url, **kw: HTTPResponse(
        "post", url, kw
    )
    aiohttp.ClientSession.request = (
        lambda self, method, url, **kw: HTTPResponse(method.lower(), url, kw)
    )


def install_web(cls):
    cls.api_call = api_call
    install_http()


def install_socket(cls):
    original_init, original_connect = cls.__init__, cls.connect

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        token = self.web_client.token
        self.message_processor.add_done_callback(
            lambda task: record(
                "native-task-exit", token, name="message_processor"
            )
        )

    async def connect(self):
        await original_connect(self)
        token = self.web_client.token
        for name in ("current_session_monitor", "message_receiver"):
            task = getattr(self, name)
            task.add_done_callback(
                lambda task, name=name: record(
                    "native-task-exit", token, name=name
                )
            )

    cls.__init__, cls.connect = initialize, connect
