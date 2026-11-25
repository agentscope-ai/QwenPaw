# -*- coding: utf-8 -*-
"""A stored provider URL is reused only while it can still be fetched.

Issue #8592: the Token Plan endpoint records a short-lived pre-signed
object URL on the ArtifactVersion.  Reusing it after expiry made the
provider reject the reference download, which surfaced as a retryable
``MODEL_ERROR`` carrying a misleading configuration hint — and the signed
query string (OSSAccessKeyId/Signature) leaked into the task error.
"""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib

import httpx
import pytest

from models.image.base import (
    BaseImageModel,
    REFERENCE_DOWNLOAD_ADVICE,
    is_reference_download_failure,
)
from services.media_files.image_execution import (
    _provider_source_url_usable,
    _resolve_version_references,
)
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Project,
)
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit


def _signed_url(expires_at: datetime) -> str:
    return (
        "https://creator-oss.example.com/artifacts/sb-1.png"
        "?OSSAccessKeyId=AK123&Expires="
        f"{int(expires_at.timestamp())}&Signature=SECRET"
    )


def test_signed_source_url_is_reused_only_before_it_expires() -> None:
    now = datetime.now(UTC)
    assert _provider_source_url_usable(
        _signed_url(now + timedelta(hours=1)),
        now=now,
    )
    assert not _provider_source_url_usable(
        _signed_url(now - timedelta(minutes=1)),
        now=now,
    )
    # The safety margin keeps a request from racing expiry.
    assert not _provider_source_url_usable(
        _signed_url(now + timedelta(seconds=30)),
        now=now,
    )
    # Signed without a provable deadline: prefer the local copy.
    assert not _provider_source_url_usable(
        "https://creator-oss.example.com/a.png?OSSAccessKeyId=AK&Signature=S",
        now=now,
    )
    # An unsigned public URL is timeless.
    assert _provider_source_url_usable(
        "https://cdn.example.com/a.png",
        now=now,
    )
    assert not _provider_source_url_usable("file:///tmp/a.png", now=now)


def test_s3_presign_expiry_is_parsed() -> None:
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    issued = now - timedelta(minutes=5)
    base = (
        "https://bucket.s3.amazonaws.com/a.png"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        f"&X-Amz-Date={issued.strftime('%Y%m%dT%H%M%SZ')}"
    )
    assert _provider_source_url_usable(
        base + "&X-Amz-Expires=600&X-Amz-Signature=SECRET",
        now=now,
    )
    assert not _provider_source_url_usable(
        base + "&X-Amz-Expires=60&X-Amz-Signature=SECRET",
        now=now,
    )


def _project_with_artifact(tmp_path, source_url):
    project = Project.new(project_id="project-1", name="Provider URL")
    project_root = tmp_path / "project-1"
    relative_uri = "assets/artifacts/sb-1.png"
    path = project_root.joinpath(*relative_uri.split("/"))
    path.parent.mkdir(parents=True)
    payload = b"\x89PNG\r\n\x1a\n" + b"reference-bytes" * 8
    path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    created_at = datetime.now(UTC)
    project.assets.files_by_id["file-1"] = IndexedFile(
        file_id="file-1",
        kind="artifact_payload",
        relative_uri=relative_uri,
        sha256=checksum,
        size_bytes=len(payload),
        media_type="image/png",
        created_at=created_at,
    )
    project.assets.artifact_versions_by_id["av-1"] = ArtifactVersion(
        version_id="av-1",
        slot_id="slot-1",
        kind="r2v_storyboard_image",
        owner_ref="element:el-1",
        name="分镜图 1",
        file_id="file-1",
        checksum=checksum,
        based_on_generation=0,
        created_at=created_at,
        metadata={"provider": {"source_url": source_url}},
    )
    project.assets.artifact_slots_by_id["slot-1"] = ArtifactSlot(
        slot_id="slot-1",
        kind="r2v_storyboard_image",
        owner_ref="element:el-1",
        version_ids=["av-1"],
        selected_version_id="av-1",
    )
    return project, project_root


def test_expired_provider_url_falls_back_to_the_local_copy(tmp_path) -> None:
    project, project_root = _project_with_artifact(
        tmp_path,
        _signed_url(datetime.now(UTC) - timedelta(hours=1)),
    )

    urls, checksums, read_set = _resolve_version_references(
        project=project,
        project_root=project_root,
        version_ids=["av-1"],
    )

    assert urls == [
        project_root.joinpath(
            "assets",
            "artifacts",
            "sb-1.png",
        )
        .resolve()
        .as_uri(),
    ]
    assert checksums == [
        project.assets.artifact_versions_by_id["av-1"].checksum,
    ]
    assert read_set[0]["fileId"] == "file-1"


def test_live_provider_url_is_preferred(tmp_path) -> None:
    source_url = _signed_url(datetime.now(UTC) + timedelta(hours=1))
    project, project_root = _project_with_artifact(tmp_path, source_url)

    urls, _checksums, read_set = _resolve_version_references(
        project=project,
        project_root=project_root,
        version_ids=["av-1"],
    )

    assert urls == [source_url]
    assert read_set[0]["sourceUrl"] == source_url


def test_expired_provider_url_falls_back_for_video_and_first_frame(
    tmp_path,
) -> None:
    """One stored image must not work for generation but fail as video input.

    Issue #8592: only the image path checked the deadline, so yesterday's
    generated image could be regenerated while the video reference list and
    the first-frame input still handed the provider a dead pre-signed URL.
    """
    from services.media_files.r2v_execution import (
        _resolve_reference_versions,
        _resolve_single_media_version,
    )

    project, project_root = _project_with_artifact(
        tmp_path,
        _signed_url(datetime.now(UTC) - timedelta(hours=1)),
    )
    local = (
        project_root.joinpath("assets", "artifacts", "sb-1.png")
        .resolve()
        .as_uri()
    )

    urls, _checksums, _provenance, read_set = _resolve_reference_versions(
        project=project,
        project_root=project_root,
        version_ids=["av-1"],
    )
    assert urls == [local]
    assert "sourceUrl" not in read_set[0]

    url, _checksum, ref, read_entry = _resolve_single_media_version(
        project=project,
        project_root=project_root,
        version_id="av-1",
        media_prefix="image/",
        label="首帧",
    )
    assert url == local
    assert ref == "artifact-version:av-1"
    assert "sourceUrl" not in read_entry


def test_live_provider_url_is_reused_for_video_and_first_frame(
    tmp_path,
) -> None:
    from services.media_files.r2v_execution import (
        _resolve_reference_versions,
        _resolve_single_media_version,
    )

    source_url = _signed_url(datetime.now(UTC) + timedelta(hours=1))
    project, project_root = _project_with_artifact(tmp_path, source_url)

    urls, _checksums, _provenance, read_set = _resolve_reference_versions(
        project=project,
        project_root=project_root,
        version_ids=["av-1"],
    )
    assert urls == [source_url]
    assert read_set[0]["sourceUrl"] == source_url

    url, _checksum, _ref, read_entry = _resolve_single_media_version(
        project=project,
        project_root=project_root,
        version_id="av-1",
        media_prefix="image/",
        label="首帧",
    )
    assert url == source_url
    assert read_entry["sourceUrl"] == source_url


class _ReferenceRejectingProvider(BaseImageModel):
    """A provider that answers HTTP 400 with the reference URL echoed."""

    backend_name = "test"
    base_url = "https://provider.example.com"

    def __init__(self, detail: str) -> None:
        super().__init__(
            model_name="qwen-image",
            api_key="sk-test",
            timeout=5,
        )
        self.detail = detail

    @classmethod
    def from_config(cls) -> "_ReferenceRejectingProvider":  # pragma: no cover
        raise NotImplementedError

    @property
    def generation_url(self) -> str:
        return "https://provider.example.com/generate"

    async def _request(
        self,
        client,
        prompt,
        aspect_ratio,
        clean_reference_urls,
        mode="generate",
    ):
        return httpx.Response(
            400,
            request=httpx.Request("POST", self.generation_url),
            text=self.detail,
        )

    async def _decode(self, data):  # pragma: no cover - not reached
        raise NotImplementedError


def test_expired_reference_url_is_a_deterministic_provider_error() -> None:
    detail = (
        '{"code":"InvalidParameter","message":"failed to download image: '
        "https://creator-oss.example.com/sb-1.png?OSSAccessKeyId=AK123"
        '&Expires=1&Signature=SECRET"}'
    )
    provider = _ReferenceRejectingProvider(detail)

    with pytest.raises(ModelError) as excinfo:
        asyncio.run(
            provider.generate(
                "cat",
                reference_image_urls=["file:///tmp/sb-1.png"],
            ),
        )

    error = excinfo.value
    assert not error.retryable
    assert REFERENCE_DOWNLOAD_ADVICE in str(error)
    assert "SECRET" not in str(error)
    assert "AK123" not in str(error)
    assert is_reference_download_failure(str(error))
