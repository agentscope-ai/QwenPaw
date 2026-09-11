# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,too-many-statements,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
from hashlib import sha256

import httpx
from fastapi import FastAPI
import pytest

from api import file_asset_routes, file_media_routes
from api.dependencies import creator_error_handler, project_file_services
from api.file_asset_routes import (
    _assert_supported_source_upload,
    _media_kind,
    _validate_public_remote_url,
    router,
)
from api.file_media_routes import router as media_router
from domain.errors import CreatorError, ValidationError
from services.media_files.keyframe_cache import CachedKeyframe
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files import safe_remote_download


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.yield_count = 0

    def __iter__(self):
        for chunk in self._chunks:
            self.yield_count += 1
            yield chunk


def test_media_kind_classifies_readable_documents_by_extension() -> None:
    # Documents classify by extension even under legacy MIME types; AV
    # prefixes win for raster media, SVG routes to the document reader.
    expectations = {
        ("application/pdf", "script.pdf"): "document",
        ("text/csv", "budget.csv"): "document",
        ("application/vnd.ms-powerpoint", "deck.ppt"): "document",
        ("video/mp4", "clip.mp4"): "video",
        ("image/png", "frame.png"): "image",
        ("image/svg+xml", "icon.svg"): "document",
        ("application/octet-stream", "logo.svg"): "document",
        ("text/x-unknown", "blob.unknownext"): "text",
        ("application/zip", "bundle.zip"): "other",
    }
    for (media_type, name), expected in expectations.items():
        assert _media_kind(media_type, name) == expected, name


def test_source_upload_rejects_unreadable_binary_formats() -> None:
    # Opaque blobs without a renderer cannot enter Source Intelligence
    # and must be refused at the upload boundary with a readable hint.
    with pytest.raises(ValidationError) as excinfo:
        _assert_supported_source_upload(
            "unsupported.exe",
            "application/octet-stream",
        )
    assert "不支持的来源素材格式" in str(excinfo.value)
    assert "unsupported.exe" in str(excinfo.value)
    # Readable creative material passes untouched. 3D models are
    # renderable documents since the model3d renderer landed.
    _assert_supported_source_upload("script.pdf", "application/pdf")
    _assert_supported_source_upload("budget.csv", "text/csv")
    _assert_supported_source_upload("clip.mp4", "video/mp4")
    _assert_supported_source_upload("prop.glb", "model/gltf-binary")


def _install_remote_transport(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chunks: list[bytes],
    headers: dict[str, str] | None = None,
) -> list[_ChunkStream]:
    streams: list[_ChunkStream] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        stream = _ChunkStream(chunks)
        streams.append(stream)
        return httpx.Response(
            200,
            headers=headers or {"content-type": "video/mp4"},
            stream=stream,
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(safe_remote_download.httpx, "Client", client_factory)
    monkeypatch.setattr(
        safe_remote_download,
        "validate_public_remote_url",
        lambda value: value,
    )
    monkeypatch.setattr(
        file_asset_routes,
        "_validate_public_remote_url",
        lambda value: value,
    )
    monkeypatch.setattr(
        safe_remote_download,
        "validate_response_peer",
        lambda _response: None,
    )
    return streams


def _app(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(Project.new(project_id="project-1", name="One"))
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.include_router(media_router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services


def test_text_asset_is_published_indexed_attached_and_replayed(
    tmp_path,
    run_scenario,
) -> None:
    app, services = _app(tmp_path)
    payload = {
        "clientRequestId": "asset-1",
        "kind": "text",
        "name": "brief.txt",
        "value": "hello creator",
        "postIngestAction": "ATTACH_SOURCE",
    }

    async def scenario(client):
        headers = {"Idempotency-Key": "asset-1"}
        first = await client.post(
            "/projects/project-1/assets",
            headers=headers,
            json=payload,
        )
        replay = await client.post(
            "/projects/project-1/assets",
            headers=headers,
            json=payload,
        )
        content = await client.get(
            f"/projects/project-1/assets/{first.json()['assetId']}/content",
            params={"versionId": first.json()["assetVersionId"]},
        )
        media = await client.get(
            f"/media/assets/{first.json()['assetVersionId']}",
        )
        return first, replay, content, media

    first, replay, content, media = run_scenario(app, scenario)
    assert first.status_code == 202
    assert first.json()["status"] == "SUCCEEDED"
    assert replay.status_code == 202
    assert replay.json()["assetVersionId"] == first.json()["assetVersionId"]
    assert replay.json()["result"]["idempotentReplay"] is True
    assert content.status_code == 200
    assert content.content == b"hello creator"
    assert media.status_code == 200
    assert media.content == b"hello creator"

    project = services.projects.read("project-1").project
    assert len(project.assets.files_by_id) == 1
    assert len(project.assets.source_versions_by_id) == 1
    assert len(project.sources.sources.items) == 1
    assert project.generation == 1


def test_indexed_media_supports_byte_ranges_and_utf8_filenames(
    tmp_path,
    run_scenario,
) -> None:
    app, _services = _app(tmp_path)
    payload = {
        "clientRequestId": "asset-range-1",
        "kind": "text",
        "name": "猫咪成片.mp4",
        "value": "0123456789",
        "postIngestAction": "ATTACH_SOURCE",
    }

    async def scenario(client):
        created = await client.post(
            "/projects/project-1/assets",
            headers={"Idempotency-Key": "asset-range-1"},
            json=payload,
        )
        version_id = created.json()["assetVersionId"]
        ranged = await client.get(
            f"/media/assets/{version_id}",
            headers={"Range": "bytes=2-5"},
        )
        invalid = await client.get(
            f"/media/assets/{version_id}",
            headers={"Range": "bytes=99-100"},
        )
        return ranged, invalid

    ranged, invalid = run_scenario(app, scenario)
    assert ranged.status_code == 206
    assert ranged.content == b"2345"
    assert ranged.headers["accept-ranges"] == "bytes"
    assert ranged.headers["content-range"] == "bytes 2-5/10"
    disposition = ranged.headers["content-disposition"]
    assert disposition.startswith('inline; filename="media.mp4"; ')
    assert (
        "filename*=UTF-8''%E7%8C%AB%E5%92%AA%E6%88%90%E7%89%87.mp4"
        in disposition
    )
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == "bytes */10"


def test_remote_asset_streams_to_file_and_project_json_only_indexes_it(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    run_scenario,
) -> None:
    app, services = _app(tmp_path)
    chunks = [b"REMOTE_VIDEO_PAYLOAD_", b"STREAMED_WITHOUT_BODY_AGGREGATION"]
    payload = b"".join(chunks)
    monkeypatch.setenv("CREATOR_REMOTE_ASSET_MAX_BYTES", str(len(payload) + 1))
    streams = _install_remote_transport(
        monkeypatch,
        chunks=chunks,
        headers={
            "content-type": "video/mp4",
            "content-length": str(len(payload)),
        },
    )
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"LOCAL_KEYFRAME")
    observed_frame_source: dict[str, object] = {}
    monkeypatch.setattr(
        file_media_routes,
        "ffmpeg_readiness",
        lambda: {"status": "ok", "path": "/fake/ffmpeg"},
    )

    def fake_materialize_keyframe(project_root, **kwargs):
        observed_frame_source.update(kwargs)
        assert project_root == services.projects.project_root("project-1")
        return CachedKeyframe(
            path=frame_path,
            sha256=sha256(frame_path.read_bytes()).hexdigest(),
            size_bytes=frame_path.stat().st_size,
            timestamp_seconds=float(kwargs["timestamp_seconds"]),
            width=int(kwargs["width"]),
        )

    monkeypatch.setattr(
        file_media_routes,
        "materialize_keyframe",
        fake_materialize_keyframe,
    )
    request_payload = {
        "clientRequestId": "remote-asset-1",
        "kind": "url",
        "name": "远程–视频.mp4",
        "value": "https://assets.example/source.mp4",
        "postIngestAction": "ATTACH_SOURCE",
    }

    async def scenario(client):
        headers = {"Idempotency-Key": "remote-asset-1"}
        first = await client.post(
            "/projects/project-1/assets",
            headers=headers,
            json=request_payload,
        )
        assert first.json()["status"] in {"QUEUED", "RUNNING"}
        await asyncio.gather(
            *list(file_asset_routes._REMOTE_INGEST_TASKS.values()),
        )
        replay = await client.post(
            "/projects/project-1/assets",
            headers=headers,
            json=request_payload,
        )
        cached = await client.get(
            f"/media/assets/{first.json()['assetVersionId']}",
        )
        direct = await client.get(
            f"/projects/project-1/assets/{first.json()['assetId']}/content",
            params={"versionId": first.json()["assetVersionId"]},
        )
        keyframe = await client.get(
            f"/media/assets/{first.json()['assetVersionId']}/frame",
            params={"timestamp": 4.5, "width": 640},
        )
        return first, replay, cached, direct, keyframe

    first, replay, cached, direct, keyframe = run_scenario(app, scenario)
    assert first.status_code == 202
    assert replay.status_code == 202
    assert first.json()["assetVersionId"].startswith("asset-version-")
    assert replay.json()["assetVersionId"] == first.json()["assetVersionId"]
    assert replay.json()["result"]["idempotentReplay"] is False
    assert cached.status_code == 200
    assert cached.content == payload
    assert direct.status_code == 200
    assert direct.content == payload
    assert keyframe.status_code == 200
    assert keyframe.content == b"LOCAL_KEYFRAME"
    assert keyframe.headers["x-creator-media-source"] == "local-keyframe-cache"
    assert observed_frame_source["timestamp_seconds"] == 4.5
    assert len(streams) == 1
    assert all(stream.yield_count == len(chunks) for stream in streams)

    snapshot = services.projects.read("project-1")
    assert snapshot.project.generation == 1
    assert snapshot.project.assets.files_by_id == {}
    version = snapshot.project.assets.source_versions_by_id[
        first.json()["assetVersionId"]
    ]
    assert version.file_id is None
    assert version.metadata["publicSourceUrl"] == request_payload["value"]
    project_root = services.projects.project_root("project-1")
    cache_item = replay.json()["result"]["items"][0]
    assert cache_item["cacheChecksum"] == sha256(payload).hexdigest()
    assert payload not in (project_root / "project.json").read_bytes()
    assert list((project_root / "assets" / ".staging").iterdir()) == []


def test_remote_asset_stream_limit_cleans_partial_staging(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app_instance, services = _app(tmp_path)
    monkeypatch.setenv("CREATOR_REMOTE_ASSET_MAX_BYTES", "5")
    _install_remote_transport(monkeypatch, chunks=[b"123", b"456"])
    file_store = file_asset_routes.AssetFileStore(
        services.projects.project_root("project-1"),
    )

    with pytest.raises(ValidationError, match="超过 5 bytes 限制"):
        file_asset_routes._download_remote_to_staging(
            "https://assets.example/too-large.mp4",
            file_store=file_store,
            staging_id="limit-test",
        )

    assert list(file_store.staging_root.iterdir()) == []


def test_local_video_route_enforces_its_own_limit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    api_request,
) -> None:
    app, services = _app(tmp_path)
    monkeypatch.setattr(file_asset_routes, "_MAX_LOCAL_VIDEO_UPLOAD_BYTES", 5)
    monkeypatch.setenv("CREATOR_REMOTE_ASSET_MAX_BYTES", "1000")

    response = api_request(
        app,
        "POST",
        "/projects/project-1/assets",
        headers={"Idempotency-Key": "local-video-too-large"},
        data={"clientRequestId": "local-video-too-large"},
        files={"file": ("source.mp4", b"123456", "video/mp4")},
    )
    assert response.status_code == 422
    assert "Local video upload exceeds 2 GiB" in response.text
    project = services.projects.read("project-1").project
    assert project.generation == 0
    assert project.assets.files_by_id == {}


def test_folder_import_commits_all_files_in_one_generation(
    tmp_path,
    run_scenario,
) -> None:
    app, services = _app(tmp_path)

    async def scenario(client):
        accepted = await client.post(
            "/projects/project-1/asset-imports",
            headers={"Idempotency-Key": "import-1"},
            data={
                "clientRequestId": "import-1",
                "postIngestAction": "ATTACH_SOURCE",
            },
            files=[
                ("files", ("a.txt", b"A", "text/plain")),
                ("files", ("b.txt", b"B", "text/plain")),
            ],
        )
        loaded = await client.get(
            f"/projects/project-1/asset-imports/{accepted.json()['importId']}",
        )
        return accepted, loaded

    accepted, loaded = run_scenario(app, scenario)
    assert accepted.status_code == 202
    assert loaded.status_code == 200
    assert loaded.json()["status"] == "SUCCEEDED"
    assert [item["name"] for item in loaded.json()["items"]] == [
        "a.txt",
        "b.txt",
    ]
    project = services.projects.read("project-1").project
    assert project.generation == 1
    assert len(project.assets.source_versions_by_id) == 2
    assert len(project.sources.sources.items) == 2


def test_remote_asset_url_validation_fails_closed_on_ssrf_vectors() -> None:
    # Literal and DNS-resolved private addresses, plus embedded credentials,
    # are refused; only clean public HTTP(S) URLs pass (fragment stripped).
    with pytest.raises(ValidationError, match="私有或保留网络"):
        _validate_public_remote_url("http://127.0.0.1/private")

    def private_resolver(*_args, **_kwargs):
        return [(2, 1, 6, "", ("10.0.0.8", 80))]

    with pytest.raises(ValidationError, match="私有或保留网络"):
        _validate_public_remote_url(
            "https://assets.example/video.mp4",
            resolver=private_resolver,
        )

    def public_resolver(*_args, **_kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    with pytest.raises(ValidationError, match="用户名或密码"):
        _validate_public_remote_url(
            "https://user:secret@assets.example/video.mp4",
            resolver=public_resolver,
        )
    assert (
        _validate_public_remote_url(
            "https://assets.example/video.mp4?version=1#ignored",
            resolver=public_resolver,
        )
        == "https://assets.example/video.mp4?version=1"
    )
