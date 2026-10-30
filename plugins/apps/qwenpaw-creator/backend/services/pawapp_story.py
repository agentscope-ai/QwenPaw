# -*- coding: utf-8 -*-
"""Import agreed writing without invoking models or media providers."""

import asyncio
import hashlib

from pydantic import BaseModel, ConfigDict

from domain.enums import CreatorGoalStatus
from schemas.projects import ProjectCreateRequest
from services.project_files.assets import AssetAlreadyExists, AssetFileStore
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
)
from services.project_files.script_artifacts import (
    add_script_version,
    script_file_relative_uri,
)
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.models import utc_now
from services.runtime_files.path_safety import require_safe_runtime_segment
from services.story_package import (
    PrepareStoryInput,
    ReviseStoryInput,
    StoryPackage,
    StoryReceipt,
)

from qwenpaw.pawapp.tasks import ActionDescriptor, ActionResult, ProjectRef
from qwenpaw.pawapp.tasks.contracts import (
    TaskScope,
    TaskStoreError,
    content_digest,
)

APP_ID = "qwenpaw-creator"
STORY_SLOT = "story:main"
TIMELINE = "timeline:main"


class StoryOwner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: TaskScope
    submission_id: str
    initial_digest: str


class StoryImportReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    meaning: str
    result: dict | None = None


def owner_store(services, project_id):
    project_id = require_safe_runtime_segment(project_id, label="project_id")
    return AtomicJsonRecordStore(
        services.root / ".pawapp" / "story-projects" / f"{project_id}.json",
        StoryOwner,
    )


def require_story_owner(services, project_id, scope):
    owner = owner_store(services, project_id).read_or_none()
    if owner is None or owner.scope != scope:
        raise TaskStoreError("story_project_not_found")
    return owner


def story_version(project, revision=None):
    slot = project.assets.artifact_slots_by_id.get(STORY_SLOT)
    if slot is None:
        raise TaskStoreError("story_package_missing")
    if revision is None:
        version = project.assets.artifact_versions_by_id[
            slot.selected_version_id
        ]
    else:
        version = next(
            (
                project.assets.artifact_versions_by_id[vid]
                for vid in slot.version_ids
                if project.assets.artifact_versions_by_id[vid].metadata.get(
                    "story_revision",
                )
                == revision
            ),
            None,
        )
        if version is None:
            raise TaskStoreError("story_revision_not_found")
    return version


def read_story(services, snapshot, revision=None):
    version = story_version(snapshot.project, revision)
    indexed = snapshot.project.assets.files_by_id[version.file_id]
    files = AssetFileStore(
        services.projects.project_root(snapshot.project.project_id),
    )
    story = StoryPackage.model_validate_json(files.read_verified(indexed))
    if story.digest != version.metadata["story_digest"]:
        raise TaskStoreError("story_package_corrupt")
    return story


def _publish_file(files, indexed, content):
    staged = files.stage_bytes(content)
    try:
        files.publish(
            staged,
            indexed.relative_uri,
            expected_sha256=indexed.sha256,
            expected_size_bytes=len(content),
        )
    except AssetAlreadyExists:
        files.read_verified(indexed)


def _receipt(snapshot, version):
    return {
        "project_id": snapshot.project.project_id,
        "story_revision": version.metadata["story_revision"],
        "story_digest": version.metadata["story_digest"],
        "project_etag": snapshot.etag,
        "project_generation": snapshot.generation,
    }


def _recover_receipt(base, story, submission_id):
    slot = base.project.assets.artifact_slots_by_id.get(STORY_SLOT)
    if slot is None:
        return None
    for vid in slot.version_ids:
        version = base.project.assets.artifact_versions_by_id[vid]
        if version.metadata["story_revision"] != story.revision:
            continue
        if (
            version.metadata["story_digest"] != story.digest
            or version.metadata["submission_id"] != submission_id
        ):
            raise TaskStoreError("story_revision_conflict")
        if base.generation != version.based_on_generation + 1:
            raise TaskStoreError("story_receipt_recovery_conflict")
        return _receipt(base, version)
    return None


def _require_idle_project(services, project_id):
    # The caller holds the exclusive lifecycle lock. These snapshot reads
    # must not try to acquire a nested shared lifecycle lock.
    session = services.sessions.get_project_session_snapshot(project_id)
    if session.active_run_id:
        raise TaskStoreError("story_project_busy")
    if session.active_goal_id:
        goal = services.sessions.get_goal(project_id, session.active_goal_id)
        if goal.status not in {
            CreatorGoalStatus.COMPLETED,
            CreatorGoalStatus.CANCELLED,
            CreatorGoalStatus.FAILED,
        }:
            raise TaskStoreError("story_project_busy")


def _apply_story(services, base, story, submission_id):
    project_id = base.project.project_id
    working = base.project.model_copy(deep=True)
    timeline = working.timelines.items[TIMELINE]
    timeline.title = story.title
    timeline.synopsis = story.synopsis
    timeline.description = story.script_markdown
    timeline.planned_duration_seconds = story.duration_seconds
    working.settings.language = story.language
    working.settings.target_duration_seconds = story.duration_seconds
    working.settings.aspect_ratio = story.aspect_ratio
    working.settings.resolution = story.resolution
    working.strategy.creative_brief = story.logline
    working.strategy.audience = story.audience
    working.strategy.creative_direction = (
        f"Tone: {story.tone}\n"
        "Read the selected story:main artifact for the complete character "
        "bible, reference notes, constraints and decisions. Preserve "
        "the selected timeline script; propose story changes explicitly."
    )
    working.strategy.constraints = "\n".join(story.constraints)
    content = story.content()
    checksum = hashlib.sha256(content).hexdigest()
    file_id = f"file-story-{checksum}"
    indexed = IndexedFile(
        file_id=file_id,
        kind="artifact_payload",
        relative_uri=f"assets/artifacts/{file_id}.json",
        sha256=checksum,
        size_bytes=len(content),
        media_type="application/json",
        created_at=utc_now(),
    )
    files = AssetFileStore(services.projects.project_root(project_id))
    _publish_file(files, indexed, content)
    working.assets.files_by_id[file_id] = indexed
    version = ArtifactVersion(
        version_id=f"story-{checksum}",
        slot_id=STORY_SLOT,
        kind="story_package",
        owner_ref=f"timeline:{TIMELINE}",
        name=f"{story.title} · revision {story.revision}",
        file_id=file_id,
        checksum=checksum,
        based_on_generation=base.generation,
        created_at=utc_now(),
        metadata={
            "story_revision": story.revision,
            "story_digest": story.digest,
            "submission_id": submission_id,
        },
    )
    working.assets.artifact_versions_by_id[version.version_id] = version
    if STORY_SLOT not in working.assets.artifact_slots_by_id:
        working.assets.artifact_slots_by_id[STORY_SLOT] = ArtifactSlot(
            slot_id=STORY_SLOT,
            kind="story_package",
            owner_ref=f"timeline:{TIMELINE}",
        )
    new_slot = working.assets.artifact_slots_by_id[STORY_SLOT]
    new_slot.version_ids.append(version.version_id)
    new_slot.selected_version_id = version.version_id

    script = story.script_markdown.encode()
    script_hash = hashlib.sha256(script).hexdigest()
    script_id = f"file-script-{script_hash}"
    script_version = add_script_version(
        working,
        TIMELINE,
        story.script_markdown,
        file_id=script_id,
        checksum=script_hash,
        name=story.title,
        now=utc_now(),
        based_on_generation=base.generation,
        provenance_refs=[version.version_id],
        input_fingerprint=story.digest,
    )
    script_index = working.assets.files_by_id[script_version.file_id]
    assert script_index.relative_uri == script_file_relative_uri(
        script_version.file_id,
    )
    _publish_file(files, script_index, script)
    # Derive invalidation and preserve review history at commit.
    result = services.commits.commit(
        base=base,
        candidate=working.model_dump(mode="json"),
        origin="runtime_task",
        caused_by_request_id=submission_id,
        _lifecycle_lock_held=True,
    )
    services.poller.note_commit(result.snapshot)
    return _receipt(result.snapshot, version)


def import_story(services, scope, submission_id, inputs, *, revise=False):
    if scope.app_id != APP_ID:
        raise TaskStoreError("story_scope_mismatch")
    parsed = (
        ReviseStoryInput.model_validate(inputs)
        if revise
        else PrepareStoryInput.model_validate(inputs)
    )
    story = parsed.story
    safe_id = require_safe_runtime_segment(
        submission_id,
        label="submission_id",
    )
    receipts = AtomicJsonRecordStore(
        services.root / ".pawapp" / "story-imports" / f"{safe_id}.json",
        StoryImportReceipt,
    )
    meaning = content_digest(
        [scope.model_dump(mode="json"), inputs, revise],
    )
    receipts.try_create(StoryImportReceipt(meaning=meaning))
    receipt = receipts.read()
    if receipt.meaning != meaning:
        raise TaskStoreError("story_submission_conflict")
    if receipt.result is not None:
        return receipt.result, story
    if not revise and story.revision != 1:
        raise TaskStoreError("initial_story_revision_must_be_one")
    project_id = (
        parsed.project_id
        if revise
        else services.project_creation.project_id(submission_id)
    )
    if revise:
        require_story_owner(services, project_id, scope)
    else:
        owner = StoryOwner(
            scope=scope,
            submission_id=submission_id,
            initial_digest=story.digest,
        )
        store = owner_store(services, project_id)
        store.try_create(owner)
        if store.read() != owner:
            raise TaskStoreError("story_submission_conflict")
        services.project_creation.create(
            ProjectCreateRequest(
                clientRequestId=submission_id,
                name=f"{story.title} · {project_id[-8:]}",
                description=story.logline,
                scenario=story.scenario,
                productionStage="script",
                aspectRatio=story.aspect_ratio,
                resolution=story.resolution,
            ),
        )

    with services.projects.lifecycle_lock(project_id):
        base = services.projects.read(project_id)
        recovered = _recover_receipt(base, story, submission_id)
        if recovered is not None:
            receipts.write(
                StoryImportReceipt(meaning=meaning, result=recovered),
            )
            return recovered, story
        if revise:
            previous = read_story(services, base)
            if (
                base.etag != parsed.expected_project_etag
                or previous.digest != parsed.expected_story_digest
                or previous.story_id != story.story_id
                or story.revision != previous.revision + 1
            ):
                raise TaskStoreError("story_revision_conflict")
            _require_idle_project(services, project_id)

        result = _apply_story(services, base, story, submission_id)
        receipts.write(StoryImportReceipt(meaning=meaning, result=result))
        return result, story


def story_action_descriptor(*, revise=False):
    action_id = "revise-story" if revise else "prepare-production"
    model = ReviseStoryInput if revise else PrepareStoryInput
    return ActionDescriptor(
        app_id=APP_ID,
        action_id=action_id,
        summary=(
            "Import an agreed story revision into its Creator project; "
            "reject stale revisions or concurrent Creator edits."
            if revise
            else "Import the complete agreed story into a new Creator "
            "project, ready to open. Does not call models or generate media."
        ),
        guidance=(
            "Use the complete story package, never a summary of the agreed "
            "script. References are preserved as data, not fetched. "
            "Retain the returned project, revision, digest and ETag for "
            "produce-video or revise-story. A conflict requires reviewing "
            "the current project; never silently overwrite Creator edits."
        ),
        engagements=("delegated",),
        input_schema=model.model_json_schema(),
        result_schema=StoryReceipt.model_json_schema(),
        output_types=("text/plain", "qwenpaw:file"),
        permissions=(
            ("creator.project.read", "creator.project.write")
            if revise
            else ("creator.project.create", "creator.project.write")
        ),
        effects=("project_mutation",),
        adapter_ref=f"{APP_ID}.{action_id}.v1",
    )


def register_story_actions(app, services_factory):
    async def run(ctx, *, revise):
        try:
            receipt, story = await asyncio.to_thread(
                import_story,
                services_factory(),
                ctx.scope,
                ctx.submission_id,
                ctx.inputs,
                revise=revise,
            )
        except TaskStoreError as error:
            if error.code not in {
                "story_revision_conflict",
                "story_receipt_recovery_conflict",
                "story_project_busy",
            }:
                raise
            services = services_factory()
            project_id = (
                ctx.inputs["project_id"]
                if revise
                else services.project_creation.project_id(ctx.submission_id)
            )
            current = await asyncio.to_thread(
                services.projects.read,
                project_id,
            )
            await ctx.fail(
                "story-conflict",
                text=(
                    "The Creator project has changed or has active work. "
                    "Open it and review its current version; finish or cancel "
                    "active production before retrying."
                ),
                project=ProjectRef(
                    app_id=APP_ID,
                    project_id=project_id,
                    kind="creator-project",
                    revision=current.generation,
                ),
            )
        await ctx.publish(
            source_id=f"story-{story.digest}",
            name=f"{story.story_id}-r{story.revision}.json",
            media_type="application/json",
            content=story.content(),
        )
        await ctx.publish(
            source_id=f"script-{story.digest}",
            name=f"{story.story_id}-r{story.revision}.md",
            media_type="text/markdown",
            content=story.script_markdown.encode(),
        )
        return ActionResult(
            summary=(
                f"{story.title}: story revision {story.revision} "
                "is ready in Creator."
            ),
            data=receipt,
            project=ProjectRef(
                app_id=APP_ID,
                project_id=receipt["project_id"],
                kind="creator-project",
                revision=receipt["project_generation"],
            ),
        )

    @app.action(story_action_descriptor(), recovery="replay_safe")
    async def prepare_production(ctx):
        return await run(ctx, revise=False)

    @app.action(story_action_descriptor(revise=True), recovery="replay_safe")
    async def revise_story(ctx):
        return await run(ctx, revise=True)
