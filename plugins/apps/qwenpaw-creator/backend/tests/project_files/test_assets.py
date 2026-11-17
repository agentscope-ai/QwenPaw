# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import hashlib
from io import BytesIO
import os
import stat

import pytest

from domain.errors import ConflictError, SourceAssetInUseError
from services.file_agent_runtime.work_graph import (
    WorkNodeStatus,
    derive_work_graph,
)
from services.project_files.assets import (
    AssetAlreadyExists,
    AssetFileCorrupt,
    AssetFileStatus,
    AssetFileStore,
    AssetPathError,
    StagedAssetError,
)
from services.project_files.auto_snapshot import auto_snapshot_timelines
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    AssetIndex,
    AudioCreation,
    EditCreation,
    ElementLocation,
    I2VCreation,
    IndexedFile,
    OverlayCreation,
    Project,
    R2VCreation,
    S2VCreation,
    SourceAssetVersion,
    SourceIntelligenceVersion,
    SourceVersionRenderSource,
    TimelineElement,
    TimelineSpan,
)
from services.project_files.store import ProjectStore

pytestmark = pytest.mark.unit
NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


def _store(tmp_path, name: str = "project-1") -> AssetFileStore:
    root = (tmp_path / name).resolve()
    root.mkdir()
    return AssetFileStore(root, chunk_size=3)


def _indexed(
    *,
    file_id: str,
    relative_uri: str,
    content: bytes,
    sha256: str | None = None,
    size_bytes: int | None = None,
) -> IndexedFile:
    return IndexedFile(
        file_id=file_id,
        kind="other",
        relative_uri=relative_uri,
        sha256=sha256 or hashlib.sha256(content).hexdigest(),
        size_bytes=len(content) if size_bytes is None else size_bytes,
        media_type="application/octet-stream",
        created_at=NOW,
    )


def test_streaming_stage_and_immutable_publish_are_fsynced(
    tmp_path,
    monkeypatch,
):
    fsync_modes: list[int] = []
    real_fsync = os.fsync

    def record_fsync(descriptor: int) -> None:
        fsync_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr("services.project_files.assets.os.fsync", record_fsync)
    store = _store(tmp_path)
    content = b"streamed-asset-payload"

    staged = store.stage_stream(BytesIO(content), staging_id="upload-1")
    assert staged.path.is_file()
    assert staged.size_bytes == len(content)
    assert staged.sha256 == hashlib.sha256(content).hexdigest()

    published = store.publish(
        staged,
        "assets/sources/source-1/version-1/original.bin",
        expected_sha256=staged.sha256,
        expected_size_bytes=staged.size_bytes,
    )

    final = store.project_root / published.relative_uri
    assert final.read_bytes() == content
    assert not staged.path.exists()
    assert published.sha256 == staged.sha256
    # The staged file must be durable on every platform. Windows does not
    # support directory fsync; POSIX also persists publication metadata.
    assert sum(stat.S_ISREG(mode) for mode in fsync_modes) >= 1
    if os.name != "nt":
        assert sum(stat.S_ISDIR(mode) for mode in fsync_modes) >= 4
    assert not (store.assets_root / "ai-edit-plans").exists()


def test_publish_never_overwrites_an_existing_immutable_path(tmp_path):
    store = _store(tmp_path)
    uri = "assets/artifacts/slot-1/version-1/payload.bin"
    first = store.stage_bytes(b"first")
    store.publish(first, uri)
    second = store.stage_bytes(b"second")

    with pytest.raises(AssetAlreadyExists):
        store.publish(second, uri)

    assert (store.project_root / uri).read_bytes() == b"first"
    assert second.path.exists()
    store.abandon(second)
    assert not second.path.exists()


def test_publish_rechecks_staged_content_before_moving_it(tmp_path):
    store = _store(tmp_path)
    staged = store.stage_bytes(b"before")
    staged.path.write_bytes(b"after!")

    with pytest.raises(StagedAssetError, match="modified"):
        store.publish(staged, "assets/content/file-1.bin")

    assert not (store.assets_root / "content" / "file-1.bin").exists()


@pytest.mark.parametrize(
    "relative_uri",
    [
        "../outside.bin",
        "/assets/content/file.bin",
        r"assets\content\file.bin",
        "assets/.staging/file.bin",
        "assets/content/bad\x01.bin",
    ],
)
def test_publish_rejects_noncanonical_or_reserved_paths(
    tmp_path,
    relative_uri,
):
    store = _store(tmp_path)
    staged = store.stage_bytes(b"payload")

    with pytest.raises(AssetPathError):
        store.publish(staged, relative_uri)

    assert staged.path.exists()


def test_symlink_parents_cannot_escape_project(tmp_path, directory_link):
    store = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    directory_link(outside, store.assets_root / "sources")
    staged = store.stage_bytes(b"payload")

    with pytest.raises(AssetPathError, match="non-symlink"):
        store.publish(staged, "assets/sources/source-1/version-1/original.bin")


def test_symlink_files_cannot_escape_project(tmp_path, file_symlink):
    store = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.assets_root / "content").mkdir()
    outside_file = outside / "outside.bin"
    outside_file.write_bytes(b"outside")
    file_symlink(outside_file, store.assets_root / "content" / "linked.bin")
    indexed = _indexed(
        file_id="file-linked",
        relative_uri="assets/content/linked.bin",
        content=b"outside",
    )

    assert store.inspect(indexed).status is AssetFileStatus.UNSAFE
    with pytest.raises(AssetPathError, match="symlink"):
        store.open_verified(indexed)


def test_index_validation_and_reads_verify_presence_size_and_sha256(tmp_path):
    store = _store(tmp_path)
    valid_content = b"valid"
    corrupt_content = b"wrong"
    valid_uri = "assets/content/valid.bin"
    corrupt_uri = "assets/content/corrupt.bin"
    store.publish(store.stage_bytes(valid_content), valid_uri)
    store.publish(store.stage_bytes(corrupt_content), corrupt_uri)

    index = AssetIndex(
        files_by_id={
            "file-valid": _indexed(
                file_id="file-valid",
                relative_uri=valid_uri,
                content=valid_content,
            ),
            "file-corrupt": _indexed(
                file_id="file-corrupt",
                relative_uri=corrupt_uri,
                content=corrupt_content,
                sha256="0" * 64,
            ),
            "file-missing": _indexed(
                file_id="file-missing",
                relative_uri="assets/content/missing.bin",
                content=b"missing",
            ),
        },
    )

    report = store.validate_index(index)
    assert [item.file_id for item in report.files] == [
        "file-corrupt",
        "file-missing",
        "file-valid",
    ]
    assert {item.file_id: item.status for item in report.files} == {
        "file-corrupt": AssetFileStatus.CORRUPT,
        "file-missing": AssetFileStatus.MISSING,
        "file-valid": AssetFileStatus.AVAILABLE,
    }
    assert not report.valid
    assert (
        store.read_verified(index.files_by_id["file-valid"]) == valid_content
    )
    with pytest.raises(AssetFileCorrupt, match="sha256"):
        store.open_verified(index.files_by_id["file-corrupt"])
    with pytest.raises(AssetFileCorrupt, match="unavailable"):
        store.require_valid_index(index)


def test_orphan_scan_marks_candidates_and_requires_persisted_grace(
    tmp_path,
    directory_link,
):
    store = _store(tmp_path)
    indexed_content = b"indexed"
    indexed_uri = "assets/content/indexed.bin"
    orphan_uri = "assets/content/orphan.bin"
    store.publish(store.stage_bytes(indexed_content), indexed_uri)
    store.publish(store.stage_bytes(b"orphan"), orphan_uri)
    staged = store.stage_bytes(b"in-flight")

    # An old mtime must not let a newly discovered orphan skip its grace period.
    os.utime(store.project_root / orphan_uri, (1, 1))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.bin").write_bytes(b"outside")
    directory_link(outside, store.assets_root / "linked")
    index = AssetIndex(
        files_by_id={
            "file-indexed": _indexed(
                file_id="file-indexed",
                relative_uri=indexed_uri,
                content=indexed_content,
            ),
        },
    )

    first = store.scan_orphans(index, now=NOW, grace_period=timedelta(hours=1))
    assert [item.relative_uri for item in first.candidates] == [orphan_uri]
    assert first.candidates[0].first_observed_at == NOW
    assert not first.candidates[0].eligible_for_collection
    assert first.unsafe_entries == ("assets/linked",)
    assert (
        staged.path.exists()
    )  # .staging is excluded from orphan publication GC

    second = store.scan_orphans(
        index,
        previous_candidates={orphan_uri: NOW - timedelta(hours=2)},
        now=NOW,
        grace_period=timedelta(hours=1),
    )
    assert second.candidates[0].eligible_for_collection
    assert (store.project_root / orphan_uri).exists()  # scan never deletes

    with pytest.raises(ValueError, match="positive"):
        store.scan_orphans(index, now=NOW, grace_period=timedelta(0))


# ── source asset version deletion: blocking references and file reclaim ─────

DELETION_PROJECT_ID = "project-1"
PORTRAIT_BYTES = b"\x89PNG\r\n\x1a\n" + b"portrait-frame" * 16
DRIVE_AUDIO_BYTES = b"RIFF" + b"drive-audio-payload" * 12
CLIP_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"source-clip" * 32
INTELLIGENCE_BYTES = b'{"coverage": {"transcript": "ok"}}'


def _deletion_store(tmp_path):
    """A ProjectStore holding a bare ``project-1`` with its asset root."""
    store = ProjectStore(tmp_path.resolve())
    base = store.create(
        Project.new(project_id=DELETION_PROJECT_ID, name="Deletion"),
    )
    return store, base


def _publish(
    store: ProjectStore,
    file_id: str,
    relative_uri: str,
    content: bytes,
    *,
    kind: str = "source_original",
    media_type: str = "application/octet-stream",
) -> IndexedFile:
    """Write ``content`` through the real asset store and index it."""
    assets = AssetFileStore(store.project_root(DELETION_PROJECT_ID))
    published = assets.publish(
        assets.stage_bytes(content, staging_id=file_id),
        relative_uri,
    )
    return IndexedFile(
        file_id=file_id,
        kind=kind,
        relative_uri=published.relative_uri,
        sha256=published.sha256,
        size_bytes=published.size_bytes,
        media_type=media_type,
        created_at=NOW,
    )


def _version(
    *,
    version_id: str,
    file_id: str,
    checksum: str,
    media_kind: str,
    media_type: str,
    duration_seconds: float | None = None,
) -> SourceAssetVersion:
    return SourceAssetVersion(
        version_id=version_id,
        logical_asset_id=f"asset-{version_id}",
        name=f"{version_id}.{media_kind}",
        file_id=file_id,
        checksum=checksum,
        media_kind=media_kind,
        media_type=media_type,
        duration_seconds=duration_seconds,
        created_at=NOW,
    )


def _s2v_element(
    element_id: str,
    *,
    portrait_version_id: str | None = None,
    audio_version_id: str | None = None,
) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        location=ElementLocation(),
        creation=S2VCreation(
            portrait_version_id=portrait_version_id,
            script="介绍一下这款产品",
            audio_version_id=audio_version_id,
        ),
    )


def _edit_element(element_id: str, version_id: str) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        span=TimelineSpan(start_tick=0, duration_tick=2000),
        location=ElementLocation(),
        creation=EditCreation(intent="pick"),
        render_source=SourceVersionRenderSource(
            version_id=version_id,
            source_in_tick=0,
            source_out_tick=2000,
        ),
    )


def _i2v_element(
    element_id: str,
    *,
    first_frame_version_id: str | None = None,
    label: str = "",
) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        label=label,
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        location=ElementLocation(),
        creation=I2VCreation(
            first_frame_version_id=first_frame_version_id,
            video_prompt="雪花落满屋檐",
        ),
    )


def _audio_element(element_id: str, version_id: str) -> TimelineElement:
    """One audio track: its creation and render_source name the same version."""
    return TimelineElement(
        element_id=element_id,
        span=TimelineSpan(start_tick=0, duration_tick=2000),
        creation=AudioCreation(
            source_asset_version_id=version_id,
            role="bgm",
        ),
        render_source=SourceVersionRenderSource(
            version_id=version_id,
            source_in_tick=0,
            source_out_tick=2000,
        ),
    )


def _r2v_element(
    element_id: str,
    *,
    storyboard_version_ids: list[str] | None = None,
    video_version_ids: list[str] | None = None,
) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        location=ElementLocation(),
        creation=R2VCreation(
            video_prompt="镜头横移",
            storyboard_reference_version_ids=list(
                storyboard_version_ids or [],
            ),
            video_reference_version_ids=list(video_version_ids or []),
        ),
    )


def _overlay_element(
    element_id: str,
    *,
    reference_version_ids: list[str] | None = None,
    render_source_version_id: str | None = None,
    text: str = "标题",
    prompt: str = "",
) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        span=TimelineSpan(start_tick=0, duration_tick=1000),
        location=ElementLocation(),
        # Text keeps the overlay valid after its references are emptied; the
        # media-sticker form passes text="" and lives on its references alone.
        creation=OverlayCreation(
            text=text,
            prompt=prompt,
            reference_version_ids=list(reference_version_ids or []),
        ),
        render_source=(
            SourceVersionRenderSource(
                version_id=render_source_version_id,
                source_in_tick=0,
                source_out_tick=1000,
            )
            if render_source_version_id
            else None
        ),
    )


def _staged(base, *, files=(), versions=(), intelligence=(), elements=None):
    """The base Project plus the supplied asset records and main timeline."""
    project = base.project.model_copy(deep=True)
    for indexed in files:
        project.assets.files_by_id[indexed.file_id] = indexed
    for version in versions:
        project.assets.source_versions_by_id[version.version_id] = version
    for record in intelligence:
        project.assets.intelligence_versions_by_id[
            record.intelligence_version_id
        ] = record
    if elements is not None:
        main = project.timelines.items["timeline:main"]
        project.timelines.items["timeline:main"] = main.model_copy(
            update={
                "elements_by_id": {
                    element.element_id: element for element in elements
                },
            },
        )
    return project


def _publish_project(store, base, project):
    """CAS-write ``project`` as the next generation and return its snapshot."""
    candidate = project.model_copy(
        update={
            "generation": base.project.generation + 1,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    return store.replace(candidate.project_id, candidate, base.etag)


def _digital_human_project(tmp_path):
    """One live S2V Element plus its portrait, drive audio and a spare."""
    store, base = _deletion_store(tmp_path)
    portrait = _publish(
        store,
        "file-portrait",
        "assets/sources/portrait/version-1/original.png",
        PORTRAIT_BYTES,
        media_type="image/png",
    )
    drive = _publish(
        store,
        "file-drive",
        "assets/sources/drive/version-1/original.wav",
        DRIVE_AUDIO_BYTES,
        media_type="audio/wav",
    )
    spare = _publish(
        store,
        "file-spare",
        "assets/sources/spare/version-1/original.mp4",
        CLIP_BYTES,
        media_type="video/mp4",
    )
    versions = [
        _version(
            version_id="version-portrait",
            file_id="file-portrait",
            checksum=portrait.sha256,
            media_kind="image",
            media_type="image/png",
        ),
        _version(
            version_id="version-drive",
            file_id="file-drive",
            checksum=drive.sha256,
            media_kind="audio",
            media_type="audio/wav",
            duration_seconds=3,
        ),
        _version(
            version_id="version-spare",
            file_id="file-spare",
            checksum=spare.sha256,
            media_kind="video",
            media_type="video/mp4",
            duration_seconds=10,
        ),
    ]
    project = _staged(
        base,
        files=[portrait, drive, spare],
        versions=versions,
        elements=[
            _s2v_element(
                "el-s2v-1",
                portrait_version_id="version-portrait",
                audio_version_id="version-drive",
            ),
        ],
    )
    base = _publish_project(store, base, project)
    return (
        store,
        base,
        {
            "version-portrait": portrait,
            "version-drive": drive,
            "version-spare": spare,
        },
    )


def test_s2v_portrait_reference_blocks_asset_deletion(tmp_path):
    # wan2.2-s2v reads the portrait straight from this exact source version:
    # the file is never copied into an owned artifact, so an unchecked delete
    # would leave an active digital-human shot pointing at a missing file.
    store, _, files = _digital_human_project(tmp_path)
    root = store.project_root(DELETION_PROJECT_ID)
    portrait_path = root / files["version-portrait"].relative_uri
    assert portrait_path.is_file()

    with pytest.raises(
        ConflictError,
        match="s2v-portrait:el-s2v-1",
    ) as caught:
        store.remove_source_asset_version(
            DELETION_PROJECT_ID,
            "version-portrait",
        )
    # The machine-readable half lets the UI name the shot instead of
    # surfacing this English sentence with internal ids.
    assert caught.value.code == "ASSET_IN_USE"
    assert [
        reference["refKind"]
        for reference in caught.value.details["timelineReferences"]
    ] == ["s2v-portrait"]

    after = store.read(DELETION_PROJECT_ID).project
    assert "version-portrait" in after.assets.source_versions_by_id
    assert "file-portrait" in after.assets.files_by_id
    assert portrait_path.is_file()


def test_s2v_drive_audio_reference_blocks_asset_deletion(tmp_path):
    # Portrait and drive audio are independent inputs, so each one has to
    # block on its own rather than sharing one elif branch.
    store, _, files = _digital_human_project(tmp_path)
    root = store.project_root(DELETION_PROJECT_ID)
    drive_path = root / files["version-drive"].relative_uri

    with pytest.raises(
        ConflictError,
        match="s2v-drive-audio:el-s2v-1",
    ) as caught:
        store.remove_source_asset_version(
            DELETION_PROJECT_ID,
            "version-drive",
        )
    assert caught.value.code == "ASSET_IN_USE"
    assert [
        reference["refKind"]
        for reference in caught.value.details["timelineReferences"]
    ] == ["s2v-drive-audio"]

    after = store.read(DELETION_PROJECT_ID).project
    assert "version-drive" in after.assets.source_versions_by_id
    assert "file-drive" in after.assets.files_by_id
    assert drive_path.is_file()

    # Control: an unreferenced version of the same project still deletes.
    store.remove_source_asset_version(DELETION_PROJECT_ID, "version-spare")
    final = store.read(DELETION_PROJECT_ID).project
    assert "version-spare" not in final.assets.source_versions_by_id
    assert not (root / files["version-spare"].relative_uri).exists()


def test_snapshot_only_reference_blocks_asset_deletion(tmp_path):
    # A snapshot freezes the timeline/element objects only, so its
    # render_source still points at this source version and its on-disk
    # bytes. Skipping snapshot timelines made the file deletable while the
    # rollback history was permanently corrupted.
    store, base = _deletion_store(tmp_path)
    clip = _publish(
        store,
        "file-clip",
        "assets/sources/clip/version-1/original.mp4",
        CLIP_BYTES,
        media_type="video/mp4",
    )
    live = _staged(
        base,
        files=[clip],
        versions=[
            _version(
                version_id="version-clip",
                file_id="file-clip",
                checksum=clip.sha256,
                media_kind="video",
                media_type="video/mp4",
                duration_seconds=10,
            ),
        ],
        elements=[_edit_element("el-edit-1", "version-clip")],
    )
    base = _publish_project(store, base, live)

    # Mint the snapshot the way a real rollback commit does, then drop the
    # element from the live timeline: only the frozen copy references it.
    base_data = live.model_dump(mode="json")
    candidate_data = copy.deepcopy(base_data)
    candidate_data["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ] = {}
    assert auto_snapshot_timelines(base_data, candidate_data)
    snapshot_id = next(
        tid
        for tid in candidate_data["timelines"]["order"]
        if tid.startswith("snapshot:")
    )
    base = _publish_project(
        store,
        base,
        Project.model_validate(candidate_data),
    )
    clip_path = store.project_root(DELETION_PROJECT_ID) / clip.relative_uri
    assert clip_path.is_file()

    with pytest.raises(ConflictError) as caught:
        store.remove_source_asset_version(DELETION_PROJECT_ID, "version-clip")
    # The conflict names the snapshot timeline so the block is diagnosable.
    assert f"{snapshot_id}/render-source:" in str(caught.value)
    assert caught.value.code == "ASSET_IN_USE"
    snapshot_ref = next(
        reference
        for reference in caught.value.details["timelineReferences"]
        if reference["isSnapshot"]
    )
    assert snapshot_ref["timelineId"] == snapshot_id
    # An Edit Element cannot render without its source range at all, so even
    # a force delete leaves this reference in place.
    assert snapshot_ref["detachable"] is False

    # Rolling the snapshot back onto the live timeline must keep working,
    # and that is exactly why the bytes have to survive: the restored
    # Element resolves its render_source against this very version.
    snapshot = base.project.timelines.items[snapshot_id]
    restored = base.project.model_copy(deep=True)
    live_elements = {}
    for element_id, element in snapshot.elements_by_id.items():
        live_id = element_id.removeprefix(f"{snapshot_id}:")
        live_elements[live_id] = element.model_copy(
            update={"element_id": live_id},
        )
    restored.timelines.items["timeline:main"] = snapshot.model_copy(
        update={
            "timeline_id": "timeline:main",
            "elements_by_id": live_elements,
        },
    )
    base = _publish_project(store, base, restored)
    assert (
        "el-edit-1"
        in base.project.timelines.items["timeline:main"].elements_by_id
    )
    with pytest.raises(ConflictError) as caught:
        store.remove_source_asset_version(DELETION_PROJECT_ID, "version-clip")
    assert "render-source:el-edit-1" in str(caught.value)
    assert clip_path.is_file()


def _i2v_project_with_snapshot(tmp_path):
    """Live i2v Element plus an auto snapshot freezing the same first frame."""
    store, base = _deletion_store(tmp_path)
    frame = _publish(
        store,
        "file-frame",
        "assets/sources/frame/version-1/original.png",
        PORTRAIT_BYTES,
        media_type="image/png",
    )
    project = _staged(
        base,
        files=[frame],
        versions=[
            _version(
                version_id="version-frame",
                file_id="file-frame",
                checksum=frame.sha256,
                media_kind="image",
                media_type="image/png",
            ),
        ],
        elements=[
            _i2v_element(
                "el-i2v-1",
                first_frame_version_id="version-frame",
                label="镜头一｜风雪定场",
            ),
        ],
    )
    base = _publish_project(store, base, project)
    # Freeze the timeline the way a real Element edit does: the snapshot keeps
    # the pre-change Element while the modified live one survives beside it.
    base_data = project.model_dump(mode="json")
    candidate_data = copy.deepcopy(base_data)
    candidate_data["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "el-i2v-1"
    ]["label"] = "镜头一｜风雪定场（修订）"
    assert auto_snapshot_timelines(base_data, candidate_data)
    snapshot_id = next(
        tid
        for tid in candidate_data["timelines"]["order"]
        if tid.startswith("snapshot:")
    )
    base = _publish_project(
        store,
        base,
        Project.model_validate(candidate_data),
    )
    return store, base, frame, snapshot_id


def test_force_delete_detaches_live_and_snapshot_references(tmp_path):
    # A snapshot used to pin an asset forever (nothing deletes snapshots), so
    # force has to clear the frozen pointer too: leaving it would keep the
    # bytes alive for a history entry nobody can restore the file for.
    store, base, frame, snapshot_id = _i2v_project_with_snapshot(tmp_path)
    root = store.project_root(DELETION_PROJECT_ID)
    frame_path = root / frame.relative_uri
    assert frame_path.is_file()
    assert (
        derive_work_graph(base.project).by_id["video:el-i2v-1"].status
        is WorkNodeStatus.READY
    )

    with pytest.raises(SourceAssetInUseError) as caught:
        store.remove_source_asset_version(DELETION_PROJECT_ID, "version-frame")
    references = caught.value.details["timelineReferences"]
    assert sorted(
        (reference["refKind"], reference["isSnapshot"])
        for reference in references
    ) == [
        ("i2v-first-frame", False),
        ("i2v-first-frame", True),
    ]
    assert all(reference["detachable"] for reference in references)
    # The live record carries the human name the UI shows instead of an id.
    assert (
        next(
            reference
            for reference in references
            if not reference["isSnapshot"]
        )["elementLabel"]
        == "镜头一｜风雪定场（修订）"
    )

    snapshot = store.remove_source_asset_version(
        DELETION_PROJECT_ID,
        "version-frame",
        force=True,
    )

    after = snapshot.project
    assert "version-frame" not in after.assets.source_versions_by_id
    assert "file-frame" not in after.assets.files_by_id
    assert not frame_path.exists()
    for timeline_id, element_id in (
        ("timeline:main", "el-i2v-1"),
        (snapshot_id, f"{snapshot_id}:el-i2v-1"),
    ):
        element = after.timelines.items[timeline_id].elements_by_id[element_id]
        # Identity untouched, only the input pointer cleared.
        assert element.element_id == element_id
        assert element.creation.first_frame_version_id is None
    # The shot now reads as "needs a first frame" rather than keeping a live
    # input the graph would happily reuse for another render.
    node = derive_work_graph(after).by_id["video:el-i2v-1"]
    assert node.status is WorkNodeStatus.GATED
    assert node.missing == ("first_frame_version_id 缺失",)


def test_force_delete_refuses_required_audio_reference(tmp_path):
    # ``AudioCreation.source_asset_version_id`` is a required EntityId and an
    # Edit Element's render_source must stay a source range: half-clearing
    # those would persist a Project the model itself rejects, so force keeps
    # refusing and the Element has to go first.
    store, base = _deletion_store(tmp_path)
    song = _publish(
        store,
        "file-song",
        "assets/sources/song/version-1/original.wav",
        DRIVE_AUDIO_BYTES,
        media_type="audio/wav",
    )
    project = _staged(
        base,
        files=[song],
        versions=[
            _version(
                version_id="version-song",
                file_id="file-song",
                checksum=song.sha256,
                media_kind="audio",
                media_type="audio/wav",
                duration_seconds=3,
            ),
        ],
        elements=[_audio_element("el-audio-1", "version-song")],
    )
    before = _publish_project(store, base, project)
    song_path = store.project_root(DELETION_PROJECT_ID) / song.relative_uri

    with pytest.raises(SourceAssetInUseError) as caught:
        store.remove_source_asset_version(
            DELETION_PROJECT_ID,
            "version-song",
            force=True,
        )

    references = caught.value.details["timelineReferences"]
    assert sorted(reference["refKind"] for reference in references) == [
        "audio-source",
        "render-source",
    ]
    assert all(not reference["detachable"] for reference in references)
    # An unlabelled Element falls back to its id so the list never goes blank.
    assert {reference["elementLabel"] for reference in references} == {
        "el-audio-1",
    }

    after = store.read(DELETION_PROJECT_ID)
    assert after.etag == before.etag
    assert after.generation == before.generation
    assert "version-song" in after.project.assets.source_versions_by_id
    assert song_path.is_file()


def test_force_delete_detaches_render_source_and_r2v_refs(tmp_path):
    # Every detachable shape in one pass, and a surviving sibling version in
    # the same lists to prove the clear is per-reference, not per-field.
    store, base = _deletion_store(tmp_path)
    dropped = _publish(
        store,
        "file-dropped",
        "assets/sources/dropped/version-1/original.png",
        PORTRAIT_BYTES,
        media_type="image/png",
    )
    survivor = _publish(
        store,
        "file-survivor",
        "assets/sources/survivor/version-1/original.png",
        CLIP_BYTES,
        media_type="image/png",
    )
    project = _staged(
        base,
        files=[dropped, survivor],
        versions=[
            _version(
                version_id="version-dropped",
                file_id="file-dropped",
                checksum=dropped.sha256,
                media_kind="image",
                media_type="image/png",
            ),
            _version(
                version_id="version-survivor",
                file_id="file-survivor",
                checksum=survivor.sha256,
                media_kind="image",
                media_type="image/png",
            ),
        ],
        elements=[
            _r2v_element(
                "el-r2v-1",
                storyboard_version_ids=[
                    "version-dropped",
                    "version-survivor",
                ],
                video_version_ids=["version-dropped"],
            ),
            _overlay_element(
                "el-overlay-1",
                reference_version_ids=["version-dropped"],
                render_source_version_id="version-dropped",
            ),
        ],
    )
    _publish_project(store, base, project)
    dropped_path = (
        store.project_root(DELETION_PROJECT_ID) / dropped.relative_uri
    )

    store.remove_source_asset_version(
        DELETION_PROJECT_ID,
        "version-dropped",
        force=True,
    )

    after = store.read(DELETION_PROJECT_ID).project
    assert "version-dropped" not in after.assets.source_versions_by_id
    assert not dropped_path.exists()
    r2v = after.timelines.items["timeline:main"].elements_by_id["el-r2v-1"]
    assert r2v.creation.storyboard_reference_version_ids == [
        "version-survivor",
    ]
    assert r2v.creation.video_reference_version_ids == []
    overlay = after.timelines.items["timeline:main"].elements_by_id[
        "el-overlay-1"
    ]
    assert overlay.creation.reference_version_ids == []
    assert overlay.render_source is None
    assert "version-survivor" in after.assets.source_versions_by_id


def test_force_delete_refuses_the_only_payload_of_a_text_free_overlay(
    tmp_path,
):
    # A media sticker is declared valid by holding nothing but reference
    # versions: clearing this one would leave an OverlayCreation its own
    # validator rejects, so the delete must stay refused (and retryable by
    # deleting the Element) instead of turning into an unpersistable project.
    store, base = _deletion_store(tmp_path)
    sticker = _publish(
        store,
        "file-sticker",
        "assets/sources/sticker/version-1/original.png",
        PORTRAIT_BYTES,
        media_type="image/png",
    )
    project = _staged(
        base,
        files=[sticker],
        versions=[
            _version(
                version_id="version-sticker",
                file_id="file-sticker",
                checksum=sticker.sha256,
                media_kind="image",
                media_type="image/png",
            ),
        ],
        elements=[
            _overlay_element(
                "el-sticker-1",
                reference_version_ids=["version-sticker"],
                render_source_version_id="version-sticker",
                text="",
            ),
        ],
    )
    before = _publish_project(store, base, project)
    sticker_path = (
        store.project_root(DELETION_PROJECT_ID) / sticker.relative_uri
    )

    with pytest.raises(SourceAssetInUseError) as caught:
        store.remove_source_asset_version(
            DELETION_PROJECT_ID,
            "version-sticker",
            force=True,
        )

    detachable = {
        reference["refKind"]: reference["detachable"]
        for reference in caught.value.details["timelineReferences"]
    }
    assert detachable == {"overlay-ref": False, "render-source": False}

    after = store.read(DELETION_PROJECT_ID)
    assert after.etag == before.etag
    assert after.generation == before.generation
    assert "version-sticker" in after.project.assets.source_versions_by_id
    assert sticker_path.is_file()


def test_force_delete_detaches_an_overlay_that_keeps_its_own_payload(tmp_path):
    # The sibling of the case above: a decoration with a design brief left is
    # still a valid OverlayCreation once the reference goes, so force may clear
    # it. Only the pointer to the deleted bytes is touched.
    store, base = _deletion_store(tmp_path)
    sticker = _publish(
        store,
        "file-sticker",
        "assets/sources/sticker/version-1/original.png",
        PORTRAIT_BYTES,
        media_type="image/png",
    )
    project = _staged(
        base,
        files=[sticker],
        versions=[
            _version(
                version_id="version-sticker",
                file_id="file-sticker",
                checksum=sticker.sha256,
                media_kind="image",
                media_type="image/png",
            ),
        ],
        elements=[
            _overlay_element(
                "el-sticker-1",
                reference_version_ids=["version-sticker"],
                render_source_version_id="version-sticker",
                text="",
                prompt="雪花飘落",
            ),
        ],
    )
    _publish_project(store, base, project)

    store.remove_source_asset_version(
        DELETION_PROJECT_ID,
        "version-sticker",
        force=True,
    )

    after = store.read(DELETION_PROJECT_ID).project
    assert "version-sticker" not in after.assets.source_versions_by_id
    assert not (
        store.project_root(DELETION_PROJECT_ID) / sticker.relative_uri
    ).exists()
    overlay = after.timelines.items["timeline:main"].elements_by_id[
        "el-sticker-1"
    ]
    assert overlay.creation.reference_version_ids == []
    assert overlay.creation.prompt == "雪花飘落"
    assert overlay.render_source is None


def test_deleting_analyzed_asset_removes_intelligence_file(tmp_path):
    # Step 2 of the detach drops every intelligence version built from the
    # deleted source, but only the source/thumbnail/model file ids were
    # collected, so the analysis payload stayed on disk and in the index with
    # no record left to reach it (the unindexed-file sweep cannot see it).
    store, base = _deletion_store(tmp_path)
    clip = _publish(
        store,
        "file-clip",
        "assets/sources/clip/version-1/original.mp4",
        CLIP_BYTES,
        media_type="video/mp4",
    )
    analysis = _publish(
        store,
        "file-analysis",
        "assets/intelligence/clip/version-1/analysis.json",
        INTELLIGENCE_BYTES,
        kind="source_intelligence",
        media_type="application/json",
    )
    project = _staged(
        base,
        files=[clip, analysis],
        versions=[
            _version(
                version_id="version-clip",
                file_id="file-clip",
                checksum=clip.sha256,
                media_kind="video",
                media_type="video/mp4",
                duration_seconds=10,
            ),
        ],
        intelligence=[
            SourceIntelligenceVersion(
                intelligence_version_id="intel-clip",
                source_asset_version_id="version-clip",
                file_id="file-analysis",
                source_checksum=clip.sha256,
                coverage={"transcript": "complete"},
                created_at=NOW,
            ),
        ],
        elements=[],
    )
    _publish_project(store, base, project)
    root = store.project_root(DELETION_PROJECT_ID)
    assert (root / analysis.relative_uri).is_file()

    store.remove_source_asset_version(DELETION_PROJECT_ID, "version-clip")

    after = store.read(DELETION_PROJECT_ID).project
    assert after.assets.intelligence_versions_by_id == {}
    assert "file-analysis" not in after.assets.files_by_id
    assert not (root / analysis.relative_uri).exists()
    assert not (root / clip.relative_uri).exists()


def test_shared_intelligence_file_survives_other_analysed_versions(tmp_path):
    # Control for the reclaim: a file id still referenced by a surviving
    # intelligence version must keep both its index entry and its bytes.
    store, base = _deletion_store(tmp_path)
    first = _publish(
        store,
        "file-clip-1",
        "assets/sources/clip-1/version-1/original.mp4",
        CLIP_BYTES,
        media_type="video/mp4",
    )
    second = _publish(
        store,
        "file-clip-2",
        "assets/sources/clip-2/version-1/original.mp4",
        CLIP_BYTES,
        media_type="video/mp4",
    )
    analysis = _publish(
        store,
        "file-analysis",
        "assets/intelligence/shared/analysis.json",
        INTELLIGENCE_BYTES,
        kind="source_intelligence",
        media_type="application/json",
    )

    def versioned(version_id: str, file_id: str, checksum: str):
        return _version(
            version_id=version_id,
            file_id=file_id,
            checksum=checksum,
            media_kind="video",
            media_type="video/mp4",
            duration_seconds=10,
        )

    project = _staged(
        base,
        files=[first, second, analysis],
        versions=[
            versioned("version-clip-1", "file-clip-1", first.sha256),
            versioned("version-clip-2", "file-clip-2", second.sha256),
        ],
        intelligence=[
            SourceIntelligenceVersion(
                intelligence_version_id="intel-clip-1",
                source_asset_version_id="version-clip-1",
                file_id="file-analysis",
                source_checksum=first.sha256,
                created_at=NOW,
            ),
            SourceIntelligenceVersion(
                intelligence_version_id="intel-clip-2",
                source_asset_version_id="version-clip-2",
                file_id="file-analysis",
                source_checksum=second.sha256,
                created_at=NOW,
            ),
        ],
        elements=[],
    )
    _publish_project(store, base, project)
    root = store.project_root(DELETION_PROJECT_ID)

    store.remove_source_asset_version(DELETION_PROJECT_ID, "version-clip-1")

    after = store.read(DELETION_PROJECT_ID).project
    assert set(after.assets.intelligence_versions_by_id) == {"intel-clip-2"}
    assert "file-analysis" in after.assets.files_by_id
    assert (root / analysis.relative_uri).is_file()
    assert not (root / first.relative_uri).exists()


def test_force_delete_marks_final_video_and_element_outputs_stale(
    tmp_path,
) -> None:
    """Force-clearing timeline references must invalidate rendered outputs.

    Detaching a source version from an element changes the creative material,
    so the previously selected final_video and element-level renders are stale
    and ``derive_work_graph`` must report compose as not-DONE.
    """
    store, base = _deletion_store(tmp_path)
    frame = _publish(
        store,
        "file-frame",
        "assets/sources/frame/version-1/original.png",
        PORTRAIT_BYTES,
        media_type="image/png",
    )
    project = _staged(
        base,
        files=[frame],
        versions=[
            _version(
                version_id="version-frame",
                file_id="file-frame",
                checksum=frame.sha256,
                media_kind="image",
                media_type="image/png",
            ),
        ],
        elements=[
            _i2v_element(
                "el-i2v-1",
                first_frame_version_id="version-frame",
            ),
        ],
    )

    # Add artifact slots and versions that represent completed renders.
    final_slot = ArtifactSlot(
        slot_id="timeline:timeline:main:render",
        kind="final_video",
        owner_ref="timeline:timeline:main",
        version_ids=["final-v1"],
        selected_version_id="final-v1",
    )
    element_slot = ArtifactSlot(
        slot_id="element:el-i2v-1:video",
        kind="element_video",
        owner_ref="element:el-i2v-1",
        version_ids=["elem-v1"],
        selected_version_id="elem-v1",
    )
    final_version = ArtifactVersion(
        version_id="final-v1",
        slot_id="timeline:timeline:main:render",
        kind="final_video",
        owner_ref="timeline:timeline:main",
        name="最终成片",
        file_id="file-frame",
        checksum=frame.sha256,
        based_on_generation=0,
        stale=False,
        created_at=NOW,
    )
    element_version = ArtifactVersion(
        version_id="elem-v1",
        slot_id="element:el-i2v-1:video",
        kind="element_video",
        owner_ref="element:el-i2v-1",
        name="镜头视频",
        file_id="file-frame",
        checksum=frame.sha256,
        based_on_generation=0,
        stale=False,
        created_at=NOW,
    )
    project.assets.artifact_slots_by_id[final_slot.slot_id] = final_slot
    project.assets.artifact_slots_by_id[element_slot.slot_id] = element_slot
    project.assets.artifact_versions_by_id[
        final_version.version_id
    ] = final_version
    project.assets.artifact_versions_by_id[
        element_version.version_id
    ] = element_version

    base = _publish_project(store, base, project)

    # Sanity: both renders start fresh.
    after_read = store.read(DELETION_PROJECT_ID).project
    assert after_read.assets.artifact_versions_by_id["final-v1"].stale is False
    assert after_read.assets.artifact_versions_by_id["elem-v1"].stale is False

    # Force delete detaches the reference and must mark renders stale.
    snapshot = store.remove_source_asset_version(
        DELETION_PROJECT_ID,
        "version-frame",
        force=True,
    )
    after = snapshot.project

    assert "version-frame" not in after.assets.source_versions_by_id
    final_after = after.assets.artifact_versions_by_id["final-v1"]
    assert final_after.stale is True
    assert final_after.stale_reason == "素材已删除，需要重新生成"
    elem_after = after.assets.artifact_versions_by_id["elem-v1"]
    assert elem_after.stale is True
    assert elem_after.stale_reason == "素材已删除，需要重新生成"

    # A storyboard slot (not final_video / element_video) stays untouched.
    storyboard_slot = ArtifactSlot(
        slot_id="element:el-i2v-1:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:el-i2v-1",
        version_ids=["sb-v1"],
        selected_version_id="sb-v1",
    )
    storyboard_version = ArtifactVersion(
        version_id="sb-v1",
        slot_id="element:el-i2v-1:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:el-i2v-1",
        name="分镜图",
        file_id="file-frame",
        checksum=frame.sha256,
        based_on_generation=0,
        stale=False,
        created_at=NOW,
    )
    after.assets.artifact_slots_by_id[
        storyboard_slot.slot_id
    ] = storyboard_slot
    after.assets.artifact_versions_by_id[
        storyboard_version.version_id
    ] = storyboard_version
    # Re-publish so the store accepts the addition, then force-delete
    # another version to confirm staleness is still applied.
    base2 = _publish_project(store, snapshot, after)
    frame2 = _publish(
        store,
        "file-frame2",
        "assets/sources/frame2/version-1/original.png",
        PORTRAIT_BYTES,
        media_type="image/png",
    )
    project2 = _staged(
        base2,
        files=[frame2],
        versions=[
            _version(
                version_id="version-frame2",
                file_id="file-frame2",
                checksum=frame2.sha256,
                media_kind="image",
                media_type="image/png",
            ),
        ],
        elements=[
            _i2v_element(
                "el-i2v-2",
                first_frame_version_id="version-frame2",
            ),
        ],
    )
    # Add a second element's slots.
    slot2 = ArtifactSlot(
        slot_id="element:el-i2v-2:video",
        kind="element_video",
        owner_ref="element:el-i2v-2",
        version_ids=["elem2-v1"],
        selected_version_id="elem2-v1",
    )
    ver2 = ArtifactVersion(
        version_id="elem2-v1",
        slot_id="element:el-i2v-2:video",
        kind="element_video",
        owner_ref="element:el-i2v-2",
        name="镜头视频2",
        file_id="file-frame2",
        checksum=frame2.sha256,
        based_on_generation=0,
        stale=False,
        created_at=NOW,
    )
    project2.assets.artifact_slots_by_id[slot2.slot_id] = slot2
    project2.assets.artifact_versions_by_id[ver2.version_id] = ver2
    base2 = _publish_project(store, base2, project2)

    # Force-delete the second frame.
    snapshot2 = store.remove_source_asset_version(
        DELETION_PROJECT_ID,
        "version-frame2",
        force=True,
    )
    after2 = snapshot2.project

    # The second element's video is stale, the first element's is untouched.
    assert after2.assets.artifact_versions_by_id["elem2-v1"].stale is True
    # The storyboard slot (not final_video / element_video) was not invalidated.
    assert after2.assets.artifact_versions_by_id["sb-v1"].stale is False
