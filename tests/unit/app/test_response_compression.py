"""Exercise the production middleware stack without starting agents."""

import gzip

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from qwenpaw.app._app import app as production_app
from qwenpaw.app.auth import AuthMiddleware
from qwenpaw.app.response_compression import ResponseCompressionMiddleware


@pytest.fixture
def client(monkeypatch):
    """Reuse the real middleware registration and ordering."""
    monkeypatch.setattr(
        AuthMiddleware,
        f"_should_skip_auth",
        staticmethod(lambda _: True),
    )
    middleware = production_app.user_middleware
    assert any(m.cls is ResponseCompressionMiddleware for m in middleware)
    application = FastAPI(middleware=middleware)

    @application.get(f"/probe/{{kind}}")
    async def probe(kind: str):
        data = f"payload " * 1000
        if kind == f"small":
            return JSONResponse({f"value": f"ok"})
        if kind == f"json":
            return JSONResponse({f"value": data})
        if kind == f"encoded":
            return Response(
                gzip.compress(data.encode()),
                media_type=f"text/plain",
                headers={f"Content-Encoding": f"gzip"},
            )
        if kind == f"attachment":
            return Response(
                data,
                media_type=f"text/plain",
                headers={f"Content-Disposition": f"attachment"},
            )
        if kind == f"partial":
            return Response(data, status_code=206, media_type=f"text/plain")
        if kind == f"text":
            return Response(data, media_type=f"text/plain")

        async def chunks():
            yield data.encode()
            yield b"end"

        media_types = {
            f"sse": f"text/event-stream",
            f"stream": f"text/plain",
            f"json_stream": f"application/json",
            f"zip": f"application/zip",
            f"video": f"video/mp4",
        }
        return StreamingResponse(chunks(), media_type=media_types[kind])

    return TestClient(application)


@pytest.mark.parametrize(f"kind", [f"json", f"text"])
def test_large_response_is_compressed(client, kind):
    response = client.get(f"/probe/{kind}")
    assert response.headers[f"content-encoding"] == f"gzip"
    assert f"Accept-Encoding" in response.headers[f"vary"]
    assert int(response.headers[f"content-length"]) < 1000
    assert f"payload " * 1000 in response.text


@pytest.mark.parametrize(
    f"kind",
    [
        f"small",
        f"sse",
        f"stream",
        f"json_stream",
        f"zip",
        f"video",
        f"attachment",
        f"partial",
    ],
)
def test_excluded_response_is_not_compressed(client, kind):
    response = client.get(f"/probe/{kind}")
    assert f"content-encoding" not in response.headers
    assert response.content


@pytest.mark.parametrize(f"encoding", [f"identity", f"gzip;q=0"])
def test_client_can_decline_gzip(client, encoding):
    response = client.get(
        f"/probe/json",
        headers={f"Accept-Encoding": encoding},
    )
    assert f"content-encoding" not in response.headers
    assert f"Accept-Encoding" in response.headers[f"vary"]
    assert response.json()[f"value"] == f"payload " * 1000


def test_encoded_response_is_not_compressed_twice(client):
    response = client.get(f"/probe/encoded")
    assert response.text == f"payload " * 1000


@pytest.mark.asyncio
async def test_stream_chunks_are_forwarded_before_producer_continues():
    """Check delivery timing rather than a buffered TestClient result."""
    delivered = []

    async def send(message):
        delivered.append(message)

    async def receive():
        return {f"type": f"http.disconnect"}

    async def streaming_app(scope, receive, send):
        await send(
            {
                f"type": f"http.response.start",
                f"status": 200,
                f"headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {
                f"type": f"http.response.body",
                f"body": b"first",
                f"more_body": True,
            }
        )
        assert delivered[-1][f"body"] == b"first"
        await send({f"type": f"http.response.body", f"body": b"last"})

    middleware = ResponseCompressionMiddleware(streaming_app)
    await middleware(
        {f"type": f"http", f"headers": [(b"accept-encoding", b"gzip")]},
        receive,
        send,
    )
    assert delivered[-1][f"body"] == b"last"
