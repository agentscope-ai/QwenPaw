"""Appended to the copied SDK; only Discord's external effects are fake."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

work = Path(globals()["WORK"])
LIVE_CLIENTS = {}


def record(kind, directory=None, **data):
    directory = directory or work
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "ledger.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"kind": kind, "pid": os.getpid(), **data}) + "\n"
        )


def mode(directory):
    path = directory / "mode"
    return path.read_text() if path.exists() else ""


async def effect(kind, directory):
    current = mode(directory)
    if current == kind + "-fail-once":
        (directory / "mode").unlink()
        raise TimeoutError("controlled one-shot external failure")
    if current == kind + "-block":
        try:
            while mode(directory) == kind + "-block":
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            record(kind + "-cancelled", directory)
            raise
    if current == kind + "-unknown":
        raise TimeoutError("controlled uncertain Discord result")
    if current == kind + "-cancel":
        raise asyncio.CancelledError()
    statuses = {"reject": 400, "missing": 404, "rate": 429, "server": 503}
    for suffix, status in statuses.items():
        if current == kind + "-" + suffix:
            response = NS(status=status, reason="controlled", headers={})
            error = NotFound if status == 404 else HTTPException
            raise error(response, {"code": 1, "message": "controlled"})


class RemoteMessage:
    def __init__(self, channel, ident):
        self.channel, self.id = channel, int(ident)

    async def edit(self, *, content):
        record(
            "edit",
            self.channel.directory,
            channel_id=self.channel.id,
            message_id=self.id,
            content=content,
        )
        await effect("edit", self.channel.directory)
        return self

    async def delete(self):
        record(
            "delete",
            self.channel.directory,
            channel_id=self.channel.id,
            message_id=self.id,
        )
        await effect("delete", self.channel.directory)


class Typing:
    def __init__(self, channel):
        self.channel = channel

    async def __aenter__(self):
        record(
            "typing-enter", self.channel.directory, channel_id=self.channel.id
        )
        await effect("typing", self.channel.directory)
        return self

    async def __aexit__(self, *_args):
        record(
            "typing-exit", self.channel.directory, channel_id=self.channel.id
        )
        await effect("typing-exit", self.channel.directory)


class RemoteChannel:
    def __init__(self, client, ident):
        self.client, self.id = client, int(ident)

    @property
    def directory(self):
        return self.client.directory

    def typing(self):
        return Typing(self)

    def get_partial_message(self, ident):
        return RemoteMessage(self, ident)

    async def fetch_message(self, ident):
        return RemoteMessage(self, ident)

    async def send(self, content=None, *, file=None, **kwargs):
        self.client.sent += 1
        ident = 10000 + self.client.sent
        data = {"channel_id": self.id, "message_id": ident, "content": content}
        if file is not None:
            data.update(
                filename=file.filename,
                uploaded=list(file.fp.read()),
                file_path=str(file.fp.name),
                file_open=not file.fp.closed,
            )
        record("send", self.directory, **data)
        if (
            mode(self.directory) == "send-second-reject"
            and self.client.sent == 2
        ):
            raise HTTPException(
                NS(status=400, reason="controlled", headers={}),
                {"code": 1, "message": "second rejected"},
            )
        await effect("send", self.directory)
        return RemoteMessage(self, ident)


class RemoteUser:
    def __init__(self, client, ident, *, name="Human", bot=False):
        self.client, self.id, self.name, self.bot = (
            client,
            int(ident),
            name,
            bot,
        )
        self.dm_channel = None

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.id == getattr(other, "id", None)

    async def create_dm(self):
        record("create-dm", self.client.directory, user_id=self.id)
        self.dm_channel = RemoteChannel(self.client, 900000 + self.id)
        return self.dm_channel


class Thread(RemoteChannel):
    def __init__(self, client, ident, parent_id=None, starter_id=None):
        super().__init__(client, ident)
        self.parent_id = parent_id
        self.starter_message = (
            NS(id=starter_id) if starter_id is not None else None
        )


class Attachment:
    def __init__(self, client, value):
        self.client = client
        self.id = int(value.get("id", 5))
        self.filename = value.get("filename", "a.png")
        self.content_type = value.get("content_type", "image/png")
        self.data = value.get("data", "attachment").encode()
        self.failure = value.get("failure", "")

    async def save(self, path):
        record(
            "download",
            self.client.directory,
            path=str(path),
            filename=self.filename,
        )
        if self.failure:
            raise OSError("controlled attachment error")
        await effect("download", self.client.directory)
        Path(path).write_bytes(self.data)


OriginalFile = File


class File(OriginalFile):
    def close(self):
        name = str(getattr(self.fp, "name", ""))
        super().close()
        record("file-close", file_path=name, closed=self.fp.closed)


class Client:
    def __init__(self, *, intents, proxy=None, proxy_auth=None, **kwargs):
        self.directory = work
        self.callbacks, self.tasks = {}, set()
        self.user = RemoteUser(self, 777, name="Bot", bot=True)
        self.ready, self.closed, self.sent = False, False, 0
        self.channels, self.users = {}, {}
        self.intents, self.proxy, self.auth = intents, proxy, proxy_auth

    def event(self, callback):
        self.callbacks[callback.__name__] = callback
        return callback

    def is_ready(self):
        return self.ready

    def get_channel(self, ident):
        record("get-channel", self.directory, channel_id=ident)
        return self.channels.get(int(ident))

    async def fetch_channel(self, ident):
        record("fetch-channel", self.directory, channel_id=ident)
        await effect("fetch", self.directory)
        channel = RemoteChannel(self, ident)
        self.channels[int(ident)] = channel
        return channel

    def get_user(self, ident):
        record("get-user", self.directory, user_id=ident)
        return self.users.get(int(ident))

    async def fetch_user(self, ident):
        record("fetch-user", self.directory, user_id=ident)
        user = RemoteUser(self, ident)
        self.users[int(ident)] = user
        return user

    def message(self, value):
        cid = value.get("channel_id", 123)
        if value.get("is_thread"):
            channel = Thread(self, cid, value.get("parent_id", 12))
        else:
            channel = RemoteChannel(self, cid)
        self.channels[int(cid)] = channel
        roles = [NS(id=ident) for ident in value.get("bot_roles", [88])]
        guild = (
            NS(id=456, get_member=lambda ident: NS(roles=roles))
            if value.get("group")
            else None
        )
        return NS(
            id=value["id"],
            content=value.get("text", "hello"),
            author=RemoteUser(
                self,
                value.get("author_id", 42),
                name=value.get("author_name", "Human"),
                bot=value.get("bot", False),
            ),
            guild=guild,
            channel=channel,
            attachments=[
                Attachment(self, row) for row in value.get("attachments", [])
            ],
            mentions=[self.user] if value.get("mention") else [],
            role_mentions=[NS(id=ident) for ident in value.get("roles", [])],
            mention_everyone=value.get("everyone", False),
            thread=(
                NS(id=value["thread_id"]) if value.get("thread_id") else None
            ),
            flags=NS(has_thread=value.get("has_thread", False)),
        )

    async def dispatch(self, callback, value=None):
        record("callback", self.directory, callback=callback)
        try:
            handler = self.callbacks[callback]
            await handler(*(() if value is None else (value,)))
        finally:
            record("callback-end", self.directory, callback=callback)

    async def start(self, token, *, reconnect=True):
        self.directory = work / token
        LIVE_CLIENTS[token] = self
        self.directory.mkdir(parents=True, exist_ok=True)
        record(
            "gateway",
            self.directory,
            token=token,
            reconnect=reconnect,
            sdk_source=__file__,
            proxy=self.proxy,
            auth=[self.auth.login, self.auth.password] if self.auth else None,
            intents={
                key: getattr(self.intents, key)
                for key in (
                    "message_content",
                    "dm_messages",
                    "messages",
                    "guilds",
                )
            },
        )
        await effect("gateway", self.directory)
        self.ready = True
        await self.dispatch("on_ready")
        offset = 0
        try:
            while not self.closed:
                inbox = self.directory / "inbox.jsonl"
                lines = (
                    inbox.read_text().splitlines() if inbox.exists() else []
                )
                while offset < len(lines):
                    value = json.loads(lines[offset])
                    offset += 1
                    if value.get("kind") == "thread":
                        event = Thread(
                            self,
                            value["thread_id"],
                            value.get("parent_id", 123),
                            value.get("starter_id"),
                        )
                        callback = "on_thread_create"
                    else:
                        event, callback = self.message(value), "on_message"
                    task = asyncio.create_task(self.dispatch(callback, event))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                await asyncio.sleep(0.01)
        finally:
            record(
                "gateway-exit", self.directory, callbacks_alive=len(self.tasks)
            )

    async def close(self):
        record("gateway-close", self.directory)
        await effect("close", self.directory)
        self.closed, self.ready = True, False
