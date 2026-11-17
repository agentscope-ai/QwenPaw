# -*- coding: utf-8 -*-
"""Regression tests for the save_draft tool."""

import asyncio
import re
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from qwenpawmail_mcp.config import load_config
from qwenpawmail_mcp.errors import MailError
from qwenpawmail_mcp.server import create_server

_HAN_RE = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class _Client:
    """Fake client recording save_draft calls (no network)."""

    def __init__(self, append_uid="3955"):
        self.append_uid = append_uid
        self.saved = []

    def list_folders(self):
        return [
            {"name": "INBOX", "flags": []},
            {"name": "Drafts", "flags": [r"\Drafts"]},
        ]

    def save_draft(self, to, subject, body, cc=None, folder=None):
        result = {
            "saved": True,
            "folder": folder or "Drafts",
            "to": to,
            "cc": cc or [],
            "subject": subject,
        }
        if self.append_uid:
            result["uid"] = self.append_uid
        self.saved.append(
            {
                "to": to,
                "subject": subject,
                "body": body,
                "cc": cc,
                "folder": folder,
            },
        )
        return result


def _config():
    return load_config(
        {
            "QWENPAWMAIL_EMAIL": "tester@163.com",
            "QWENPAWMAIL_AUTH_CODE": "secret",
        },
    )


def _call_save_draft(server, arguments):
    return asyncio.run(
        server._tool_manager.call_tool(  # pylint: disable=protected-access
            "save_draft",
            arguments,
            convert_result=False,
        ),
    )


def test_save_draft_registered_and_saves_to_drafts():
    client = _Client()
    server = create_server(_config(), client)

    result = _call_save_draft(
        server,
        {
            "to": "alice@example.com",
            "subject": "hello",
            "body": "draft body",
        },
    )

    assert result["saved"] is True
    assert result["folder"] == "Drafts"
    assert result["uid"] == "3955"
    assert client.saved == [
        {
            "to": ["alice@example.com"],
            "subject": "hello",
            "body": "draft body",
            "cc": [],
            "folder": None,
        },
    ]


def test_save_draft_accepts_cc_and_explicit_folder():
    client = _Client()
    server = create_server(_config(), client)

    result = _call_save_draft(
        server,
        {
            "to": "alice@example.com, bob@example.com",
            "cc": "cc@example.com",
            "subject": "s",
            "body": "b",
            "folder": "草稿箱",
        },
    )

    assert result["folder"] == "草稿箱"
    assert client.saved[0]["to"] == ["alice@example.com", "bob@example.com"]
    assert client.saved[0]["cc"] == ["cc@example.com"]


def test_drafts_folder_autodetect_and_fallback():
    from qwenpawmail_mcp.mail_client import MailClient

    client = MailClient(_config())

    # 优先 \\Drafts 标记
    with patch.object(
        client,
        "list_folders",
        return_value=[
            {"name": "INBOX", "flags": []},
            {"name": "草稿箱", "flags": [r"\Drafts"]},
            {"name": "Drafts", "flags": []},
        ],
    ):
        assert client._drafts_folder() == "草稿箱"

    # 无 \\Drafts 时回退字面 Drafts
    with patch.object(
        client,
        "list_folders",
        return_value=[
            {"name": "INBOX", "flags": []},
            {"name": "Drafts", "flags": []},
        ],
    ):
        assert client._drafts_folder() == "Drafts"

    # 都没有时报英文错误
    with patch.object(
        client,
        "list_folders",
        return_value=[
            {"name": "INBOX", "flags": []},
        ],
    ):
        with pytest.raises(MailError) as error:
            client._drafts_folder()
        message = str(error.value)
        assert _HAN_RE.search(message) is None
        assert "Drafts folder" in message
