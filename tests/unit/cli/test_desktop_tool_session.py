# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Desktop shell CLI capabilities cross the real child-process boundary."""

import asyncio
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit
from functools import partial

import httpx
import pytest
from starlette.requests import HTTPConnection

from qwenpaw.tauri import env as desktop_env
from qwenpaw.utils.runtime_api import (
    TOOL_ENV_KEYS,
    TOOL_ORIGIN_ENV,
    TOOL_SESSION_HEADER,
    TOOL_TOKEN_ENV,
    tool_api_environment,
    verify_tool_session,
)
from qwenpaw.utils.runtime_api import (
    api_client,
    async_api_client,
    read_runtime_api,
)


def connection(token, *, path="/api/cron/jobs", method="GET", kind="http"):
    origin, _ = desktop_env.get_desktop_session()
    return HTTPConnection(
        {
            "type": kind,
            "method": method,
            "path": path,
            "headers": [
                (b"host", origin[7:].encode()),
                (TOOL_SESSION_HEADER.lower().encode(), token.encode()),
            ],
        },
    )


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(
        desktop_env,
        "_desktop_origin",
        "http://127.0.0.1:8765",
    )
    monkeypatch.setattr(desktop_env, "_desktop_token", "native-master-fixture")
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path / "working"))
    monkeypatch.setenv("QWENPAW_SECRET_DIR", str(tmp_path / "secret"))
    for key in (
        *TOOL_ENV_KEYS,
        "QWENPAW_DESKTOP_SESSION",
        "QWENPAW_RUNTIME_INTERNAL_TOKEN",
        "QWENPAW_RUNTIME_ID",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(name="receiver")
def receiver_fixture(monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            path = urlsplit(self.path).path
            request = HTTPConnection(
                {
                    "type": "http",
                    "method": self.command,
                    "path": path,
                    "headers": [
                        (key.lower().encode(), value.encode())
                        for key, value in self.headers.items()
                    ],
                },
            )
            accepted = verify_tool_session(request)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append(
                (
                    self.command,
                    path,
                    accepted,
                    self.headers.get("X-Agent-Id"),
                    body,
                    self.headers.get("X-Desktop-Session"),
                ),
            )
            payload = json.dumps({"ok": accepted}).encode()
            self.send_response(200 if accepted else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        origin = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setattr(desktop_env, "_desktop_origin", origin)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield origin, seen
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize(
    "arguments,path,method",
    [
        (["cron", "list"], "/api/cron/jobs", "GET"),
        (["chats", "list", "--agent-id", "other-agent"], "/api/chats", "GET"),
        (
            [
                "channels",
                "send",
                "--agent-id",
                "other-agent",
                "--channel",
                "console",
                "--target-user",
                "fixture",
                "--target-session",
                "fixture",
                "--text",
                "harmless fixture",
            ],
            "/api/messages/send",
            "POST",
        ),
    ],
)
def test_real_cli_child_discovers_origin_and_authenticates(
    receiver,
    arguments,
    path,
    method,
):
    origin, seen = receiver
    # Even a broken discovery implementation must target this isolated
    # receiver, never an unrelated service at the default application port.
    script = (
        "from qwenpaw.cli import main; "
        f"main.read_last_api=lambda:('127.0.0.1',{urlsplit(origin).port}); "
        "main.cli()"
    )
    with tool_api_environment(os.environ) as child:
        result = subprocess.run(
            [sys.executable, "-c", script, *arguments],
            env=child,
            capture_output=True,
            check=False,
            text=True,
            timeout=45,
        )
    assert result.returncode == 0, result.stderr
    assert seen[0][:3] == (method, path, True)
    assert seen[0][5] is None
    if path != "/api/cron/jobs":
        assert seen[0][3] == "other-agent"
    if method == "POST":
        assert json.loads(seen[0][4])["text"] == "harmless fixture"


def test_capability_lifecycle_concurrency_and_restart():
    with tool_api_environment(os.environ) as first:
        token1 = first[TOOL_TOKEN_ENV]
        with tool_api_environment(os.environ) as second:
            token2 = second[TOOL_TOKEN_ENV]
            assert token1 != token2 != desktop_env._desktop_token
            assert verify_tool_session(connection(token1))
            assert verify_tool_session(connection(token2))
            assert all(key not in os.environ for key in TOOL_ENV_KEYS)
        assert not verify_tool_session(connection(token2))
        assert verify_tool_session(connection(token1))
        desktop_env._desktop_token = "replacement-native-master"
        assert not verify_tool_session(connection(token1))
    assert TOOL_TOKEN_ENV not in first


def test_copied_environment_excludes_native_and_stale_credentials():
    original = {
        "QWENPAW_DESKTOP_SESSION": "native-master-fixture",
        TOOL_TOKEN_ENV: "stale",
        TOOL_ORIGIN_ENV: "http://other.example",
        "OTHER": "unchanged",
    }
    with tool_api_environment(original) as child:
        assert "QWENPAW_DESKTOP_SESSION" not in child
        assert child[TOOL_TOKEN_ENV] != original[TOOL_TOKEN_ENV]
        assert child[TOOL_ORIGIN_ENV] == desktop_env.get_desktop_session()[0]
        assert child["OTHER"] == "unchanged"
    assert original["QWENPAW_DESKTOP_SESSION"] == "native-master-fixture"
    assert original[TOOL_TOKEN_ENV] == "stale"


@pytest.mark.parametrize("runtime_id", ["hub-runtime", "desktop-tool"])
def test_no_desktop_preserves_hub_but_drops_borrowed_credentials(
    monkeypatch,
    runtime_id,
):
    monkeypatch.setattr(desktop_env, "_desktop_origin", "")
    monkeypatch.setattr(desktop_env, "_desktop_token", "")
    original = {
        "QWENPAW_RUNTIME_ID": runtime_id,
        TOOL_TOKEN_ENV: "existing-runtime-token",
        TOOL_ORIGIN_ENV: "http://127.0.0.1:9001",
    }
    with tool_api_environment(original) as child:
        assert child == (original if runtime_id == "hub-runtime" else {})
    assert len(original) == 3


@pytest.mark.parametrize(
    "method,path,kind",
    [
        ("GET", "/api/mcp", "http"),
        ("POST", "/api/auth/logout", "http"),
        ("GET", "/api/files/preview/private", "http"),
        ("GET", "/console", "http"),
        ("GET", "/api/chats", "websocket"),
        ("POST", "/api/agents/something", "http"),
    ],
)
def test_capability_does_not_authorize_unrelated_interfaces(
    method,
    path,
    kind,
):
    with tool_api_environment(os.environ) as child:
        assert not verify_tool_session(
            connection(
                child[TOOL_TOKEN_ENV],
                method=method,
                path=path,
                kind=kind,
            ),
        )


@pytest.mark.parametrize(
    "exception",
    [RuntimeError, TimeoutError, asyncio.CancelledError],
)
def test_capability_revoked_on_exception_timeout_and_cancel(exception):
    with pytest.raises(exception):
        with tool_api_environment(os.environ) as child:
            token = child[TOOL_TOKEN_ENV]
            assert verify_tool_session(connection(token))
            raise exception()
    assert not verify_tool_session(connection(token))


def test_plain_child_cannot_access_desktop(receiver):
    origin, seen = receiver
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import httpx,sys; "
            "print(httpx.get(sys.argv[1],trust_env=False).status_code)",
            origin + "/api/cron/jobs",
        ],
        env=os.environ.copy(),
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "401"
    assert not seen[0][2]


def test_cli_without_child_handoff_is_rejected(receiver):
    """The pre-fix child handoff fails at the receiver (negative control)."""
    origin, seen = receiver
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from qwenpaw.cli.main import cli; cli()",
            "--port",
            str(urlsplit(origin).port),
            "chats",
            "list",
        ],
        env=os.environ.copy(),
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )
    assert result.returncode != 0
    assert "401 Unauthorized" in result.stderr
    assert seen[0][:3] == ("GET", "/api/chats", False)


@pytest.mark.asyncio
async def test_real_shell_entry_lends_and_revokes_cli_capability(
    receiver,
    monkeypatch,
    tmp_path,
):
    from qwenpaw.agents.tools import shell
    from qwenpaw.utils import runtime_api as tool_session

    _, seen = receiver
    monkeypatch.setattr(shell, "get_tool_base_dir", lambda: tmp_path)
    monkeypatch.setattr(
        shell,
        "get_current_shell_command_executable",
        lambda: "cmd.exe" if sys.platform == "win32" else "/bin/sh",
    )
    script = tmp_path / "child.py"
    script.write_text(
        "from qwenpaw.utils.runtime_api import api_client, read_runtime_api\n"
        "host, port = read_runtime_api()\n"
        "with api_client(f'http://{host}:{port}') as client:\n"
        " print(client.get('/api/cron/jobs').status_code)\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script}"'
    result = await shell.execute_shell_command(command, timeout=30)
    assert seen, result.content
    assert seen[0][:3] == ("GET", "/api/cron/jobs", True)
    assert "200" in str(result.content)
    assert not tool_session._active_tools
    assert all(key not in os.environ for key in TOOL_ENV_KEYS)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception",
    [RuntimeError, TimeoutError, asyncio.CancelledError],
)
async def test_shell_revokes_on_host_exception(
    monkeypatch,
    tmp_path,
    exception,
):
    from qwenpaw.agents.tools import shell

    monkeypatch.setattr(shell, "get_tool_base_dir", lambda: tmp_path)
    tokens = []

    async def fail(_command, _cwd, _timeout, child, _shell):
        tokens.append(child[TOOL_TOKEN_ENV])
        assert verify_tool_session(connection(tokens[-1]))
        assert "QWENPAW_DESKTOP_SESSION" not in child
        raise exception()

    monkeypatch.setattr(shell, "_execute_windows_host", fail)
    monkeypatch.setattr(shell, "_execute_posix_host", fail)
    if exception is asyncio.CancelledError:
        with pytest.raises(exception):
            await shell.execute_shell_command("fixture", timeout=0.1)
    else:
        await shell.execute_shell_command("fixture", timeout=0.1)
    assert len(tokens) == 1
    assert not verify_tool_session(connection(tokens[0]))


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_child_clients_strip_credentials_on_redirect_and_foreign_base(
    monkeypatch,
    asynchronous,
):
    monkeypatch.setattr(desktop_env, "_desktop_token", "")
    origin = "http://127.0.0.1:8765"
    monkeypatch.setenv(TOOL_ORIGIN_ENV, origin)
    monkeypatch.setenv(TOOL_TOKEN_ENV, "a" * 43)
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "desktop-tool")
    seen = []

    def respond(request):
        seen.append(
            (
                request.headers.get(TOOL_SESSION_HEADER),
                request.headers.get("X-Desktop-Session"),
            ),
        )
        if request.url.port == 8765:
            return httpx.Response(
                307,
                headers={"Location": "http://127.0.0.1:8766/api/chats"},
            )
        return httpx.Response(200)

    target = httpx.AsyncClient if asynchronous else httpx.Client
    monkeypatch.setattr(
        httpx,
        "AsyncClient" if asynchronous else "Client",
        partial(target, transport=httpx.MockTransport(respond)),
    )
    headers = {TOOL_SESSION_HEADER: "stale", "X-Desktop-Session": "stale"}
    if asynchronous:
        async with async_api_client(origin) as client:
            await client.get(
                "/api/chats",
                headers=headers,
                follow_redirects=True,
            )
        async with async_api_client("http://foreign.example") as client:
            await client.get(origin + "/api/chats", headers=headers)
    else:
        with api_client(origin) as client:
            client.get("/api/chats", headers=headers, follow_redirects=True)
        with api_client("http://foreign.example") as client:
            client.get(origin + "/api/chats", headers=headers)
    assert seen == [("a" * 43, None), (None, None), (None, None)]
    assert read_runtime_api() == ("127.0.0.1", 8765)


@pytest.mark.parametrize(
    "origin",
    [
        "http://user:pass@127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:8765/path",
        "http://127.0.0.1:8765/?query=1",
        "https://127.0.0.1:8765",
        "http://external.example:8765",
        "http://127.0.0.1:8765#fragment",
        "http://127.0.0.1:bad",
    ],
)
def test_malformed_private_endpoint_is_not_trusted(monkeypatch, origin):
    monkeypatch.setattr(desktop_env, "_desktop_token", "")
    monkeypatch.setenv(TOOL_ORIGIN_ENV, origin)
    monkeypatch.setenv(TOOL_TOKEN_ENV, "a" * 43)
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "desktop-tool")
    assert read_runtime_api() is None


def test_real_boundary_keeps_account_authentication(monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from qwenpaw.app import auth

    monkeypatch.setenv("QWENPAW_DESKTOP_APP", "1")
    monkeypatch.setenv("QWENPAW_DESKTOP_AUTH", "1")
    monkeypatch.setattr(
        auth.AuthMiddleware,
        "_should_skip_auth",
        staticmethod(lambda _: False),
    )
    monkeypatch.setattr(
        auth,
        "verify_token",
        lambda token: "fixture-user" if token == "account-valid" else None,
    )
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(auth.RuntimeBoundaryMiddleware)
    hits = []

    @app.post("/api/messages/send")
    async def receive(request: Request):
        hits.append(request.state.user)
        return {"ok": True}

    with tool_api_environment(os.environ) as child, TestClient(
        app,
        base_url=child[TOOL_ORIGIN_ENV],
    ) as client:
        headers = {TOOL_SESSION_HEADER: child[TOOL_TOKEN_ENV]}
        assert (
            client.post("/api/messages/send", headers=headers).status_code
            == 401
        )
        assert not hits
        headers["Authorization"] = "Bearer account-valid"
        assert (
            client.post("/api/messages/send", headers=headers).status_code
            == 200
        )
        assert hits == ["fixture-user"]
        assert (
            client.post(
                "/api/messages/send",
                headers={**headers, "Origin": "http://other.example"},
            ).status_code
            == 403
        )
