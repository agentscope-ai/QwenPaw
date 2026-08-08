# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.file_asset_routes import (
    _AssetInput,
    _ingest_many_sync,
    _register_remote_asset_sync,
)
from services.file_agent_runtime import native_media
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.models import CreatorMessageRecord

pytestmark = pytest.mark.unit


def test_asset_version_refs_are_uploaded_and_attached_as_native_media(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    response, _replayed = _ingest_many_sync(
        services,
        project_id="project-1",
        key="local-media",
        inputs=[
            _AssetInput(
                name="input.mp4",
                content=b"video-bytes",
                media_type="video/mp4",
            ),
        ],
        attach_source=True,
        scope="test-local-media",
    )
    version_id = response["items"][0]["assetVersionId"]
    observed_paths = []

    async def fake_upload(path, **kwargs):
        observed_paths.append((path, kwargs))
        return "oss://dashscope/input.mp4"

    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_api_key",
        lambda: "test-vlm-key",
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )
    monkeypatch.setattr(
        native_media,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    request = CreatorMessageRecord(
        message_id="message-1",
        project_id="project-1",
        creator_session_id="session-1",
        conversation_id="conversation-1",
        message_seq=1,
        role="user",
        content_parts=[{"type": "text", "text": "理解本地视频"}],
        metadata={"assetVersionRefs": [f"asset-version:{version_id}"]},
    )

    parts = asyncio.run(
        native_media.source_intelligence_content_parts(
            services,
            project_id="project-1",
            request=request,
        ),
    )

    assert len(observed_paths) == 1
    assert observed_paths[0][0].read_bytes() == b"video-bytes"
    assert parts == [
        {
            "type": "video_url",
            "video_url": {
                "url": "oss://dashscope/input.mp4",
                "mediaType": "video/mp4",
                "versionId": version_id,
                "checksum": response["items"][0]["checksum"],
                "fps": 0.5,
            },
            "attachment": {
                "assetVersionRef": f"asset-version:{version_id}",
                "mediaType": "video/mp4",
            },
        },
    ]


def test_url_backed_version_uses_public_source_without_local_cache(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    item = _register_remote_asset_sync(
        services,
        project_id="project-1",
        key="remote-media",
        url="https://assets.example/input.mp4",
        requested_name="input.mp4",
        attach_source=False,
        scope="POST-assets",
    )

    async def unexpected_upload(*_args, **_kwargs):
        raise AssertionError(
            "remote source must not be uploaded from a local cache",
        )

    monkeypatch.setattr(
        native_media,
        "upload_local_file_to_dashscope_temp",
        unexpected_upload,
    )
    request = CreatorMessageRecord(
        message_id="message-remote",
        project_id="project-1",
        creator_session_id="session-1",
        conversation_id="conversation-1",
        message_seq=1,
        role="user",
        content_parts=[
            {
                "type": "video_url",
                "video_url": {"url": "https://assets.example/input.mp4"},
            },
        ],
        metadata={
            "assetVersionRefs": [f"asset-version:{item['assetVersionId']}"],
        },
    )

    parts = asyncio.run(
        native_media.source_intelligence_content_parts(
            services,
            project_id="project-1",
            request=request,
        ),
    )

    assert parts == [
        {
            "type": "video_url",
            "video_url": {"url": "https://assets.example/input.mp4"},
        },
    ]


def test_url_backed_version_uses_runtime_cache_probe_for_duration(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    item = _register_remote_asset_sync(
        services,
        project_id="project-1",
        key="remote-media-cached",
        url="https://assets.example/cached.mp4",
        requested_name="cached.mp4",
        attach_source=True,
        scope="POST-assets",
    )
    cache_path = tmp_path / "cached.mp4"
    cache_path.write_bytes(b"cached-video")
    monkeypatch.setattr(
        native_media,
        "resolve_remote_cache",
        lambda *_args, **_kwargs: SimpleNamespace(path=cache_path),
    )
    monkeypatch.setattr(
        native_media,
        "probe_media",
        lambda _path: SimpleNamespace(duration_seconds=3502.567),
    )
    request = CreatorMessageRecord(
        message_id="message-cached",
        project_id="project-1",
        creator_session_id="session-1",
        conversation_id="conversation-1",
        message_seq=1,
        role="user",
        content_parts=[{"type": "text", "text": "理解远程长视频"}],
        metadata={
            "assetVersionRefs": [f"asset-version:{item['assetVersionId']}"],
        },
    )

    parts = asyncio.run(
        native_media.source_intelligence_content_parts(
            services,
            project_id="project-1",
            request=request,
        ),
    )

    assert parts[0]["video_url"] == {
        "url": "https://assets.example/cached.mp4",
        "mediaType": "video/mp4",
        "versionId": item["assetVersionId"],
        "checksum": item["checksum"],
        "fps": 0.5,
        "durationMs": 3_502_567,
    }


def test_document_page_refs_become_native_image_parts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.source_analysis.service import (
        document_page_path,
        document_page_ref,
    )

    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    project_root = services.projects.project_root("project-1")
    checksum = "c" * 64
    for page in (1, 2):
        path = document_page_path(project_root, checksum, page)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png-bytes")
    uploads: list[str] = []

    async def fake_upload(path, **kwargs):
        del kwargs
        uploads.append(path.name)
        return f"oss://dashscope/{path.name}"

    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_api_key",
        lambda: "test-vlm-key",
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )
    monkeypatch.setattr(
        native_media,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    refs = [document_page_ref(checksum, page) for page in (1, 2)]

    parts = asyncio.run(
        native_media.document_page_content_parts(
            services,
            project_id="project-1",
            tool_result={"pageImageRefs": refs},
        ),
    )

    assert uploads == ["page-0001.png", "page-0002.png"]
    assert [part["type"] for part in parts] == ["image_url", "image_url"]
    assert parts[0]["image_url"] == {
        "url": "oss://dashscope/page-0001.png",
        "mediaType": "image/png",
        "page": 1,
    }
    assert parts[1]["attachment"]["documentPageRef"] == refs[1]


def test_document_page_parts_reject_out_of_boundary_refs(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from domain.errors import StorageIntegrityError

    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_api_key",
        lambda: "test-vlm-key",
    )

    with pytest.raises(StorageIntegrityError):
        asyncio.run(
            native_media.document_page_content_parts(
                services,
                project_id="project-1",
                tool_result={"pageImageRefs": ["asset-version:evil"]},
            ),
        )
