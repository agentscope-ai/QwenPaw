# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image

from models import media_transport
from models.media_transport import (
    SEEDANCE_REFERENCE_IMAGE_MAX_BYTES,
    _upload_local_file_to_dashscope_temp_sync,
    _upload_reference_bytes_to_dashscope_temp_sync,
    read_reference_media,
    reference_media_data_url,
    validate_reference_image_bytes,
)


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color="blue").save(output, format="PNG")
    return output.getvalue()


def test_reference_image_dimensions_are_read_before_verify(
    monkeypatch,
) -> None:
    class VerifyInvalidatesImage:
        verified = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @property
        def size(self):
            if self.verified:
                raise AssertionError("image attributes accessed after verify")
            return (8, 8)

        def verify(self):
            self.verified = True

    monkeypatch.setattr(
        "models.media_transport.Image.open",
        lambda _stream: VerifyInvalidatesImage(),
    )

    validate_reference_image_bytes(b"fake image bytes")


def test_dashscope_temporary_upload_streams_file_handle_instead_of_loading_bytes(
    tmp_path,
    monkeypatch,
) -> None:
    video = tmp_path / "large-local-video.mp4"
    with video.open("wb") as stream:
        stream.seek(64 * 1024 * 1024 - 1)
        stream.write(b"\0")
    observed = {}

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs):
            observed["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, *, params, headers):
            observed["policy_request"] = (url, params, headers)
            return FakeResponse(
                {
                    "data": {
                        "max_file_size_mb": 1024,
                        "upload_dir": "dashscope-instant/account/date/id",
                        "upload_host": "https://upload.example.test",
                        "oss_access_key_id": "temporary-access",
                        "signature": "temporary-signature",
                        "policy": "temporary-policy",
                        "x_oss_object_acl": "private",
                        "x_oss_forbid_overwrite": "true",
                    },
                },
            )

        def post(self, url, *, data, files):
            filename, file_handle, media_type = files["file"]
            observed["upload"] = {
                "url": url,
                "data": dict(data),
                "filename": filename,
                "media_type": media_type,
                "is_bytes": isinstance(file_handle, (bytes, bytearray)),
                "first_byte": file_handle.read(1),
            }
            return FakeResponse()

    monkeypatch.setattr("models.media_transport.httpx.Client", FakeClient)

    url = _upload_local_file_to_dashscope_temp_sync(
        video,
        api_key="test-api-key",
        model_name="qwen3.7-plus",
        media_type="video/mp4",
    )

    assert url.startswith("oss://dashscope-instant/account/date/id/")
    assert observed["upload"]["is_bytes"] is False
    assert observed["upload"]["first_byte"] == b"\0"
    assert observed["upload"]["filename"].endswith(".mp4")
    assert observed["upload"]["media_type"] == "video/mp4"
    assert observed["upload"]["data"]["success_action_status"] == "200"


def test_dashscope_temporary_upload_accepts_in_memory_reference_bytes(
    monkeypatch,
) -> None:
    observed = {}

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, *, params, headers):
            observed["policy_request"] = (url, params, headers)
            return FakeResponse(
                {
                    "data": {
                        "max_file_size_mb": 1024,
                        "upload_dir": "dashscope-instant/account/date/id",
                        "upload_host": "https://upload.example.test",
                        "oss_access_key_id": "temporary-access",
                        "signature": "temporary-signature",
                        "policy": "temporary-policy",
                    },
                },
            )

        def post(self, url, *, data, files):
            del data
            filename, file_source, media_type = files["file"]
            observed["upload"] = {
                "url": url,
                "filename": filename,
                "media_type": media_type,
                "content": file_source,
            }
            return FakeResponse()

    monkeypatch.setattr("models.media_transport.httpx.Client", FakeClient)

    content = _png_bytes()
    url = _upload_reference_bytes_to_dashscope_temp_sync(
        content,
        "scene-1 reference.png",
        api_key="test-api-key",
        model_name="wan2.7-r2v",
    )

    assert url.startswith("oss://dashscope-instant/account/date/id/")
    assert observed["policy_request"][1] == {
        "action": "getPolicy",
        "model": "wan2.7-r2v",
    }
    assert observed["upload"]["content"] == content
    assert observed["upload"]["filename"].endswith(".png")
    assert observed["upload"]["media_type"] == "image/png"


def test_reference_media_data_url_inlines_png_for_seedance() -> None:
    content = _png_bytes()

    data_url = reference_media_data_url(content, "reference.png")

    prefix = "data:image/png;base64,"
    assert data_url.startswith(prefix)
    assert base64.b64decode(data_url[len(prefix) :]) == content


def test_reference_media_data_url_guesses_media_type_from_magic() -> None:
    content = _png_bytes()

    data_url = reference_media_data_url(content, "reference")

    assert data_url.startswith("data:image/png;base64,")


def test_reference_media_data_url_rejects_oversized_media() -> None:
    oversized = b"\0" * SEEDANCE_REFERENCE_IMAGE_MAX_BYTES

    with pytest.raises(RuntimeError, match="30MB"):
        reference_media_data_url(oversized, "reference.png")


def test_reference_media_uses_bounded_safe_remote_download(
    monkeypatch,
) -> None:
    observed = {}

    def download(url, *, max_bytes, timeout):
        observed.update(url=url, max_bytes=max_bytes, timeout=timeout)
        return _png_bytes()

    monkeypatch.setattr("models.media_transport.safe_download_bytes", download)

    content, filename = asyncio.run(
        read_reference_media(
            "https://public.example/reference.png",
            max_bytes=1234,
        ),
    )

    assert content == _png_bytes()
    assert filename == "reference.png"
    assert observed == {
        "url": "https://public.example/reference.png",
        "max_bytes": 1234,
        "timeout": 60.0,
    }


def test_reference_media_checks_local_size_before_reading(tmp_path) -> None:
    reference = tmp_path / "too-large.png"
    reference.write_bytes(b"123456")

    with pytest.raises(ValueError, match="exceeds 5 bytes"):
        asyncio.run(read_reference_media(reference.as_uri(), max_bytes=5))


@pytest.mark.parametrize(
    ("values", "expected_status"),
    [
        (("", "", ""), "absent"),
        (("id", "secret", "https://oss.example.test"), "ready"),
        (("id", "", ""), "invalid"),
    ],
)
def test_creator_oss_readiness_has_explicit_three_states(
    monkeypatch,
    values,
    expected_status,
) -> None:
    access_id, access_secret, endpoint = values
    monkeypatch.setattr(
        media_transport.model_config,
        "get_oss_access_key_id",
        lambda: access_id,
    )
    monkeypatch.setattr(
        media_transport.model_config,
        "get_oss_access_key_secret",
        lambda: access_secret,
    )
    monkeypatch.setattr(
        media_transport.model_config,
        "get_oss_endpoint",
        lambda: endpoint,
    )
    monkeypatch.setattr(
        media_transport.model_config,
        "get_oss_bucket",
        lambda default: default,
    )
    monkeypatch.setattr(
        media_transport.model_config,
        "get_oss_public_base_url",
        lambda: "",
    )

    readiness = media_transport.creator_oss_readiness()

    assert readiness["status"] == expected_status


def test_uguu_upload_retries_429_and_parses_temporary_url(monkeypatch) -> None:
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={"files": [{"url": "https://uguu.se/example.png"}]},
        )

    async def no_sleep(_seconds):
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        media_transport.httpx,
        "AsyncClient",
        lambda **kwargs: client,
    )
    monkeypatch.setattr(media_transport.asyncio, "sleep", no_sleep)

    url = asyncio.run(
        media_transport.upload_image_to_uguu_for_temporary_public_url(
            _png_bytes(),
            "reference.png",
        ),
    )

    assert url == "https://uguu.se/example.png"
    assert len(calls) == 2
    assert b'name="files[]"' in calls[-1].content
