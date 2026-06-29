# -*- coding: utf-8 -*-
from __future__ import annotations

from click.testing import CliRunner

from qwenpaw.cli.main import cli


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, bool]:
        return {"success": True}


class _Client:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def post(self, path: str, *, json: dict, headers: dict) -> _Response:
        self.posts.append({"path": path, "json": json, "headers": headers})
        return _Response()


def test_channels_send_passes_dingtalk_mentions(monkeypatch) -> None:
    http_client = _Client()
    monkeypatch.setattr(
        "qwenpaw.cli.channels_cmd.client",
        lambda _base_url: http_client,
    )

    result = CliRunner().invoke(
        cli,
        [
            "channels",
            "send",
            "--agent-id",
            "bot",
            "--channel",
            "dingtalk",
            "--target-user",
            "user",
            "--target-session",
            "session",
            "--text",
            "hello",
            "--at-user-ids",
            "staff-1,staff-2",
            "--at-user-ids",
            "staff-3",
            "--at-dingtalk-ids",
            "dt-1",
            "--at-all",
        ],
    )

    assert result.exit_code == 0
    assert http_client.posts == [
        {
            "path": "/messages/send",
            "headers": {"X-Agent-Id": "bot"},
            "json": {
                "channel": "dingtalk",
                "target_user": "user",
                "target_session": "session",
                "text": "hello",
                "at_user_ids": ["staff-1", "staff-2", "staff-3"],
                "at_dingtalk_ids": ["dt-1"],
                "is_at_all": True,
            },
        },
    ]
