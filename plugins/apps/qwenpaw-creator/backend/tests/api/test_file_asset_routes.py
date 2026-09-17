# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,too-many-statements,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from hashlib import sha256

import httpx
from fastapi import FastAPI
import pytest

from api.content_disposition import inline_content_disposition
from api import file_asset_routes, file_media_routes
from api.dependencies import creator_error_handler, project_file_services
from api.file_asset_routes import (
    _assert_supported_source_upload,
    _media_kind,
    _remote_asset_max_bytes,
    _validate_local_video_upload,
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
    # Required first-batch document formats must classify as documents even
    # when the browser reports text/* or legacy Office MIME types.
    assert _media_kind("application/pdf", "script.pdf") == "document"
    assert _media_kind("text/csv", "budget.csv") == "document"
    assert _media_kind("text/plain", "notes.txt") == "document"
    assert _media_kind("application/x-subrip", "dialogue.srt") == "document"
    assert _media_kind("text/vtt", "dialogue.vtt") == "document"
    assert (
        _media_kind("application/vnd.ms-powerpoint", "deck.ppt") == "document"
    )
    assert (
        _media_kind(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet",
            "plan.xlsx",
        )
        == "document"
    )
    # AV prefixes win for raster media, SVG routes to the document reader,
    # and unreadable payloads keep legacy kinds.
    assert _media_kind("video/mp4", "clip.mp4") == "video"
    assert _media_kind("image/png", "frame.png") == "image"
    assert _media_kind("image/svg+xml", "icon.svg") == "document"
    assert _media_kind("application/octet-stream", "logo.svg") == "document"
    assert _media_kind("text/x-unknown", "blob.unknownext") == "text"
    assert _media_kind("application/zip", "bundle.zip") == "other"


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
) -> None:
    app, services = _app(tmp_path)
    payload = {
        "clientRequestId": "asset-1",
        "kind": "text",
        "name": "brief.txt",
        "value": "hello creator",
        "postIngestAction": "ATTACH_SOURCE",
    }

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/projects/project-1/assets",
                headers={"Idempotency-Key": "asset-1"},
                json=payload,
            )
            replay = await client.post(
                "/projects/project-1/assets",
                headers={"Idempotency-Key": "asset-1"},
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

    first, replay, content, media = asyncio.run(scenario())
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


def test_asset_content_supports_utf8_filenames(tmp_path) -> None:
    app, _services = _app(tmp_path)
    payload = {
        "clientRequestId": "asset-utf8-content-1",
        "kind": "text",
        "name": "哈兰德–舞台.txt",
        "value": "unicode filename",
        "postIngestAction": "ATTACH_SOURCE",
    }

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            created = await client.post(
                "/projects/project-1/assets",
                headers={"Idempotency-Key": "asset-utf8-content-1"},
                json=payload,
            )
            content = await client.get(
                f"/projects/project-1/assets/{created.json()['assetId']}/content",
                params={"versionId": created.json()["assetVersionId"]},
            )
        return created, content

    created, content = asyncio.run(scenario())
    assert created.status_code == 202
    assert content.status_code == 200
    assert content.content == b"unicode filename"
    disposition = content.headers["content-disposition"]
    assert disposition.startswith('inline; filename="')
    assert (
        "filename*=UTF-8''%E5%93%88%E5%85%B0%E5%BE%B7%E2%80%93"
        "%E8%88%9E%E5%8F%B0.txt"
    ) in disposition


def test_content_disposition_handles_lone_surrogates_and_ascii_fallback() -> (
    None
):
    disposition = inline_content_disposition("坏文件\ud800.mp4")

    assert disposition.startswith('inline; filename="media.mp4"; ')
    assert "filename*=UTF-8''%E5%9D%8F%E6%96%87%E4%BB%B6%3F.mp4" in disposition
    disposition.encode("latin-1")


def test_indexed_media_supports_byte_ranges_and_utf8_filenames(
    tmp_path,
) -> None:
    app, _services = _app(tmp_path)
    payload = {
        "clientRequestId": "asset-range-1",
        "kind": "text",
        "name": "猫咪成片.mp4",
        "value": "0123456789",
        "postIngestAction": "ATTACH_SOURCE",
    }

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
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

    ranged, invalid = asyncio.run(scenario())
    assert ranged.status_code == 206
    assert ranged.content == b"2345"
    assert ranged.headers["accept-ranges"] == "bytes"
    assert ranged.headers["content-range"] == "bytes 2-5/10"
    assert ranged.headers["content-length"] == "4"
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
) -> None:
    app, services = _app(tmp_path)
    chunks = [
        b"REMOTE_VIDEO_PAYLOAD_",
        b"STREAMED_WITHOUT_BODY_AGGREGATION",
    ]
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

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/projects/project-1/assets",
                headers={"Idempotency-Key": "remote-asset-1"},
                json=request_payload,
            )
            assert first.json()["status"] in {"QUEUED", "RUNNING"}
            before_cache = await client.get(
                f"/media/assets/{first.json()['assetVersionId']}",
            )
            await asyncio.gather(
                *list(file_asset_routes._REMOTE_INGEST_TASKS.values()),
            )
            replay = await client.post(
                "/projects/project-1/assets",
                headers={"Idempotency-Key": "remote-asset-1"},
                json=request_payload,
            )
            after_cache = await client.get(
                f"/media/assets/{first.json()['assetVersionId']}",
            )
            direct_after_cache = await client.get(
                f"/projects/project-1/assets/{first.json()['assetId']}/content",
                params={"versionId": first.json()["assetVersionId"]},
            )
            keyframe = await client.get(
                f"/media/assets/{first.json()['assetVersionId']}/frame",
                params={"timestamp": 4.5, "width": 640},
            )
        return (
            first,
            replay,
            before_cache,
            after_cache,
            direct_after_cache,
            keyframe,
        )

    (
        first,
        replay,
        before_cache,
        after_cache,
        direct_after_cache,
        keyframe,
    ) = asyncio.run(
        scenario(),
    )
    assert first.status_code == 202
    assert replay.status_code == 202
    assert first.json()["assetVersionId"].startswith("asset-version-")
    assert replay.json()["assetVersionId"] == first.json()["assetVersionId"]
    assert replay.json()["result"]["idempotentReplay"] is False
    assert before_cache.status_code in {200, 404}
    if before_cache.status_code == 200:
        assert before_cache.content == payload
    assert after_cache.status_code == 200
    assert after_cache.content == payload
    assert direct_after_cache.status_code == 200
    assert direct_after_cache.content == payload
    assert (
        "filename*=UTF-8''%E8%BF%9C%E7%A8%8B%E2%80%93" "%E8%A7%86%E9%A2%91.mp4"
    ) in direct_after_cache.headers["content-disposition"]
    assert keyframe.status_code == 200
    assert keyframe.content == b"LOCAL_KEYFRAME"
    assert keyframe.headers["x-creator-media-source"] == "local-keyframe-cache"
    assert observed_frame_source["source_path"] == (
        services.projects.project_root("project-1")
        / replay.json()["result"]["items"][0]["cacheRelativeUri"]
    )
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
    assert (
        project_root / cache_item["cacheRelativeUri"]
    ).read_bytes() == payload
    assert payload not in (project_root / "project.json").read_bytes()
    assert list((project_root / "assets" / ".staging").iterdir()) == []


def test_registered_remote_asset_is_indexed_while_uncached_media_is_unavailable(
    tmp_path,
) -> None:
    app, services = _app(tmp_path)
    item = file_asset_routes._register_remote_asset_sync(
        services,
        project_id="project-1",
        key="registered-only",
        url="https://assets.example/not-cached.mp4",
        requested_name="not-cached.mp4",
        attach_source=False,
        scope="POST-assets",
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(f"/media/assets/{item['assetVersionId']}")

    response = asyncio.run(scenario())
    assert response.status_code == 404
    version = services.projects.read(
        "project-1",
    ).project.assets.source_versions_by_id[item["assetVersionId"]]
    assert version.file_id is None
    assert version.metadata["publicSourceUrl"].endswith("/not-cached.mp4")


def test_remote_asset_download_does_not_hold_project_lifecycle_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app_instance, services = _app(tmp_path)
    lock_state = {"held": False, "acquisitions": 0}
    real_lifecycle_lock = services.projects.lifecycle_lock

    @contextmanager
    def tracked_lifecycle_lock(project_id: str):
        with real_lifecycle_lock(project_id):
            lock_state["acquisitions"] += 1
            lock_state["held"] = True
            try:
                yield
            finally:
                lock_state["held"] = False

    def staged_download(
        _url: str,
        *,
        file_store: file_asset_routes.AssetFileStore,
        staging_id: str,
        on_progress=None,
    ) -> file_asset_routes._RemoteAssetDownload:
        assert lock_state["held"] is False
        staged = file_store.stage_bytes(
            b"locked-remote",
            staging_id=staging_id,
        )
        return file_asset_routes._RemoteAssetDownload(
            name="locked.mp4",
            staged=staged,
            media_type="video/mp4",
        )

    monkeypatch.setattr(
        services.projects,
        "lifecycle_lock",
        tracked_lifecycle_lock,
    )
    monkeypatch.setattr(
        file_asset_routes,
        "_download_remote_to_staging",
        staged_download,
    )

    file_asset_routes._register_remote_asset_sync(
        services,
        project_id="project-1",
        key="lock-test",
        url="https://assets.example/locked.mp4",
        requested_name="locked.mp4",
        attach_source=False,
        scope="POST-assets",
    )

    result, replayed = file_asset_routes._ingest_remote_sync(
        services,
        project_id="project-1",
        key="lock-test",
        url="https://assets.example/locked.mp4",
        requested_name="locked.mp4",
        attach_source=False,
        scope="POST-assets",
    )

    assert result["status"] == "SUCCEEDED"
    assert replayed is False
    assert lock_state["acquisitions"] >= 1
    assert lock_state["held"] is False
    project_root = services.projects.project_root("project-1")
    assert list((project_root / "assets" / ".staging").iterdir()) == []


def test_remote_asset_limit_defaults_to_two_gib_and_honors_env_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CREATOR_REMOTE_ASSET_MAX_BYTES", raising=False)
    monkeypatch.delenv("CREATOR_DOWNLOAD_MAX_BYTES", raising=False)
    assert _remote_asset_max_bytes() == 2 * 1024 * 1024 * 1024
    assert 250_102_529 < _remote_asset_max_bytes()

    monkeypatch.setenv("CREATOR_DOWNLOAD_MAX_BYTES", "123")
    assert _remote_asset_max_bytes() == 123

    monkeypatch.setenv("CREATOR_REMOTE_ASSET_MAX_BYTES", "456")
    assert _remote_asset_max_bytes() == 456


def test_remote_asset_stream_limit_cleans_partial_staging(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app_instance, services = _app(tmp_path)
    monkeypatch.setenv("CREATOR_REMOTE_ASSET_MAX_BYTES", "5")
    _install_remote_transport(
        monkeypatch,
        chunks=[b"123", b"456"],
    )
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


def test_remote_asset_rejects_invalid_content_length_without_staging(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app_instance, services = _app(tmp_path)
    _install_remote_transport(
        monkeypatch,
        chunks=[b"unused"],
        headers={
            "content-type": "video/mp4",
            "content-length": "invalid",
        },
    )
    file_store = file_asset_routes.AssetFileStore(
        services.projects.project_root("project-1"),
    )

    with pytest.raises(ValidationError, match="Content-Length 非法"):
        file_asset_routes._download_remote_to_staging(
            "https://assets.example/invalid-length.mp4",
            file_store=file_store,
            staging_id="invalid-length-test",
        )

    assert list(file_store.staging_root.iterdir()) == []


def test_local_video_limit_remains_100_mib_and_is_independent_of_remote_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CREATOR_REMOTE_ASSET_MAX_BYTES",
        str(4 * 1024 * 1024 * 1024),
    )
    assert file_asset_routes._MAX_LOCAL_VIDEO_UPLOAD_BYTES == 100 * 1024 * 1024
    _validate_local_video_upload(
        name="source.mp4",
        media_type="video/mp4",
        size_bytes=100 * 1024 * 1024,
    )
    with pytest.raises(ValidationError, match="100 MiB"):
        _validate_local_video_upload(
            name="source.mp4",
            media_type="video/mp4",
            size_bytes=100 * 1024 * 1024 + 1,
        )

    # Do not add a new backend limit to non-video uploads in this change.
    _validate_local_video_upload(
        name="dataset.bin",
        media_type="application/octet-stream",
        size_bytes=100 * 1024 * 1024 + 1,
    )


def test_local_video_route_enforces_its_own_limit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, services = _app(tmp_path)
    monkeypatch.setattr(file_asset_routes, "_MAX_LOCAL_VIDEO_UPLOAD_BYTES", 5)
    monkeypatch.setenv("CREATOR_REMOTE_ASSET_MAX_BYTES", "1000")

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/projects/project-1/assets",
                headers={"Idempotency-Key": "local-video-too-large"},
                data={"clientRequestId": "local-video-too-large"},
                files={"file": ("source.mp4", b"123456", "video/mp4")},
            )

    response = asyncio.run(scenario())
    assert response.status_code == 422
    assert "本地视频超过 100 MiB" in response.text
    project = services.projects.read("project-1").project
    assert project.generation == 0
    assert project.assets.files_by_id == {}


def test_folder_import_commits_all_files_in_one_generation(tmp_path) -> None:
    app, services = _app(tmp_path)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
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

    accepted, loaded = asyncio.run(scenario())
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


def test_remote_asset_url_rejects_private_and_resolved_private_addresses() -> (
    None
):
    with pytest.raises(ValidationError, match="私有或保留网络"):
        _validate_public_remote_url("http://127.0.0.1/private")

    def private_resolver(*_args, **_kwargs):
        return [(2, 1, 6, "", ("10.0.0.8", 80))]

    with pytest.raises(ValidationError, match="私有或保留网络"):
        _validate_public_remote_url(
            "https://assets.example/video.mp4",
            resolver=private_resolver,
        )


def test_remote_asset_url_accepts_only_public_http_without_credentials() -> (
    None
):
    def public_resolver(*_args, **_kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    assert (
        _validate_public_remote_url(
            "https://assets.example/video.mp4?version=1#ignored",
            resolver=public_resolver,
        )
        == "https://assets.example/video.mp4?version=1"
    )
    with pytest.raises(ValidationError, match="用户名或密码"):
        _validate_public_remote_url(
            "https://user:secret@assets.example/video.mp4",
            resolver=public_resolver,
        )
