"""Only HTTP service effects change; native PTB mapping/tasks remain real."""

import asyncio
import base64
import html
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, unquote, urlsplit
import httpx
from email.parser import BytesParser
from email.policy import default as email_policy
from types import SimpleNamespace
from urllib.parse import parse_qsl

WORK = Path(__file__).with_name("telegram-test-work").read_text().strip()
CLIENT_TOKENS = {}
COUNTS = {}
MESSAGES = {}
ACTIVE_REQUESTS = {}
REQUEST_SEQUENCE = 0


def directory(token):
    path = Path(WORK) / quote(token, safe="")
    path.mkdir(parents=True, exist_ok=True)
    return path


def record(kind, token, **values):
    task = asyncio.current_task()
    request_id = ACTIVE_REQUESTS.get(id(task)) if task is not None else None
    with (directory(token) / "ledger.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "kind": kind,
                    "pid": os.getpid(),
                    "at": time.monotonic(),
                    "request_id": request_id,
                    **values,
                }
            )
            + "\n"
        )


def mode(token):
    path = directory(token) / "mode"
    return path.read_text() if path.exists() else ""


def payload(data):
    result = {}
    for key, value in (data or {}).items():
        try:
            result[key] = (
                json.loads(value) if isinstance(value, str) else value
            )
        except ValueError:
            result[key] = value
    return result


def native_message(token, arguments, *, edit=False):
    number = MESSAGES.get(token, 0) + (0 if edit else 1)
    MESSAGES[token] = number
    message = {
        "message_id": arguments.get("message_id", number),
        "date": 1000000000,
        "chat": {
            "id": int(arguments.get("chat_id", 12345)),
            "type": "private",
        },
        "from": {
            "id": 999,
            "is_bot": True,
            "first_name": "Bot",
            "username": "test_bot",
        },
    }
    for key in ("text", "message_thread_id", "reply_markup"):
        if key in arguments:
            message[key] = arguments[key]
    return message


async def effect(kind, token, request, arguments=None):
    rich_failure = mode(token)
    if (
        rich_failure == "media-error-notice-reject"
        and kind == "sendMessage"
        and (arguments or {}).get("text") == "Could not decode media data URL."
    ):
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: chat not found",
            },
            request=request,
        )
    if (
        rich_failure in {"rich-unavailable-400", "rich-unavailable-404"}
        and kind in {"sendRichMessage", "editMessageText"}
        and "rich_message" in (arguments or {})
    ):
        code = int(rich_failure.rsplit("-", 1)[1])
        return httpx.Response(
            code,
            json={
                "ok": False,
                "error_code": code,
                "description": "Bad Request: unsupported",
            },
            request=request,
        )
    script_path = directory(token) / "poll-script.json"
    if (
        kind == "getUpdates"
        and (arguments or {}).get("timeout") == 10
        and script_path.exists()
    ):
        script = json.loads(script_path.read_text())
        if script:
            action = script.pop(0)
            script_path.write_text(json.dumps(script))
            if action.get("code"):
                return httpx.Response(
                    action["code"],
                    json={
                        "ok": False,
                        "error_code": action["code"],
                        "description": action.get(
                            "description", "Conflict: another getUpdates"
                        ),
                    },
                    request=request,
                )
    value = mode(token)
    if value == kind + "-token-once":
        (directory(token) / "mode").unlink()
        value = kind + "-token"
    if value == kind + "-timeout":
        (directory(token) / "mode").unlink()
        raise httpx.ReadTimeout("controlled service timeout", request=request)
    if value == kind + "-block" and (
        kind != "getUpdates" or (arguments or {}).get("timeout", 0) > 0
    ):
        try:
            while mode(token) == value:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            record(kind + "-cancelled", token)
            raise
    if value in {
        kind + "-conflict",
        kind + "-server",
        kind + "-format",
        kind + "-reject",
        kind + "-rate",
        kind + "-token",
        kind + "-missing",
    }:
        code = {
            "conflict": 409,
            "server": 503,
            "format": 400,
            "reject": 400,
            "rate": 429,
            "token": 401,
            "missing": 404,
        }[value.rsplit("-", 1)[1]]
        text = {
            "format": "Bad Request: can't parse entities",
            "conflict": "Conflict: other getUpdates",
        }.get(value.rsplit("-", 1)[1], "controlled service rejection")
        if value.endswith(("-rate", "-format")):
            (directory(token) / "mode").unlink()
        return httpx.Response(
            code,
            json={
                "ok": False,
                "error_code": code,
                "description": text,
                **({"parameters": {"retry_after": 1}} if code == 429 else {}),
            },
            request=request,
        )
    return None


async def response_received(client, response, kind, token):
    record(
        kind + "-response",
        token,
        status=response.status_code,
        task=id(asyncio.current_task()),
    )
    return response


async def service_request(self, method, url, **kwargs):
    path = unquote(urlsplit(str(url)).path)
    if "/bot" not in path:
        raise AssertionError("Unexpected non-Telegram HTTP: " + str(url))
    suffix = path.split("/bot", 1)[1]
    token, _, kind = suffix.partition("/")
    CLIENT_TOKENS[id(self)] = token
    request_object = httpx.Request(method, url)
    arguments = payload(kwargs.get("data"))
    files = {}
    for key, item in (kwargs.get("files") or {}).items():
        filename, content, mime = item
        if hasattr(content, "read"):
            content = content.read()
        files[key] = {
            "filename": filename,
            "mime": mime,
            "bytes_b64": base64.b64encode(content).decode(),
        }
    timeout = kwargs.get("timeout")
    record(
        kind,
        token,
        arguments=arguments,
        files=files,
        url=str(url),
        read_timeout=getattr(timeout, "read", None),
        task=id(asyncio.current_task()),
        sdk_source=__import__("telegram").__file__,
        client_proxy=getattr(self, "_telegram_test_proxy", None),
    )
    COUNTS[token, kind] = COUNTS.get((token, kind), 0) + 1
    failure = await effect(kind, token, request_object, arguments)
    if failure is not None:
        return await response_received(self, failure, kind, token)
    if kind in {"sendMessage", "editMessageText"} and "text" in arguments:
        visible = (
            html.unescape(re.sub("<[^>]*>", "", arguments["text"]))
            if arguments.get("parse_mode") == "HTML"
            else arguments["text"]
        )
        if len(visible.encode("utf-16-le")) // 2 > 4096:
            return await response_received(
                self,
                httpx.Response(
                    400,
                    json={
                        "ok": False,
                        "error_code": 400,
                        "description": "Bad Request: message is too long",
                    },
                    request=request_object,
                ),
                kind,
                token,
            )
    for row in arguments.get("reply_markup", {}).get("inline_keyboard", []):
        for button in row:
            assert len(button.get("callback_data", "").encode("utf-8")) <= 64
    if path.startswith("/file/"):
        record("file-bytes", token, path=kind)
        return await response_received(
            self,
            httpx.Response(
                200, content=b"downloaded media bytes", request=request_object
            ),
            kind,
            token,
        )
    if kind == "getMe":
        result = {
            "id": 999,
            "is_bot": True,
            "first_name": "Bot",
            "username": "test_bot",
        }
    elif kind == "getUpdates":
        inbox = directory(token) / "inbox.jsonl"
        values = (
            [json.loads(line) for line in inbox.read_text().splitlines()]
            if inbox.exists()
            else []
        )
        result = [
            v for v in values if v["update_id"] >= arguments.get("offset", 0)
        ]
        replay = directory(token) / "replay.json"
        if arguments.get("timeout", 0) > 0 and replay.exists():
            result = json.loads(replay.read_text()) + result
            replay.unlink()
            record(
                "service-replayed-update",
                token,
                update_ids=[v["update_id"] for v in result],
            )
        if not result and arguments.get("timeout", 0):
            await asyncio.sleep(0.05)
    elif kind == "getFile":
        configured = directory(token) / "file.json"
        result = {
            "file_id": arguments["file_id"],
            "file_unique_id": "unique-file",
            "file_path": "photos/inbound.jpg",
            "file_size": 22,
        }
        if configured.exists():
            result.update(json.loads(configured.read_text()))
    elif kind in {
        "sendMessage",
        "sendPhoto",
        "sendVideo",
        "sendAudio",
        "sendDocument",
        "sendRichMessage",
    }:
        if (
            mode(token) == "sendMessage-second-reject"
            and COUNTS[token, kind] == 2
        ):
            return await response_received(
                self,
                httpx.Response(
                    400,
                    json={
                        "ok": False,
                        "error_code": 400,
                        "description": "Bad Request: can't parse entities",
                    },
                    request=request_object,
                ),
                kind,
                token,
            )
        result = native_message(token, arguments)
        record("message-effect", token, endpoint=kind, message=result)
        if mode(token) == kind + "-unknown":
            raise httpx.ReadTimeout(
                "result lost after platform effect", request=request_object
            )
    elif kind == "editMessageText":
        result = native_message(token, arguments, edit=True)
        record("edit-effect", token, message=result)
        if mode(token) == kind + "-unknown":
            raise httpx.ReadTimeout(
                "edit result lost after effect", request=request_object
            )
    elif kind in {
        "deleteWebhook",
        "setMyCommands",
        "deleteMessage",
        "sendChatAction",
        "answerCallbackQuery",
    }:
        result = True
    else:
        raise AssertionError("Unimplemented Bot API endpoint: " + kind)
    record(kind + "-success", token, arguments=arguments)
    return await response_received(
        self,
        httpx.Response(
            200, json={"ok": True, "result": result}, request=request_object
        ),
        kind,
        token,
    )


async def close(self):
    token = CLIENT_TOKENS.get(id(self), "123:local-A")
    record("http-close-enter", token, client=id(self))
    if mode(token) == "http-close-fail":
        raise OSError("controlled external HTTP close failure")
    if mode(token) == "http-close-block":
        while mode(token) == "http-close-block":
            await asyncio.sleep(0.01)
    await ORIGINAL_CLOSE(self)
    record("http-close-exit", token, client=id(self))


class ControlledBody(httpx.AsyncByteStream):
    def __init__(self, content, token, timeout):
        self.content, self.token, self.timeout = content, token, timeout

    async def __aiter__(self):
        record("getUpdates-body-enter", self.token, poll_timeout=self.timeout)
        try:
            while mode(self.token) == "getUpdates-body-block":
                await asyncio.sleep(0.01)
            yield self.content
        except asyncio.CancelledError:
            record(
                "getUpdates-body-cancelled",
                self.token,
                poll_timeout=self.timeout,
            )
            raise
        finally:
            record(
                "getUpdates-body-exit", self.token, poll_timeout=self.timeout
            )

    async def aclose(self):
        record(
            "getUpdates-stream-close-enter",
            self.token,
            poll_timeout=self.timeout,
        )
        if mode(self.token) == "getUpdates-close-block":
            try:
                while mode(self.token) == "getUpdates-close-block":
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                record(
                    "getUpdates-stream-close-interrupted",
                    self.token,
                    poll_timeout=self.timeout,
                )
                raise
        record(
            "getUpdates-stream-close-exit",
            self.token,
            poll_timeout=self.timeout,
        )


class ServiceTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        body = await request.aread()
        content_type = request.headers.get("content-type", "")
        data, files = {}, {}
        if content_type.startswith("multipart/form-data"):
            message = BytesParser(policy=email_policy).parsebytes(
                b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
            )
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                value = part.get_payload(decode=True)
                filename = part.get_filename()
                if filename is not None:
                    files[name] = (filename, value, part.get_content_type())
                else:
                    data[name] = value.decode()
        elif body:
            data = dict(parse_qsl(body.decode(), keep_blank_values=True))
        result = await service_request(
            self.client,
            request.method,
            str(request.url),
            data=data,
            files=files,
            timeout=SimpleNamespace(**request.extensions.get("timeout", {})),
        )
        path = unquote(request.url.path)
        token, _, kind = path.split("/bot", 1)[1].partition("/")
        if (
            kind == "getUpdates"
            and payload(data).get("timeout", 0) > 0
            and mode(token)
            in {"getUpdates-body-block", "getUpdates-close-block"}
        ):
            return httpx.Response(
                result.status_code,
                headers=result.headers,
                stream=ControlledBody(
                    result.content, token, payload(data).get("timeout", 0)
                ),
                request=request,
            )
        return result


async def request(self, method, url, **kwargs):
    global REQUEST_SEQUENCE
    REQUEST_SEQUENCE += 1
    ACTIVE_REQUESTS[id(asyncio.current_task())] = str(REQUEST_SEQUENCE)
    token, _, kind = (
        unquote(urlsplit(str(url)).path).split("/bot", 1)[1].partition("/")
    )
    try:
        return await ORIGINAL_REQUEST(self, method, url, **kwargs)
    finally:
        if mode(token) == kind + "-finally-block":
            record(kind + "-finally-enter", token)
            try:
                while mode(token) == kind + "-finally-block":
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                record(kind + "-finally-interrupted", token)
                raise
        record(kind + "-exit", token, task=id(asyncio.current_task()))
        ACTIVE_REQUESTS.pop(id(asyncio.current_task()), None)


def client_init(self, *args, **kwargs):
    self._telegram_test_proxy = kwargs.get("proxy")
    transport = ServiceTransport()
    transport.client = self
    kwargs["transport"] = transport
    kwargs["mounts"] = {
        **kwargs.get("mounts", {}),
        "http://": transport,
        "https://": transport,
        "all://": transport,
    }
    ORIGINAL_INIT(self, *args, **kwargs)


def install():
    global ORIGINAL_CLOSE, ORIGINAL_INIT, ORIGINAL_REQUEST
    ORIGINAL_CLOSE = httpx.AsyncClient.aclose
    ORIGINAL_REQUEST = httpx.AsyncClient.request
    ORIGINAL_INIT = httpx.AsyncClient.__init__
    httpx.AsyncClient.__init__ = client_init
    httpx.AsyncClient.request = request
    httpx.AsyncClient.aclose = close
