# -*- coding: utf-8 -*-
"""Verify when the serving process publishes its endpoint."""

import json
from types import SimpleNamespace

import pytest
import uvicorn

from qwenpaw.app import base_path
from qwenpaw.app.api_server import ApiServer
from qwenpaw.config import utils


@pytest.fixture
def record_file(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(utils, "get_config_path", lambda: path)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.setattr(utils, "_runtime_last_api", None)
    monkeypatch.setattr(base_path, "_server_base_path", None)
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mount", "configured_port", "bound_port", "prebound"),
    [("/serving/api/", 8765, 8765, False), ("/", 0, 8766, True)],
)
async def test_publish_mount_from_successful_startup(
    monkeypatch,
    record_file,
    mount,
    configured_port,
    bound_port,
    prebound,
):
    monkeypatch.setenv("QWENPAW_BASE_PATH", mount)
    base_path.initialize_server_base_path()
    monkeypatch.setenv("QWENPAW_BASE_PATH", "/edited")

    async def start(server, sockets):
        assert not record_file.exists()
        assert utils.read_last_api() == ("127.0.0.1", bound_port)
        server.started = True

    monkeypatch.setattr(uvicorn.Server, "startup", start)
    server = ApiServer(
        uvicorn.Config("unused:app", host="0.0.0.0", port=configured_port),
    )
    sock = SimpleNamespace(getsockname=lambda: ("0.0.0.0", bound_port))
    await server.startup(sockets=[sock] if prebound else None)

    record = json.loads(record_file.read_text(encoding="utf-8"))["last_api"]
    assert record == {
        "host": "127.0.0.1",
        "port": bound_port,
        "base_path": mount.rstrip("/"),
    }


@pytest.mark.asyncio
async def test_failed_startup_does_not_overwrite_last_endpoint(
    monkeypatch,
    record_file,
):
    utils.write_last_api("127.0.0.1", 8765, "/previous")
    before = record_file.read_bytes()
    monkeypatch.setenv("QWENPAW_BASE_PATH", "/failed")
    base_path.initialize_server_base_path()

    async def fail(_server, sockets):
        raise SystemExit(3)

    monkeypatch.setattr(uvicorn.Server, "startup", fail)
    server = ApiServer(uvicorn.Config("unused:app", port=8766))

    with pytest.raises(SystemExit):
        await server.startup()

    assert record_file.read_bytes() == before
