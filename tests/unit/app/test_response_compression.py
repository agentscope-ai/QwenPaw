# -*- coding: utf-8 -*-
"""Exercise the production middleware stack without starting agents."""

import gzip

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from qwenpaw.app._app import app as production_app
from qwenpaw.app.auth import AuthMiddleware
from qwenpaw.app.response_compression import ResponseCompressionMiddleware


@pytest.fixture(name="client")
def compression_client(monkeypatch):
    """Reuse the real middleware registration and ordering."""
    monkeypatch.setattr(
        AuthMiddleware,
        "_should_skip_auth",
        staticmethod(lambda _: True),
    )
    middleware = production_app.user_middleware
    assert any(m.cls is ResponseCompressionMiddleware for m in middleware)
    application = FastAPI(middleware=middleware)

    @application.get("/probe/{kind}")
    async def probe(kind: str):
        data = "payload " * 1000
        if kind in {"small", "json"}:
            return JSONResponse({"value": "ok" if kind == "small" else data})
        if kind == "encoded":
            return Response(
                gzip.compress(data.encode()),
                media_type="text/plain",
                headers={"Content-Encoding": "gzip"},
            )
        if kind == "attachment":
            return Response(
                data,
                media_type="text/plain",
                headers={"Content-Disposition": "attachment"},
            )
        if kind == "partial":
            return Response(data, status_code=206, media_type="text/plain")
        if kind == "text":
            return Response(data, media_type="text/plain")

        async def chunks():
            yield data.encode()
            yield b"end"

        media_types = {
            "sse": "text/event-stream",
            "stream": "text/plain",
            "json_stream": "application/json",
            "zip": "application/zip",
            "video": "video/mp4",
        }
        return StreamingResponse(chunks(), media_type=media_types[kind])

    return TestClient(application)


@pytest.mark.parametrize("kind", ["json", "text"])
def test_large_response_is_compressed(client, kind):
    response = client.get(f"/probe/{kind}")
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert int(response.headers["content-length"]) < 1000
    assert "payload " * 1000 in response.text


@pytest.mark.parametrize(
    "kind",
    [
        "small",
        "sse",
        "stream",
        "json_stream",
        "zip",
        "video",
        "attachment",
        "partial",
    ],
)
def test_excluded_response_is_not_compressed(client, kind):
    response = client.get(f"/probe/{kind}")
    assert "content-encoding" not in response.headers
    assert response.content


@pytest.mark.parametrize("encoding", ["identity", "gzip;q=0"])
def test_client_can_decline_gzip(client, encoding):
    response = client.get(
        "/probe/json",
        headers={"Accept-Encoding": encoding},
    )
    assert "content-encoding" not in response.headers
    assert "Accept-Encoding" in response.headers["vary"]
    assert response.json()["value"] == "payload " * 1000


def test_encoded_response_is_not_compressed_twice(client):
    response = client.get("/probe/encoded")
    assert response.text == "payload " * 1000


@pytest.mark.parametrize(
    "encodings, compressed",
    [
        (["*;q=1, identity;q=0"], True),
        (["br", "gzip"], True),
        (["br", "*;q=0.5"], True),
        (["*;q=1", "gzip;q=0"], False),
        (["gzip;q=0", "*;q=1"], False),
        (["*;q=0", "gzip;q=0.5"], True),
        (["gzip;q=0.5", "*;q=0"], True),
        (["*;q=0"], False),
        (["gzip;q=invalid", "*;q=1"], False),
        (["br", "GZIP;Q=0.5"], True),
    ],
)
def test_accept_encoding_negotiation(client, encodings, compressed):
    response = client.get(
        "/probe/json",
        headers=[("Accept-Encoding", value) for value in encodings],
    )
    assert response.headers.get("content-encoding") == (
        "gzip" if compressed else None
    )
    assert "Accept-Encoding" in response.headers["vary"]
    assert response.json()["value"] == "payload " * 1000


@pytest.mark.asyncio
async def test_stream_chunks_are_forwarded_before_producer_continues():
    """Check delivery timing rather than a buffered TestClient result."""
    delivered = []

    async def send(message):
        delivered.append(message)

    async def receive():
        return {"type": "http.disconnect"}

    async def streaming_app(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            },
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"first",
                "more_body": True,
            },
        )
        assert delivered[-1]["body"] == b"first"
        await send({"type": "http.response.body", "body": b"last"})

    middleware = ResponseCompressionMiddleware(streaming_app)
    await middleware(
        {"type": "http", "headers": [(b"accept-encoding", b"gzip")]},
        receive,
        send,
    )
    assert delivered[-1]["body"] == b"last"
