# -*- coding: utf-8 -*-
"""File delivery must preserve the identity of local filesystem paths."""
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.agents.tools.send_file import send_file_to_user
from qwenpaw.app.channels.utils import file_url_to_local_path
from qwenpaw.app.routers import files


@pytest.fixture(name="preview_app")
def fixture_preview_app(tmp_path, monkeypatch):
    """Use the real router with a temporary permitted workspace."""
    monkeypatch.setattr(files, "_ALLOWED_ROOT", tmp_path.resolve())
    monkeypatch.setattr(
        files,
        "_is_preview_outside_workspace_allowed",
        lambda: False,
    )
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    return app


@pytest.mark.parametrize(
    "name",
    [
        "plain.txt",
        "hello world.txt",
        "中文.txt",
        "literal%20name.txt",
        "literal%23name.txt",
        "only%25file.txt",
        "report#1.txt",
    ],
)
@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.asyncio
async def test_send_and_preview_exact_file(
    name,
    relative,
    tmp_path,
    monkeypatch,
    preview_app,
):
    """The sent URI and HTTP preview must select the requested bytes."""
    target = tmp_path / name
    target.write_text("REQUESTED_FILE", encoding="utf-8")
    sibling = tmp_path / unquote(name)
    if sibling != target and not name.startswith("only"):
        sibling.write_text("WRONG_SIBLING", encoding="utf-8")
    monkeypatch.setattr(
        "qwenpaw.agents.tools.file_io._effective_project_roots",
        lambda: [tmp_path],
    )
    result = await send_file_to_user(name if relative else str(target))
    data = [block for block in result.content if block.type == "data"]
    assert len(data) == 1, result
    assert data[0].name == name
    uri = str(data[0].source.url)
    assert (
        Path(file_url_to_local_path(uri)).read_text(encoding="utf-8")
        == "REQUESTED_FILE"
    )
    async with AsyncClient(
        transport=ASGITransport(app=preview_app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/files/preview/" + uri[7:])
    assert response.status_code == 200
    assert response.text == "REQUESTED_FILE"


@pytest.mark.parametrize("name", ["literal%20name.txt", "only%25file.txt"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.asyncio
async def test_preview_decodes_transport_path_once(
    name,
    method,
    tmp_path,
    preview_app,
):
    """A correctly encoded URI must not be decoded into a sibling file."""
    target = tmp_path / name
    target.write_text("REQUESTED_FILE", encoding="utf-8")
    if not name.startswith("only"):
        (tmp_path / unquote(name)).write_text("WRONG", encoding="utf-8")
    async with AsyncClient(
        transport=ASGITransport(app=preview_app),
        base_url="http://test",
    ) as client:
        response = await client.request(
            method,
            "/api/files/preview/" + target.as_uri()[7:],
        )
    assert response.status_code == 200
    assert int(response.headers["content-length"]) == len("REQUESTED_FILE")
    if method == "GET":
        assert response.text == "REQUESTED_FILE"


@pytest.mark.asyncio
async def test_preview_still_blocks_outside_workspace(
    tmp_path,
    preview_app,
):
    """Decoding changes must retain the existing workspace boundary."""
    outside = tmp_path.parent / "outside.txt"
    async with AsyncClient(
        transport=ASGITransport(app=preview_app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/files/preview/" + outside.as_uri()[7:],
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "OUTSIDE_WORKSPACE"
