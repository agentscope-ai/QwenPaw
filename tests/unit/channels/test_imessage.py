# -*- coding: utf-8 -*-
"""iMessage uses the native read-only Messages schema and imsg command."""

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import (
    eventually,
    open_route,
    send,
)


@pytest.fixture
async def imessage(tmp_path, monkeypatch):
    db = tmp_path / "messages.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
        CREATE TABLE message (text TEXT, is_from_me INTEGER,
                              handle_id INTEGER);
        CREATE TABLE chat (label TEXT);
        CREATE TABLE handle (id TEXT);
        CREATE TABLE chat_message_join (message_id INTEGER, chat_id INTEGER);
        INSERT INTO chat VALUES ('test chat');
        INSERT INTO handle VALUES ('+15550001111');
        INSERT INTO message VALUES ('before startup',0,1);
        INSERT INTO chat_message_join VALUES (1,1);
        """,
        )
    executable = tmp_path / "imsg"
    executable.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """
import json,pathlib,sys
root=pathlib.Path(__file__).parent
with (root/'commands.jsonl').open('a') as out:
    out.write(json.dumps(sys.argv[1:])+'\\n')
print('sent')
""",
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    native = module("imessage", "platform")
    if sys.platform == "win32":
        spawn = asyncio.create_subprocess_exec

        async def spawn_script(command, *args, **kwargs):
            if command == str(executable):
                return await spawn(sys.executable, command, *args, **kwargs)
            return await spawn(command, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn_script)
    monkeypatch.setattr(native.sys, "platform", "darwin")
    driver = module("imessage").IMessageDriver()
    peer, identity = bind("imessage", driver, tmp_path)
    config = dict(
        enabled=True,
        db_path=str(db),
        poll_sec=0.01,
        workspace_dir=str(tmp_path),
        media_dir=str(tmp_path / "media"),
    )
    await driver.start(config)
    yield driver, peer, identity, db, tmp_path
    await driver.stop()


def insert(db, text, own=0, sender="+15550001111"):
    with sqlite3.connect(db) as conn:
        handle = conn.execute(
            "INSERT INTO handle VALUES (?)",
            (sender,),
        ).lastrowid
        row = conn.execute(
            "INSERT INTO message VALUES (?,?,?)",
            (text, own, handle),
        ).lastrowid
        conn.execute("INSERT INTO chat_message_join VALUES (?,1)", (row,))
    return row


async def receive(value, text="hello", **fields):
    driver, peer, _, db, _ = value
    row = insert(db, text, **fields)
    await eventually(lambda: driver._platform._last_rowid >= row)
    return peer.batches[-1]["events"][0] if peer.batches else None


async def test_only_new_sqlite_rows_enter_host_with_native_identity(imessage):
    _, peer, identity, _, root = imessage
    event = await receive(imessage)
    assert len(peer.batches) == 1
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert event["event_id"] == "imessage:row:2:1"
    assert event["conversation"] == {
        "id": "+15550001111",
        "type": "dm",
        "thread_id": None,
    }
    assert event["acl_sender_id"] == "+15550001111"
    assert event["metadata"]["session_id"] == "imessage:+15550001111"
    assert event["instance_id"] == identity.instance_id
    result = await send(peer, identity, event["response_handle"])
    assert result["state"] == "acknowledged"
    commands = [
        json.loads(line)
        for line in (root / "commands.jsonl").read_text().splitlines()
    ]
    assert commands == [
        ["send", "--to", "+15550001111", "--text", "native answer"],
    ]


@pytest.mark.parametrize("text,own", [("outgoing", 1), ("", 0)])
async def test_outgoing_and_empty_rows_advance_cursor_without_admission(
    imessage,
    text,
    own,
):
    assert await receive(imessage, text, own=own) is None


async def test_proactive_session_resolves_native_destination(imessage):
    driver, peer, identity, _, root = imessage
    handle = await open_route(peer, identity, "imessage:+15559990000")
    assert driver._route_attrs(handle)["sender"] == "+15559990000"
    assert (await send(peer, identity, handle))["state"] == "acknowledged"
    assert "+15559990000" in (root / "commands.jsonl").read_text()


async def test_stop_closes_sqlite_and_owned_watcher(imessage):
    driver, _, _, _, _ = imessage
    platform = driver._platform
    connection, watcher, http = (
        platform._conn,
        platform._watcher,
        platform._http,
    )
    await driver.stop()
    assert watcher.done() and http.is_closed and driver._platform is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    await driver.stop()
