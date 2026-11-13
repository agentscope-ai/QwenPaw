# -*- coding: utf-8 -*-
"""Runtime base-path mounting keeps application routes prefix-aware."""
from __future__ import annotations

import json
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        (" / ", ""),
        ("/app/qwenpaw/web/", "/app/qwenpaw/web"),
    ],
)
def test_normalize_base_path(value, expected):
    assert normalize_base_path(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "app/qwenpaw",
        "/app//qwenpaw",
        "/app/../admin",
        "/app/%2e%2e/admin",
        "/app%2fadmin",
        "/app?x=1",
        "/app#x",
    ],
)
def test_normalize_base_path_rejects_ambiguous_paths(value):
    with pytest.raises(ValueError):
        normalize_base_path(value)


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


def test_console_index_injects_only_base_path_tokens(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(
        '<html><head><base href="/" />'
        '<script>window.__qpBase = "";</script>'
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
            "window.__qpBase = "
            + json.dumps(
                "/app/qwenpaw/web",
            )
            in response.text
        )
        assert '<script src="./assets/index.js"></script>' in response.text
        assert "__QWENPAW_BASE_HREF__" not in response.text
        assert "__QWENPAW_BASE_PATH_JSON__" not in response.text
        assert response.headers["content-length"] == str(len(response.content))


def test_console_index_escapes_html_attributes_and_inline_script(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(
        '<base href="/" /><script>window.__qpBase = "";</script>',
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
        assert "&quot;&gt;&lt;script&gt;" in response.text
        assert "\\u003cscript\\u003e" in response.text
        assert "\\u003c/script\\u003e" in response.text
        assert '"><script>alert(1)</script>' not in response.text
        assert response.text.count("<script>") == 1
        assert response.text.count("</script>") == 1


def test_production_app_serves_api_console_and_assets_below_base_path(
    tmp_path,
):
    console = tmp_path / "console"
    assets = console / "assets"
    assets.mkdir(parents=True)
    (console / "index.html").write_text(
        '<base href="/" />'
        '<script>window.__qpBase = "";</script>'
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
                for path in ("/app/qwenpaw/web/", "/app/qwenpaw/web/chat", "/app/qwenpaw/web/chat/"):
                    page = client.get(path)
                    assert page.status_code == 200, path
                    assert '<base href="/app/qwenpaw/web/">' in page.text
                    assert 'window.__qpBase = "/app/qwenpaw/web"' in page.text
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
