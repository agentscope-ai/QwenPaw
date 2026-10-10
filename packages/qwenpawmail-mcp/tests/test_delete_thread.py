# -*- coding: utf-8 -*-
"""Regression tests for partial thread deletion."""

import asyncio
import re
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from qwenpawmail_mcp.config import load_config
from qwenpawmail_mcp.errors import MailError
from qwenpawmail_mcp.server import create_server
from qwenpawmail_mcp.thread_store import ThreadStore


_HAN_RE = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class _Client:
    def __init__(self, failed_uids=()):
        self.failed_uids = {str(uid) for uid in failed_uids}
        self.moved = []

    @staticmethod
    def list_folders():
        return [{"name": "Trash", "flags": [r"\Trash"]}]

    def move_message(self, folder, uid, target_folder):
        if str(uid) in self.failed_uids:
            raise OSError(f"cannot move {uid}")
        self.moved.append((folder, str(uid), target_folder))
        return {"moved": True}


class _NoTrashClient(_Client):
    @staticmethod
    def list_folders():
        return [{"name": "INBOX", "flags": []}]


def _config():
    return load_config(
        {
            "QWENPAWMAIL_EMAIL": "tester@163.com",
            "QWENPAWMAIL_AUTH_CODE": "secret",
        },
    )


def _seed_thread(state_dir, folders):
    store = ThreadStore.for_email(state_dir, "tester@163.com")
    thread_id = ""
    for index, folder in enumerate(folders, start=1):
        message_id = f"<message-{index}@example.com>"
        thread_id = store.add_message(
            {
                "uid": str(index),
                "message_id": message_id,
                "references": "<message-1@example.com>" if index > 1 else "",
                "subject": "thread",
                "from": "alice@example.com",
                "to": "tester@163.com",
            },
            folder,
            "trash" if folder == "Trash" else "inbox",
        )
    store.save()
    return thread_id


def _delete_thread(server, thread_id):
    return asyncio.run(
        server._tool_manager.call_tool(  # pylint: disable=protected-access
            "delete_thread",
            {"thread_id": thread_id},
            convert_result=False,
        ),
    )


def test_partial_delete_keeps_failed_message_indexed(tmp_path):
    thread_id = _seed_thread(tmp_path, ["INBOX", "INBOX"])
    client = _Client(failed_uids={"2"})
    with patch.dict(
        "os.environ",
        {"QWENPAWMAIL_STATE_DIR": str(tmp_path)},
    ):
        result = _delete_thread(create_server(_config(), client), thread_id)

    assert result["deleted"] is False
    assert result["partial"] is True
    assert result["moved_count"] == 1
    assert [error["uid"] for error in result["errors"]] == ["2"]
    remaining = ThreadStore.for_email(
        tmp_path,
        "tester@163.com",
    ).thread_messages(thread_id)
    assert [(message["folder"], message["uid"]) for message in remaining] == [
        ("INBOX", "2"),
    ]


def test_delete_thread_already_in_trash_removes_index(tmp_path):
    thread_id = _seed_thread(tmp_path, ["Trash", "Trash"])
    client = _Client()
    with patch.dict(
        "os.environ",
        {"QWENPAWMAIL_STATE_DIR": str(tmp_path)},
    ):
        result = _delete_thread(create_server(_config(), client), thread_id)

    assert result["deleted"] is True
    assert result["moved_count"] == 0
    assert not client.moved
    with pytest.raises(MailError, match="not found"):
        ThreadStore.for_email(
            tmp_path,
            "tester@163.com",
        ).thread_messages(thread_id)


def test_delete_thread_total_failure_error_is_english(tmp_path):
    thread_id = _seed_thread(tmp_path, ["INBOX", "INBOX"])
    client = _Client(failed_uids={"1", "2"})
    with patch.dict(
        "os.environ",
        {"QWENPAWMAIL_STATE_DIR": str(tmp_path)},
    ):
        with pytest.raises(ToolError) as error:
            _delete_thread(create_server(_config(), client), thread_id)

    message = str(error.value)
    assert _HAN_RE.search(message) is None
    assert "All 2 messages failed to move to the trash folder" in message
    assert "First error: cannot move 1\nTry deleting" in message


def test_delete_thread_missing_trash_error_is_english(tmp_path):
    thread_id = _seed_thread(tmp_path, ["INBOX"])
    with patch.dict(
        "os.environ",
        {"QWENPAWMAIL_STATE_DIR": str(tmp_path)},
    ):
        with pytest.raises(ToolError) as error:
            _delete_thread(
                create_server(_config(), _NoTrashClient()),
                thread_id,
            )

    message = str(error.value)
    assert _HAN_RE.search(message) is None
    assert "No trash folder was found" in message
