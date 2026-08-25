# -*- coding: utf-8 -*-
"""Shared construction and runtime-record helpers for project_files tests."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
import hashlib

from services.media_files.local_execution import (
    LocalMediaExecutionSpec,
    _render_element_total,
)
from services.project_files.assets import AssetFileStore
from services.project_files.commit import (
    ProjectCommitBoundary,
    ProjectCommitJournal,
)
from services.project_files.models import (
    EditCreation,
    ElementLocation,
    EntityCollection,
    IndexedFile,
    Project,
    R2VCreation,
    Shot,
    SourceVersionRenderSource,
    TimelineElement,
    TimelineSpan,
)
from services.project_files.recovery import ProjectCommitRecoveryCoordinator
from services.project_files.store import ProjectStore
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.models import (
    ChangeOrigin,
    ChangeRoundRecord,
    ReviewBoundary,
    ReviewPolicy,
    ReviewRecord,
    RuntimeChangeSet,
    RuntimeProjectState,
)

# pylint: disable=no-name-in-module
from utils.paths import unique_task_work_path

# pylint: enable=no-name-in-module


PROJECT_ID = "project-1"


def make_store(tmp_path, **project_fields):
    """Create a store plus the canonical ``project-1`` base snapshot."""
    store = ProjectStore(tmp_path.resolve())
    fields = {"project_id": PROJECT_ID, "name": "Initial", **project_fields}
    return store, store.create(Project.new(**fields))


def runtime_root(store, project_id=PROJECT_ID):
    return store.project_root(project_id) / "runtime"


def transaction_root(store, transaction_id):
    return runtime_root(store) / "transactions" / transaction_id


def journal_store(store, transaction_id):
    return AtomicJsonRecordStore(
        transaction_root(store, transaction_id) / "journal.json",
        ProjectCommitJournal,
    )


def read_journal(store, transaction_id):
    return journal_store(store, transaction_id).read()


def round_store(store, round_id):
    return AtomicJsonRecordStore(
        runtime_root(store) / "change-rounds" / round_id / "round.json",
        ChangeRoundRecord,
    )


def read_round(store, round_id):
    return round_store(store, round_id).read()


def read_changeset(store, round_id):
    return AtomicJsonRecordStore(
        runtime_root(store) / "change-rounds" / round_id / "changeset.json",
        RuntimeChangeSet,
    ).read()


def read_state(store):
    return AtomicJsonRecordStore(
        runtime_root(store) / "state.json",
        RuntimeProjectState,
    ).read()


def read_review(store, round_id):
    return AtomicJsonRecordStore(
        runtime_root(store) / "reviews" / f"review-{round_id}" / "review.json",
        ReviewRecord,
    ).read()


def recover(store):
    return ProjectCommitRecoveryCoordinator(store).recover_project(PROJECT_ID)


def review_boundary(base, *, seq=2, request_id=None, run_id=None):
    return ReviewBoundary(
        request_message_seq=seq,
        request_id=request_id or f"request-{seq}",
        interrupted_run_id=run_id or f"run-{seq - 1}",
        accepted_generation=base.generation,
        accepted_etag=base.etag,
    )


def review_commit_kwargs(boundary):
    """Commit metadata for an AgentDock interrupt gated behind review."""
    return {
        "origin": "agentdock_interrupt",
        "review_policy": "require_review",
        "review_boundary": boundary,
        "caused_by_request_id": boundary.request_id,
        "caused_by_message_seq": boundary.request_message_seq,
    }


def make_pending_review(tmp_path):
    """A committed AgentDock change (name+description) pending review."""
    store, base = make_store(tmp_path, name="Before", description="old")
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "After"
    candidate["description"] = "new"
    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        round_id="round-2",
        **review_commit_kwargs(review_boundary(base)),
    )
    return store, base, result


def commit_indexed_file(
    store,
    base,
    *,
    file_id,
    kind,
    content,
    media_type,
    relative_uri,
    staging_id,
):
    """Publish ``content`` and commit it as an IndexedFile on project-1."""
    asset_store = AssetFileStore(store.project_root(PROJECT_ID))
    published = asset_store.publish(
        asset_store.stage_bytes(content, staging_id=staging_id),
        relative_uri,
    )
    candidate = base.project.model_copy(deep=True)
    candidate.assets.files_by_id[file_id] = IndexedFile(
        file_id=file_id,
        kind=kind,
        relative_uri=published.relative_uri,
        sha256=published.sha256,
        size_bytes=published.size_bytes,
        media_type=media_type,
        created_at=datetime.now(timezone.utc),
    )
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate.model_dump(mode="json"),
        origin="runtime_task",
    )


# ── timeline-element POC doubles and builders ────────────────────────────────

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"timeline-storyboard" * 16
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"timeline-video" * 64


class FakeImageProvider:
    async def generate(self, **_kwargs):
        return {"content": PNG_BYTES, "media_type": "image/png"}


class FakeR2VProvider:
    async def submit(self, **_kwargs) -> str:
        return "provider-task-1"

    async def poll(self, provider_task_id: str):
        path = unique_task_work_path(
            "video",
            ".mp4",
            prefix="timeline-provider-",
        )
        path.write_bytes(MP4_BYTES)
        return {
            "task_id": provider_task_id,
            "status": "SUCCEEDED",
            "result_url": path.resolve().as_uri(),
            "media_type": "video/mp4",
            "durationSeconds": 4,
        }


class RecordingLocalRunner:
    def __init__(self) -> None:
        self.calls: list[LocalMediaExecutionSpec] = []

    async def render(self, spec: LocalMediaExecutionSpec):
        self.calls.append(spec)
        if spec.on_element_done is not None:
            total_elements = _render_element_total(spec.inputs)
            spec.on_element_done(total_elements, total_elements)
        spec.output_path.write_bytes(MP4_BYTES + spec.command.value.encode())
        return {
            "media_type": "video/mp4",
            "duration_seconds": spec.expected_duration_seconds,
        }


def r2v_element(element_id: str, *, start: int, duration: int = 4_000):
    shot = Shot(
        shot_id=f"{element_id}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=duration / 1_000,
    )
    return TimelineElement(
        element_id=element_id,
        label="猫追老鼠",
        span=TimelineSpan(start_tick=start, duration_tick=duration),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            video_prompt="动画，猫从左向右追逐老鼠，动作连续",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )


def install_edit_source(services) -> None:
    """Publish a 10s source video and index it into ``edit-project``."""
    root = services.projects.project_root("edit-project")
    content = b"source-video"
    checksum = hashlib.sha256(content).hexdigest()
    relative_uri = "assets/sources/cat/source.mp4"
    store = AssetFileStore(root)
    store.publish(
        store.stage_bytes(content, staging_id="source"),
        relative_uri,
        expected_sha256=checksum,
        expected_size_bytes=len(content),
    )
    base = services.projects.read("edit-project")
    candidate = base.project.model_dump(mode="json")
    candidate["assets"]["files_by_id"]["source-file"] = {
        "file_id": "source-file",
        "kind": "source_original",
        "relative_uri": relative_uri,
        "sha256": checksum,
        "size_bytes": len(content),
        "media_type": "video/mp4",
        "created_at": datetime.now(UTC).isoformat(),
    }
    candidate["assets"]["source_versions_by_id"]["source-version"] = {
        "version_id": "source-version",
        "logical_asset_id": "cat-source",
        "name": "cat.mp4",
        "file_id": "source-file",
        "checksum": checksum,
        "media_kind": "video",
        "media_type": "video/mp4",
        "duration_seconds": 10,
        "created_at": datetime.now(UTC).isoformat(),
    }
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )


# ── agent-tools advisory builders ────────────────────────────────────────────


def timeline_project_with(element: TimelineElement, *, edit_plan=None):
    """A ``project-1`` whose main timeline holds exactly ``element``."""
    project = Project.new(project_id=PROJECT_ID, name="Advisory")
    timeline = project.timelines.items["timeline:main"].model_copy(
        update={
            "elements_by_id": {element.element_id: element},
            "edit_plan": edit_plan,
        },
    )
    patched = project.model_copy(deep=True)
    patched.timelines.items["timeline:main"] = timeline
    return patched


def edit_element():
    return TimelineElement(
        element_id="el-edit-1",
        span=TimelineSpan(start_tick=0, duration_tick=1000),
        location=ElementLocation(),
        creation=EditCreation(intent="pick"),
    )


def spoken_edit_element(*, in_tick: int, out_tick: int):
    return TimelineElement(
        element_id="el-edit-1",
        span=TimelineSpan(start_tick=0, duration_tick=out_tick - in_tick),
        location=ElementLocation(),
        creation=EditCreation(
            intent="pick",
            source_intelligence_version_id="intel-1",
        ),
        render_source=SourceVersionRenderSource(
            version_id="version-1",
            source_in_tick=in_tick,
            source_out_tick=out_tick,
        ),
    )
