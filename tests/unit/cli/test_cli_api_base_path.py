# -*- coding: utf-8 -*-
"""Check URLs emitted by Click commands without opening connections."""
from functools import partial

import httpx
import pytest
from click.testing import CliRunner

from qwenpaw.cli.main import cli


@pytest.mark.parametrize(
    "command, routes",
    [
        (("cron", "list"), [("GET", "/cron/jobs")]),
        (
            ("auto", "crons-list_jobs"),
            [("HEAD", "/version"), ("GET", "/crons/jobs")],
        ),
        (("chats", "list"), [("GET", "/chats")]),
        (("agents", "list"), [("GET", "/agents")]),
        (
            ("agents", "chat", "--background", "--task-id", "demo"),
            [("GET", "/console/chat/task/demo")],
        ),
        (
            (
                "channels",
                "send",
                "--agent-id",
                "default",
                "--channel",
                "console",
                "--target-user",
                "demo",
                "--target-session",
                "demo",
                "--text",
                "hello",
            ),
            [("POST", "/messages/send")],
        ),
    ],
)
@pytest.mark.parametrize(
    "mount, override, endpoint",
    [
        ("/api/", None, "http://127.0.0.1:9002/api/api"),
        ("/paw/api/", None, "http://127.0.0.1:9002/paw/api/api"),
        ("/paw/", None, "http://127.0.0.1:9002/paw/api"),
        ("/", None, "http://127.0.0.1:9002/api"),
        (
            "/api/",
            "https://example.test/custom",
            "https://example.test/custom/api",
        ),
        (
            "/api/",
            "https://example.test/custom/api/",
            "https://example.test/custom/api",
        ),
    ],
)
def test_click_commands_target_api(
    monkeypatch,
    command,
    routes,
    mount,
    override,
    endpoint,
):
    monkeypatch.setenv("QWENPAW_BASE_PATH", mount)
    monkeypatch.setattr("qwenpaw.cli.main.read_runtime_api", lambda: None)
    monkeypatch.setattr(
        "qwenpaw.cli.main.read_last_api",
        lambda: ("127.0.0.1", 9002),
    )
    requests = []

    def respond(request):
        requests.append((request.method, str(request.url)))
        return httpx.Response(200, json={"agents": []})

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    args = list(command)
    if override:
        args.extend(["--base-url", override])
    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.exception
    assert requests == [(method, endpoint + path) for method, path in routes]
