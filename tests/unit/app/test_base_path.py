# -*- coding: utf-8 -*-
"""Runtime base-path mounting keeps application routes prefix-aware."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.routing import get_route_path

from qwenpaw.app.base_path import (
    BasePathMiddleware,
    ConsoleIndexResponse,
    normalize_base_path,
)
from qwenpaw.channel_protocol.models import HostForwardingBinding


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("/", ""),
        (" / ", ""),
        (" /demo ", "/demo"),
        ("/app/qwenpaw/web/", "/app/qwenpaw/web"),
        (" /my console/ ", "/my console"),
        ("/app/中文/", "/app/中文"),
        ("/demo /中文/", "/demo /中文"),
    ],
)
def test_normalize_base_path(value, expected):
    normalized = normalize_base_path(value)
    assert normalized == expected
    assert normalize_base_path(normalized) == normalized


@pytest.mark.parametrize(
    "value",
    [
        "app/qwenpaw",
        "/demo /",
        " /demo /// ",
        "/demo\u00a0/",
        "/app//qwenpaw",
        "/app/../admin",
        "/app/%2e%2e/admin",
        "/app%2fadmin",
        "/app?x=1",
        "/app#x",
        "/app/%71wenpaw/web",
        "/app/qwenpaw%20web",
        "/app/%2571wenpaw/web",
    ],
)
def test_normalize_base_path_rejects_ambiguous_paths(value):
    with pytest.raises(ValueError):
        normalize_base_path(value)


@pytest.mark.parametrize(
    "value",
    ["/app\tname", "/app\x1fname", "/app\x7fname", "/app\n"],
)
def test_normalize_base_path_rejects_control_characters(value):
    with pytest.raises(
        ValueError,
        match="QWENPAW_BASE_PATH.*control characters",
    ):
        normalize_base_path(value)


def test_forwarding_binding_preserves_optional_base_path():
    fields = {
        "route_query_key": "_qp_endpoint",
        "route_selector": "voice/private:scope",
        "host_port": 18433,
        "paths": ["/voice/incoming"],
        "bridge_token": "private-bridge-token",
    }
    root = HostForwardingBinding.from_mapping(fields)
    assert root.base_path == ""
    assert "base_path" not in root.to_mapping()

    mounted = HostForwardingBinding.from_mapping(
        {**fields, "base_path": "/my console"},
    )
    assert mounted.base_path == "/my console"
    assert (
        HostForwardingBinding.from_mapping(
            mounted.to_mapping(),
        )
        == mounted
    )


def _mounted_app(base_path: str = "/app/qwenpaw/web") -> FastAPI:
    application = FastAPI()
    application.add_middleware(BasePathMiddleware, base_path=base_path)

    @application.get("/api/version", name="version")
    def version(request: Request):
        return {
            "path": get_route_path(request.scope),
            "root_path": request.scope["root_path"],
            "url": str(request.url_for("version")),
        }

    @application.websocket("/api/events")
    async def events(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"root_path": websocket.scope["root_path"]})
        await websocket.close()

    return application


def test_prefixed_http_and_websocket_routes_share_the_same_mount():
    with TestClient(_mounted_app()) as client:
        response = client.get("/app/qwenpaw/web/api/version")
        assert response.status_code == 200
        assert response.json() == {
            "path": "/api/version",
            "root_path": "/app/qwenpaw/web",
            "url": "http://testserver/app/qwenpaw/web/api/version",
        }
        assert client.get("/api/version").status_code == 404
        assert (
            client.get("/app/qwenpaw/web-other/api/version").status_code == 404
        )

        with client.websocket_connect("/app/qwenpaw/web/api/events") as socket:
            assert socket.receive_json() == {"root_path": "/app/qwenpaw/web"}


def test_mount_root_redirects_to_slash_without_losing_the_query():
    with TestClient(_mounted_app(), follow_redirects=False) as client:
        response = client.get("/app/qwenpaw/web?from=fnos")
        assert response.status_code == 307
        assert response.headers["location"] == "/app/qwenpaw/web/?from=fnos"


@pytest.mark.parametrize("base_path", [None, "", "/"])
def test_root_console_index_preserves_file_response(tmp_path, base_path):
    index = tmp_path / "index.html"
    content = (
        b'<base href="/" />' b'<meta name="qwenpaw-base-path" content="" />'
    )
    index.write_bytes(content)
    application = FastAPI()

    @application.get("/")
    def index_response():
        return ConsoleIndexResponse(index, base_path=base_path)

    with TestClient(application) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.content == content
        assert response.headers["etag"]
        assert response.headers["last-modified"]


def test_console_index_serves_runtime_meta_under_strict_script_csp(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(
        "<html><head>"
        '<meta http-equiv="Content-Security-Policy" content="script-src \'self\'">'
        '<base href="/" />'
        '<meta name="qwenpaw-base-path" content="" />'
        '</head><body><script src="./assets/index.js"></script></body></html>',
        encoding="utf-8",
    )
    application = FastAPI()

    @application.get("/")
    def index_response():
        return ConsoleIndexResponse(index, base_path="/app/qwenpaw/web")

    with TestClient(application) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert '<base href="/app/qwenpaw/web/">' in response.text
        assert (
            '<meta name="qwenpaw-base-path" ' 'content="/app/qwenpaw/web" />'
        ) in response.text
        assert "script-src 'self'" in response.text
        assert '<script src="./assets/index.js"></script>' in response.text
        assert response.text.count("<script") == 1
        assert response.headers["content-length"] == str(len(response.content))


def test_console_index_updates_legacy_runtime_base_for_old_bundle(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(
        '<base href="/" /><script>window.__qpBase = "";</script>',
        encoding="utf-8",
    )
    application = FastAPI()

    @application.get("/")
    def index_response():
        return ConsoleIndexResponse(index, base_path="/review-mount")

    with TestClient(application) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert '<base href="/review-mount/">' in response.text
        assert 'window.__qpBase = "/review-mount";' in response.text
        assert 'window.__qpBase = "";' not in response.text


def test_console_index_escapes_meta_and_legacy_runtime_config(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(
        '<base href="/" />'
        '<meta name="qwenpaw-base-path" content="" />'
        '<script>window.__qpBase = "";</script>',
        encoding="utf-8",
    )
    application = FastAPI()
    malicious_path = '/app/"><script>alert(1)</script>'
    application.get("/")(
        lambda: ConsoleIndexResponse(index, base_path=malicious_path),
    )

    with TestClient(application) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert (
            'content="/app/&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"'
            in response.text
        )
        assert (
            r'window.__qpBase = "/app/\"\u003e\u003cscript\u003e'
            r'alert(1)\u003c/script\u003e";' in response.text
        )
        assert '"><script>alert(1)</script>' not in response.text
        assert response.text.count("<script>") == 1
        assert response.text.count("</script>") == 1


def test_production_app_rejects_noncanonical_base_path_at_startup(tmp_path):
    env = {
        **os.environ,
        "QWENPAW_BASE_PATH": "/demo /",
        "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        "QWENPAW_TELEMETRY_DISABLED": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", "from qwenpaw.app import _app"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert (
        "ValueError: QWENPAW_BASE_PATH must not end with whitespace"
        in result.stderr
    )


def test_production_app_serves_api_console_and_assets_below_base_path(
    tmp_path,
):
    console = tmp_path / "console"
    assets = console / "assets"
    assets.mkdir(parents=True)
    (console / "index.html").write_text(
        '<base href="/" />'
        '<meta name="qwenpaw-base-path" content="" />'
        '<script type="module" src="./assets/index.js"></script>',
        encoding="utf-8",
    )
    (assets / "index.js").write_text(
        "export const asset = 'unmodified';\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "QWENPAW_BASE_PATH": "/app/qwenpaw/web",
        "QWENPAW_CONSOLE_STATIC_DIR": str(console),
        "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        "QWENPAW_TELEMETRY_DISABLED": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                from fastapi.testclient import TestClient
                from qwenpaw.app import _app

                client = TestClient(_app.app, follow_redirects=False)
                assert client.get("/api/version").status_code == 404
                version = client.get("/app/qwenpaw/web/api/version")
                assert version.status_code == 200, version.text
                assert version.json()["version"]
                redirect = client.get("/app/qwenpaw/web?from=fnos")
                assert redirect.status_code == 307
                assert redirect.headers["location"] == "/app/qwenpaw/web/?from=fnos"
                for route in ("", "index.html", "chat", "chat/"):
                    path = "/app/qwenpaw/web/" + route
                    page = client.get(path)
                    assert page.status_code == 200, path
                    assert '<base href="/app/qwenpaw/web/">' in page.text
                    assert (
                        '<meta name="qwenpaw-base-path" '
                        'content="/app/qwenpaw/web" />'
                    ) in page.text
                    assert "<script>" not in page.text
                    assert 'src="./assets/index.js"' in page.text
                asset = client.get("/app/qwenpaw/web/assets/index.js")
                assert asset.status_code == 200
                assert asset.content == b"export const asset = 'unmodified';\\n"
                """,
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_saved_base_path_keeps_agent_calls_aligned_until_restart(tmp_path):
    env = {
        **os.environ,
        "QWENPAW_BASE_PATH": "/current",
        "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        "QWENPAW_AUTH_ENABLED": "false",
        "QWENPAW_TELEMETRY_DISABLED": "1",
    }
    script = textwrap.dedent(
        """
        import os
        import sys
        from urllib.parse import urlsplit

        from fastapi.testclient import TestClient
        from qwenpaw.app._app import app
        from qwenpaw.agents.tools.agent_management import resolve_agent_api_endpoint
        from qwenpaw.browser.control_link.chrome.ws_handler import resolve_default_ws_url

        client = TestClient(app)
        active, inactive = sys.argv[1:]
        if active == '/current':
            response = client.patch(
                '/current/api/envs', json={'QWENPAW_BASE_PATH': '/next'},
            )
            assert response.status_code == 200, response.text
            assert {'key': 'QWENPAW_BASE_PATH', 'value': '/next'} in response.json()

        assert os.environ['QWENPAW_BASE_PATH'] == active
        agent_api = urlsplit(resolve_agent_api_endpoint()).path
        assert agent_api == f'{active}/api', agent_api
        assert client.get(f'{agent_api}/version').status_code == 200
        assert client.get(f'{inactive}/api/version').status_code == 404
        bridge_path = urlsplit(resolve_default_ws_url()).path
        assert bridge_path == f'{active}/api/ws/chrome', bridge_path
        """,
    )
    for active, inactive in [("/current", "/next"), ("/next", "/current")]:
        result = subprocess.run(
            [sys.executable, "-c", script, active, inactive],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
