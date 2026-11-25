# -*- coding: utf-8 -*-
"""Check URLs emitted by Click commands without opening connections."""
import json
from functools import partial

import httpx
import pytest
from click.testing import CliRunner

from qwenpaw.cli.main import cli
from qwenpaw.config.utils import LastApiEndpoint


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
        "qwenpaw.cli.main.read_last_api_record",
        lambda: LastApiEndpoint("127.0.0.1", 9002),
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


@pytest.fixture
def recorded_endpoint(monkeypatch, tmp_path):
    from qwenpaw.config import utils

    path = tmp_path / "config.json"
    monkeypatch.setattr(utils, "get_config_path", lambda: path)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.setattr(utils, "_runtime_last_api", None)
    monkeypatch.delenv("QWENPAW_RUNTIME_ID", raising=False)

    def write(record):
        path.write_text(
            json.dumps(
                {"last_api": {"host": "127.0.0.1", "port": 9002, **record}},
            ),
            encoding="utf-8",
        )

    return write


@pytest.mark.parametrize(
    "record, env_mount, options, url",
    [
        (
            {"base_path": "/paw/api"},
            None,
            [],
            "http://127.0.0.1:9002/paw/api/api/chats",
        ),
        ({"base_path": ""}, "/client", [], "http://127.0.0.1:9002/api/chats"),
        ({}, "/client/", [], "http://127.0.0.1:9002/client/api/chats"),
        (
            {"base_path": "/running"},
            None,
            ["--port", "8088"],
            "http://127.0.0.1:8088/api/chats",
        ),
        (
            {"base_path": "/running"},
            "/client",
            ["--host", "other.test"],
            "http://other.test:9002/client/api/chats",
        ),
        (
            {"base_path": "/running"},
            "/client",
            ["--host", "127.0.0.1", "--port", "9002"],
            "http://127.0.0.1:9002/running/api/chats",
        ),
        (
            {"base_path": "/running"},
            "not-a-path",
            [],
            "http://127.0.0.1:9002/running/api/chats",
        ),
    ],
)
def test_click_discovers_recorded_mount(
    monkeypatch,
    recorded_endpoint,
    record,
    env_mount,
    options,
    url,
):
    recorded_endpoint(record)
    if env_mount is None:
        monkeypatch.delenv("QWENPAW_BASE_PATH", raising=False)
    else:
        monkeypatch.setenv("QWENPAW_BASE_PATH", env_mount)
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    result = CliRunner().invoke(cli, [*options, "chats", "list"])

    assert result.exit_code == 0, result.exception
    assert requests == [url]


def test_explicit_url_ignores_mount_record_and_env(
    monkeypatch,
    recorded_endpoint,
):
    recorded_endpoint({"base_path": "/running"})
    monkeypatch.setenv("QWENPAW_BASE_PATH", "not-a-path")
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    result = CliRunner().invoke(
        cli,
        ["chats", "list", "--base-url", "https://example.test/custom/api/"],
    )

    assert result.exit_code == 0, result.exception
    assert requests == ["https://example.test/custom/api/chats"]


def test_standalone_plugin_discovery_uses_same_record(
    monkeypatch,
    recorded_endpoint,
):
    from qwenpaw.cli.plugin_commands import _get_api_base

    recorded_endpoint({"base_path": "/server/api"})
    monkeypatch.setenv("QWENPAW_BASE_PATH", "/client")

    assert _get_api_base() == "http://127.0.0.1:9002/server/api/api"
