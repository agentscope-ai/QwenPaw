# -*- coding: utf-8 -*-
"""Writing handoff preserves source bytes and never performs media work."""

# pylint: disable=protected-access,redefined-outer-name

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from services.pawapp_story import (
    import_story,
    read_story,
    register_story_actions,
    story_version,
)
from services.pawapp_story_production import CreatorStoryProductionTaskAdapter
from services.project_files.assets import AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.story_package import StoryPackage
from qwenpaw.pawapp import PawApp
from qwenpaw.pawapp.artifacts import ArtifactStore
from qwenpaw.pawapp.handoffs import HandoffStore
from qwenpaw.pawapp.tasks import (
    TaskHandle,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
    TaskSubmission,
)
from qwenpaw.pawapp.tasks.policy import FileTaskPolicy, TaskGrant, TaskPolicy
from qwenpaw.pawapp.tasks.runtime import HostTaskRuntime


def story(revision=1, script="## Scene 1\n\n**阿青**：Keep  this exactly.\n"):
    return StoryPackage(
        story_id="story-one",
        revision=revision,
        title="The return",
        synopsis="A daughter returns to her childhood home.",
        script_markdown=script,
        characters=[
            {
                "id": "qing",
                "name": "阿青",
                "description": "Her left sleeve is red.",
                "continuity": "Never change the sleeve.",
            },
        ],
        references=[
            {
                "id": "look",
                "label": "Look reference",
                "uri": "https://example.com/reference.png",
                "notes": "Muted colors; no automatic fetch.",
            },
        ],
        decisions=["Keep the ending silent."],
    ).model_dump(mode="json")


@pytest.fixture
def setup(tmp_path):
    return (
        CreatorFileServices.create(tmp_path / "creator"),
        TaskScope(
            principal_id="alice",
            workspace_id="one",
            app_id="qwenpaw-creator",
        ),
    )


def test_prepare_exact_script_and_complete_package_survive_replay(setup):
    services, scope = setup
    inputs = {"story": story()}
    result, source = import_story(services, scope, "first", inputs)
    snapshot = services.projects.read(result["project_id"])
    assert snapshot.project.settings.production_stage == "script"
    assert (
        snapshot.project.timelines.items["timeline:main"].description
        == source.script_markdown
    )
    assert read_story(services, snapshot) == source
    slot = snapshot.project.assets.artifact_slots_by_id["script:timeline:main"]
    version = snapshot.project.assets.artifact_versions_by_id[
        slot.selected_version_id
    ]
    indexed = snapshot.project.assets.files_by_id[version.file_id]
    files = AssetFileStore(
        services.projects.project_root(result["project_id"]),
    )
    assert files.read_verified(indexed) == source.script_markdown.encode()
    assert (
        services.sessions.get_project_session(
            result["project_id"],
        ).active_goal_id
        is None
    )
    assert import_story(services, scope, "first", inputs)[0] == result
    assert (
        services.projects.read(result["project_id"]).generation
        == snapshot.generation
    )


def test_revision_preserves_history_and_rejects_other_owner(setup):
    services, scope = setup
    first, _ = import_story(services, scope, "first", {"story": story()})
    inputs = {
        "project_id": first["project_id"],
        "expected_story_digest": first["story_digest"],
        "expected_project_etag": first["project_etag"],
        "story": story(
            2,
            "## Scene 1\n\nThe daughter leaves without a word.\n",
        ),
    }
    foreign = scope.model_copy(update={"principal_id": "bob"})
    with pytest.raises(TaskStoreError, match="story_project_not_found"):
        import_story(services, foreign, "foreign", inputs, revise=True)
    result, _ = import_story(services, scope, "second", inputs, revise=True)
    snapshot = services.projects.read(result["project_id"])
    assert read_story(services, snapshot).revision == 2
    assert (
        read_story(services, snapshot, 1).script_markdown
        == story()["script_markdown"]
    )
    assert (
        story_version(snapshot.project).metadata["story_digest"]
        == result["story_digest"]
    )
    assert (
        import_story(services, scope, "second", inputs, revise=True)[0]
        == result
    )


def test_stale_editor_snapshot_is_not_overwritten(setup):
    services, scope = setup
    first, _ = import_story(services, scope, "first", {"story": story()})
    base = services.projects.read(first["project_id"])
    candidate = base.project.model_dump(mode="json")
    candidate["timelines"]["items"]["timeline:main"][
        "description"
    ] = "Creator edit"
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
    )
    with pytest.raises(TaskStoreError, match="story_revision_conflict"):
        import_story(
            services,
            scope,
            "second",
            {
                "project_id": first["project_id"],
                "expected_story_digest": first["story_digest"],
                "expected_project_etag": first["project_etag"],
                "story": story(2),
            },
            revise=True,
        )
    assert (
        services.projects.read(first["project_id"])
        .project.timelines.items["timeline:main"]
        .description
        == "Creator edit"
    )


def production_submission(scope, result, submission_id="produce-one"):
    action = CreatorStoryProductionTaskAdapter.action_descriptor()
    return TaskSubmission(
        handle=TaskHandle(
            task_id=f"task-{submission_id}",
            submission_id=submission_id,
            scope=scope,
            action_id=action.action_id,
            descriptor_digest=action.descriptor_digest,
            origin=TaskOrigin(
                engagement="delegated",
                origin_ref="chat-two",
                return_session_ref="chat-two",
            ),
            created_at=1000,
            updated_at=1000,
        ),
        action=action,
        inputs={
            "project_id": result["project_id"],
            "story_revision": result["story_revision"],
            "story_digest": result["story_digest"],
            "expected_project_etag": result["project_etag"],
        },
    )


@pytest.mark.asyncio
async def test_production_resumes_same_project_once_from_another_chat(setup):
    services, scope = setup
    result, source = import_story(services, scope, "first", {"story": story()})
    adapter = CreatorStoryProductionTaskAdapter(lambda: services)
    submission = production_submission(scope, result)
    first = await adapter.submit(submission)
    assert await adapter.submit(submission) == first
    assert (await adapter.query(submission)).state == "accepted"
    snapshot = services.projects.read(result["project_id"])
    assert snapshot.project.settings.production_stage == "media"
    assert snapshot.project.settings.script_approval_fingerprint
    assert read_story(services, snapshot) == source
    session = services.sessions.get_project_session(result["project_id"])
    messages = services.sessions.list_messages(
        result["project_id"],
        session.session_id,
    )
    assert len(messages) == 1
    assert (
        "Preserve the agreed script verbatim"
        in messages[0].content_parts[0].text
    )
    assert session.active_goal_id
    record = adapter._store(services, submission.handle.submission_id).read()
    assert record.project_id == result["project_id"]


@pytest.mark.asyncio
async def test_production_rejects_stale_etag_and_foreign_scope(setup):
    services, scope = setup
    result, _ = import_story(services, scope, "first", {"story": story()})
    adapter = CreatorStoryProductionTaskAdapter(lambda: services)
    foreign = scope.model_copy(update={"workspace_id": "other"})
    submission = production_submission(scope, result)
    assert (await adapter.readiness(scope, submission.inputs)).state == "ready"
    assert (
        await adapter.readiness(foreign, submission.inputs)
    ).state == "blocked"
    assert (
        await adapter.readiness(
            scope,
            {**submission.inputs, "story_digest": "0" * 64},
        )
    ).state == "blocked"
    assert {
        "creator.image.generate",
        "creator.video.generate",
    } <= set(submission.action.permissions)
    with pytest.raises(TaskStoreError, match="story_project_not_found"):
        await adapter.submit(production_submission(foreign, result))
    base = services.projects.read(result["project_id"])
    candidate = base.project.model_dump(mode="json")
    candidate["strategy"]["audience"] = "Creator edit"
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
    )
    submission = production_submission(scope, result)
    await adapter.submit(submission)
    events = [event async for event in adapter.attach(submission)]
    assert events[-1].status == "failed"
    assert "review" in events[-1].text_result
    assert (
        events[-1].detail["project_ref"]["project_id"] == result["project_id"]
    )
    assert (await adapter.query(submission)).state == "accepted"
    snapshot = services.projects.read(result["project_id"])
    assert snapshot.project.settings.production_stage == "script"
    assert (
        services.sessions.get_project_session(
            result["project_id"],
        ).active_goal_id
        is None
    )


@pytest.mark.asyncio
async def test_decision_only_revision_invalidates_script_approval(setup):
    services, scope = setup
    first, _ = import_story(services, scope, "first", {"story": story()})
    adapter = CreatorStoryProductionTaskAdapter(lambda: services)
    await adapter.submit(production_submission(scope, first))
    base = services.projects.read(first["project_id"])
    session = services.sessions.get_project_session(first["project_id"])
    revised = story(2)
    revised["decisions"] = ["End on the red sleeve, without dialogue."]
    inputs = {
        "story": revised,
        "project_id": first["project_id"],
        "expected_story_digest": first["story_digest"],
        "expected_project_etag": base.etag,
    }
    with pytest.raises(TaskStoreError, match="story_project_busy"):
        import_story(services, scope, "revision-two", inputs, revise=True)
    assert services.projects.read(first["project_id"]).etag == base.etag
    services.sessions.set_goal_status(
        first["project_id"],
        session.active_goal_id,
        "COMPLETED",
    )
    second, _ = import_story(
        services,
        scope,
        "revision-two",
        inputs,
        revise=True,
    )
    snapshot = services.projects.read(second["project_id"])
    assert snapshot.project.settings.production_stage == "script"
    assert snapshot.project.settings.script_approval_fingerprint is None


def test_story_package_rejects_ambiguous_or_oversized_inputs():
    candidate = story()
    candidate["characters"].append(candidate["characters"][0])
    with pytest.raises(ValidationError, match="unique"):
        StoryPackage.model_validate(candidate)
    candidate = story()
    candidate["script_markdown"] = " " * 10
    with pytest.raises(ValidationError):
        StoryPackage.model_validate(candidate)
    candidate = story()
    candidate["decisions"] = ["x" * 8000] * 64
    with pytest.raises(ValidationError, match="128 KiB"):
        StoryPackage.model_validate(candidate)


@pytest.mark.asyncio
async def test_managed_import_publishes_full_artifacts_and_project_handoff(
    setup,
    tmp_path,
):
    services, scope = setup
    app = PawApp("Creator", app_id=scope.app_id)
    register_story_actions(app, lambda: services)
    registrations = {
        (scope.app_id, r.action.action_id): r for r in app._task_actions
    }
    action = registrations[(scope.app_id, "prepare-production")].action
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        TaskPolicy(
            grants=tuple(
                TaskGrant(
                    scope=scope,
                    action_id=registration.action.action_id,
                    descriptor_digest=registration.action.descriptor_digest,
                )
                for registration in registrations.values()
            ),
        ).model_dump_json(),
    )
    tasks = await TaskStore.open(tmp_path / "tasks.db")
    artifacts = await ArtifactStore.open(tmp_path / "artifacts")
    runtime = HostTaskRuntime(
        tasks,
        policy=FileTaskPolicy(policy_path),
        registrations=lambda: registrations,
        authorize_origin=AsyncMock(),
        artifacts=artifacts,
        interval=0.01,
    )
    await runtime.start()
    try:
        response = await runtime.dispatch(
            scope,
            action.action_id,
            request_id="handoff",
            inputs={"story": story()},
            origin=TaskOrigin(
                engagement="delegated",
                origin_ref="chat-one",
                return_session_ref="chat-one",
            ),
        )
        async with asyncio.timeout(5):
            while True:
                submission = await tasks.get(scope, response["task"].task_id)
                if submission.handle.status in {"succeeded", "failed"}:
                    break
                await asyncio.sleep(0.01)
        assert submission.handle.status == "succeeded"
        receipt = submission.handle.result_data
        assert (
            submission.handle.project_ref.project_id == receipt["project_id"]
        )
        contents = {}
        for ref in submission.handle.output_refs:
            contents[ref.media_type] = (
                await artifacts.read(
                    scope,
                    ref.artifact_id,
                    ref.version,
                )
            )[1]
        assert (
            StoryPackage.model_validate_json(
                contents["application/json"],
            ).model_dump(
                mode="json",
            )
            == story()
        )
        assert contents["text/markdown"] == story()["script_markdown"].encode()
        handoffs = await HandoffStore.open(tmp_path / "handoffs.db", artifacts)
        link = await handoffs.create(submission, target_app_id=scope.app_id)
        resolved = await handoffs.resolve(scope, link.handoff_id)
        assert resolved.context.goal == submission.handle.text_result
        assert len(resolved.context.artifact_refs) == 2
        assert resolved.context.project_ref.project_id == receipt["project_id"]
        response = await runtime.dispatch(
            scope,
            "revise-story",
            request_id="stale-revision",
            inputs={
                "story": story(2),
                "project_id": receipt["project_id"],
                "expected_story_digest": receipt["story_digest"],
                "expected_project_etag": "stale-editor-etag",
            },
            origin=submission.handle.origin,
        )
        async with asyncio.timeout(5):
            while True:
                failed = await tasks.get(scope, response["task"].task_id)
                if failed.handle.status == "failed":
                    break
                await asyncio.sleep(0.01)
        assert "review its current version" in failed.handle.text_result
        assert failed.handle.project_ref.project_id == receipt["project_id"]
        assert services.projects.read(receipt["project_id"]).generation == 1
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_production_recovers_committed_approval_before_goal_creation(
    setup,
    monkeypatch,
):
    services, scope = setup
    result, _ = import_story(services, scope, "first", {"story": story()})
    adapter = CreatorStoryProductionTaskAdapter(lambda: services)
    submission = production_submission(scope, result)
    sessions_type = type(services.sessions)
    original = sessions_type._append_message_unlocked
    failures = []

    def crash_after_approval(self, **kwargs):
        if not failures:
            failures.append(True)
            raise RuntimeError("simulated process loss")
        return original(self, **kwargs)

    monkeypatch.setattr(
        sessions_type,
        "_append_message_unlocked",
        crash_after_approval,
    )
    with pytest.raises(RuntimeError, match="process loss"):
        await adapter.submit(submission)
    approved = services.projects.read(result["project_id"])
    assert approved.project.settings.production_stage == "media"
    await adapter.submit(submission)
    assert (
        services.projects.read(result["project_id"]).generation
        == approved.generation
    )
    session = services.sessions.get_project_session(result["project_id"])
    assert session.active_goal_id
    assert (
        len(
            services.sessions.list_messages(
                result["project_id"],
                session.session_id,
            ),
        )
        == 1
    )


@pytest.mark.asyncio
async def test_production_recovers_pointer_without_reactivating_terminal_goal(
    setup,
    monkeypatch,
):
    services, scope = setup
    result, _ = import_story(services, scope, "first", {"story": story()})
    adapter = CreatorStoryProductionTaskAdapter(lambda: services)
    submission = production_submission(scope, result)
    sessions_type = type(services.sessions)
    original = sessions_type._write_session_unlocked
    failures = []

    def crash_at_pointer(self, session):
        if session.active_goal_id and not failures:
            failures.append(True)
            raise RuntimeError("pointer lost")
        return original(self, session)

    monkeypatch.setattr(
        sessions_type,
        "_write_session_unlocked",
        crash_at_pointer,
    )
    with pytest.raises(RuntimeError, match="pointer lost"):
        await adapter.submit(submission)
    await adapter.submit(submission)
    session = services.sessions.get_project_session(result["project_id"])
    assert session.active_goal_id
    services.sessions.set_goal_status(
        result["project_id"],
        session.active_goal_id,
        "COMPLETED",
    )
    record, request = adapter._candidate(services, submission)
    adapter._create_project(services, record, request)
    assert (
        services.sessions.get_goal(
            result["project_id"],
            session.active_goal_id,
        ).status
        == "COMPLETED"
    )


def test_import_recovers_commit_before_receipt_and_rejects_changed_retry(
    setup,
    monkeypatch,
):
    services, scope = setup
    store_type = type(services.poller)
    original = store_type.note_commit
    failures = []

    def crash_after_commit(self, snapshot):
        if not failures:
            failures.append(True)
            raise RuntimeError("receipt lost")
        return original(self, snapshot)

    monkeypatch.setattr(store_type, "note_commit", crash_after_commit)
    inputs = {"story": story()}
    with pytest.raises(RuntimeError, match="receipt lost"):
        import_story(services, scope, "first", inputs)
    result, _ = import_story(services, scope, "first", inputs)
    assert result["project_generation"] == 1
    assert (
        len(
            services.projects.read(result["project_id"])
            .project.assets.artifact_slots_by_id["story:main"]
            .version_ids,
        )
        == 1
    )
    with pytest.raises(TaskStoreError, match="story_submission_conflict"):
        import_story(services, scope, "first", {"story": story(2)})
