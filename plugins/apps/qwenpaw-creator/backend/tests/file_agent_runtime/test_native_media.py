# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest

from api.file_asset_routes import (
    _AssetInput,
    _ingest_many_sync,
    _register_remote_asset_sync,
)
from domain.errors import ValidationError
from models import vlm_model
from services.file_agent_runtime import native_media
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.models import CreatorMessageRecord

pytestmark = pytest.mark.unit

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPEN_GATEWAY_BASE_URL = "https://api.openai.example/v1"


def _ingest_local_video(services, *, scope: str) -> dict:
    """Ingest one file-backed video source and return its first item."""

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
        scope=scope,
    )
    return response["items"][0]


def _local_video_request(version_id: str) -> CreatorMessageRecord:
    return CreatorMessageRecord(
        message_id="message-1",
        project_id="project-1",
        creator_session_id="session-1",
        conversation_id="conversation-1",
        message_seq=1,
        role="user",
        content_parts=[{"type": "text", "text": "理解本地视频"}],
        metadata={"assetVersionRefs": [f"asset-version:{version_id}"]},
    )


def _project(tmp_path) -> CreatorFileServices:
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    return services


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
        "transport_local_media_url",
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


def test_non_dashscope_provider_inlines_local_media_without_upload_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-DashScope gateway gets inline Base64 and needs no upload key.

    Regression guard: media understanding used to upload every local file to
    the DashScope model-bound temporary OSS and authenticate with the VLM
    key, so a non-Bailian provider answered 401 for all four call sites and
    both image and video understanding silently produced empty records.
    """

    services = _project(tmp_path)
    item = _ingest_local_video(services, scope="test-non-dashscope")

    async def forbidden_upload(*_args, **_kwargs):
        raise AssertionError(
            "a non-DashScope gateway must never reach the DashScope upload",
        )

    monkeypatch.setattr(
        vlm_model,
        "upload_local_file_to_dashscope_temp",
        forbidden_upload,
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_base_url",
        lambda: OPEN_GATEWAY_BASE_URL,
    )
    # No credential at all: the inline transport must not require one.
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_api_key",
        lambda: "",
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_model_name",
        lambda: "gpt-vision",
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 1024 * 1024,
    )

    parts = asyncio.run(
        native_media.source_intelligence_content_parts(
            services,
            project_id="project-1",
            request=_local_video_request(item["assetVersionId"]),
        ),
    )

    assert len(parts) == 1
    payload = parts[0]["video_url"]
    assert payload["url"].startswith("data:video/mp4;base64,")
    decoded = base64.b64decode(payload["url"].split(",", 1)[1])
    assert decoded == b"video-bytes"
    assert payload["versionId"] == item["assetVersionId"]
    assert payload["checksum"] == item["checksum"]


def test_dashscope_provider_still_uploads_and_requires_the_vlm_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Making the key conditional must not weaken the DashScope path."""

    services = _project(tmp_path)
    item = _ingest_local_video(services, scope="test-dashscope-key")

    async def forbidden_upload(*_args, **_kwargs):
        raise AssertionError(
            "the missing-key guard must reject before any upload",
        )

    monkeypatch.setattr(
        vlm_model,
        "upload_local_file_to_dashscope_temp",
        forbidden_upload,
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_base_url",
        lambda: DASHSCOPE_BASE_URL,
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_api_key",
        lambda: "",
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )

    with pytest.raises(ValidationError, match="VLM API key"):
        asyncio.run(
            native_media.source_intelligence_content_parts(
                services,
                project_id="project-1",
                request=_local_video_request(item["assetVersionId"]),
            ),
        )


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
        "transport_local_media_url",
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


def test_short_video_target_ref_is_delivered_as_frame_sequence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clips below the native-video minimum become ordered frame parts."""

    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    response, _replayed = _ingest_many_sync(
        services,
        project_id="project-1",
        key="short-media",
        inputs=[
            _AssetInput(
                name="short.mp4",
                content=b"short-video-bytes",
                media_type="video/mp4",
            ),
        ],
        attach_source=True,
        scope="test-short-media",
    )
    version_id = response["items"][0]["assetVersionId"]
    logical_asset_id = response["items"][0]["assetId"]
    uploads: list[str] = []

    async def fake_upload(path, **kwargs):
        del kwargs
        uploads.append(path.name)
        return f"oss://dashscope/{path.name}"

    def fake_extract(local_path, duration_seconds, output_dir):
        del local_path, duration_seconds
        frames = []
        for index, stamp_ms in enumerate((0, 427, 853, 1230)):
            frame_path = output_dir / f"frame-{index:02d}.jpg"
            frame_path.write_bytes(b"jpeg-bytes")
            frames.append((stamp_ms, frame_path))
        return frames

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
        "transport_local_media_url",
        fake_upload,
    )
    monkeypatch.setattr(
        native_media,
        "probe_media",
        lambda _path: SimpleNamespace(duration_seconds=1.28),
    )
    monkeypatch.setattr(
        native_media,
        "_extract_video_frames_sync",
        fake_extract,
    )
    request = CreatorMessageRecord(
        message_id="message-short",
        project_id="project-1",
        creator_session_id="session-1",
        conversation_id="conversation-1",
        message_seq=1,
        role="user",
        content_parts=[{"type": "text", "text": "理解短片"}],
    )

    parts = asyncio.run(
        native_media.source_intelligence_content_parts(
            services,
            project_id="project-1",
            request=request,
            target_refs=[f"asset:{logical_asset_id}"],
        ),
    )

    assert [part["type"] for part in parts] == [
        "text",
        "image_url",
        "image_url",
        "image_url",
        "image_url",
    ]
    assert "1280ms" in parts[0]["text"]
    assert "short.mp4" in parts[0]["text"]
    assert parts[1]["image_url"]["frameTimestampMs"] == 0
    assert parts[4]["image_url"]["frameTimestampMs"] == 1230
    assert all(
        part["image_url"]["versionId"] == version_id for part in parts[1:]
    )
    assert uploads == [
        "frame-00.jpg",
        "frame-01.jpg",
        "frame-02.jpg",
        "frame-03.jpg",
    ]


def test_target_refs_scope_media_to_the_delegated_asset(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-target delegations must not re-observe sibling uploads."""

    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id="project-1", name="Project"),
    )
    response, _replayed = _ingest_many_sync(
        services,
        project_id="project-1",
        key="batch-media",
        inputs=[
            _AssetInput(
                name="a.png",
                content=b"a-bytes",
                media_type="image/png",
            ),
            _AssetInput(
                name="b.png",
                content=b"b-bytes",
                media_type="image/png",
            ),
        ],
        attach_source=True,
        scope="test-batch-media",
    )
    items = response["items"]
    target_item = items[0]
    uploaded_bytes: list[bytes] = []

    async def fake_upload(path, **kwargs):
        del kwargs
        uploaded_bytes.append(path.read_bytes())
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
        "transport_local_media_url",
        fake_upload,
    )
    request = CreatorMessageRecord(
        message_id="message-batch",
        project_id="project-1",
        creator_session_id="session-1",
        conversation_id="conversation-1",
        message_seq=1,
        role="user",
        content_parts=[{"type": "text", "text": "上传了两张图"}],
        metadata={
            "assetVersionRefs": [
                f"asset-version:{item['assetVersionId']}" for item in items
            ],
        },
    )

    parts = asyncio.run(
        native_media.source_intelligence_content_parts(
            services,
            project_id="project-1",
            request=request,
            target_refs=[f"asset:{target_item['assetId']}"],
        ),
    )

    assert [part["type"] for part in parts] == ["image_url"]
    assert parts[0]["image_url"]["versionId"] == target_item["assetVersionId"]
    assert uploaded_bytes == [b"a-bytes"]


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
        "transport_local_media_url",
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


def _inline_transport_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point the VLM at a non-DashScope gateway that has no upload key.

    Reaching the DashScope temporary OSS fails the test, so a call site that
    skipped the provider branch is caught instead of quietly handing the
    gateway an ``oss://`` URL it cannot fetch with a 401 credential.
    """

    async def forbidden_upload(*_args, **_kwargs):
        raise AssertionError(
            "a non-DashScope gateway must never reach the DashScope upload",
        )

    monkeypatch.setattr(
        vlm_model,
        "upload_local_file_to_dashscope_temp",
        forbidden_upload,
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_base_url",
        lambda: OPEN_GATEWAY_BASE_URL,
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_api_key",
        lambda: "",
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_model_name",
        lambda: "gpt-vision",
    )
    monkeypatch.setattr(
        native_media.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 1024 * 1024,
    )


def test_document_page_parts_inline_for_a_non_dashscope_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rendered document pages inline as Base64 off the DashScope path.

    Same regression as the asset-version call site, but read_document output
    reaches the VLM through its own part builder and its own key guard.
    """

    from services.source_analysis.service import (
        document_page_path,
        document_page_ref,
    )

    services = _project(tmp_path)
    _inline_transport_config(monkeypatch)
    project_root = services.projects.project_root("project-1")
    checksum = "c" * 64
    page_path = document_page_path(project_root, checksum, 1)
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_bytes(b"png-bytes")
    ref = document_page_ref(checksum, 1)

    parts = asyncio.run(
        native_media.document_page_content_parts(
            services,
            project_id="project-1",
            tool_result={"pageImageRefs": [ref]},
        ),
    )

    assert [part["type"] for part in parts] == ["image_url"]
    payload = parts[0]["image_url"]
    assert payload["url"].startswith("data:image/png;base64,")
    decoded = base64.b64decode(payload["url"].split(",", 1)[1])
    assert decoded == b"png-bytes"
    assert payload["mediaType"] == "image/png"
    assert payload["page"] == 1
    assert parts[0]["attachment"] == {
        "documentPageRef": ref,
        "mediaType": "image/png",
    }


def test_downscaled_document_page_reports_the_media_it_carries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized page inlines as JPEG, so mediaType has to follow.

    The part builder declared ``image/png`` unconditionally while the
    inline transport re-encodes an over-budget page as a downscaled
    JPEG. Consumers read the data URL header first, so nothing breaks
    today; the stale sibling field is exactly what this pins.
    """

    from services.source_analysis.service import (
        document_page_path,
        document_page_ref,
    )

    services = _project(tmp_path)
    _inline_transport_config(monkeypatch)
    project_root = services.projects.project_root("project-1")
    checksum = "c" * 64
    page_path = document_page_path(project_root, checksum, 1)
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_bytes(b"png-bytes")
    ref = document_page_ref(checksum, 1)

    async def downscaled_transport(_path, **_kwargs):
        return "data:image/jpeg;base64," + base64.b64encode(b"j").decode()

    monkeypatch.setattr(
        native_media,
        "transport_local_media_url",
        downscaled_transport,
    )

    parts = asyncio.run(
        native_media.document_page_content_parts(
            services,
            project_id="project-1",
            tool_result={"pageImageRefs": [ref]},
        ),
    )

    assert parts[0]["image_url"]["mediaType"] == "image/jpeg"
    assert parts[0]["attachment"]["mediaType"] == "image/jpeg"


def test_video_frame_parts_inline_for_a_non_dashscope_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extracted source frames inline as Base64 off the DashScope path.

    The frame refs come from a persisted read_source_video task result, so
    this also covers the nested-payload branch of that part builder.
    """

    from services.media.source_video_reader import (
        video_frame_path,
        video_frame_ref,
    )

    services = _project(tmp_path)
    _inline_transport_config(monkeypatch)
    project_root = services.projects.project_root("project-1")
    version_id = "version-1"
    frame = video_frame_path(project_root, version_id, 5000)
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"jpeg-bytes")
    ref = video_frame_ref(version_id, 5000)

    parts = asyncio.run(
        native_media.video_frame_content_parts(
            services,
            project_id="project-1",
            # wait=TASK tool payloads nest the task output under "result".
            task_result={"result": {"frameImageRefs": [{"ref": ref}]}},
        ),
    )

    # Each frame keeps its source timestamp ahead of the pixels, mirroring
    # the upstream read_video ``<MM:SS>`` + frame layout.
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert parts[0]["text"] == "<5000>"
    payload = parts[1]["image_url"]
    assert payload["url"].startswith("data:image/jpeg;base64,")
    decoded = base64.b64decode(payload["url"].split(",", 1)[1])
    assert decoded == b"jpeg-bytes"
    assert payload["mediaType"] == "image/jpeg"
    assert payload["frameTimestampMs"] == 5000
    assert parts[1]["attachment"] == {
        "videoFrameRef": ref,
        "mediaType": "image/jpeg",
    }


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
