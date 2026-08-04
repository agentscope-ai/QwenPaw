# -*- coding: utf-8 -*-
# pylint: disable=consider-using-from-import,protected-access
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

import api.project_file_routes as project_file_routes
from api.dependencies import creator_error_handler, project_file_services
from api.project_file_routes import router
from domain.errors import CreatorError
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.json_pointer import MISSING, hash_json_value
from services.project_files.models import Project
from services.project_files.review import (
    ReviewDecisionItem,
    ReviewDecisionJournalState,
    ReviewRejectionAction,
    ReviewRejectionFeedback,
)
from services.runtime_files import IdempotencyRecordStore, IdempotencyStatus
from services.runtime_files.models import ReviewBoundary


def _run(coro):
    return asyncio.run(coro)


async def _post_review_decision_twice(app, url, payload):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        first = await client.post(
            url,
            headers={"Idempotency-Key": payload["decisionId"]},
            json=payload,
        )
        replay = await client.post(
            url,
            headers={"Idempotency-Key": payload["decisionId"]},
            json=payload,
        )
    return first, replay


def _app(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    snapshot = services.projects.create(
        Project.new(project_id="project-1", name="Initial", description="old"),
    )
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services, snapshot


def _pending_review(services, base):
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Review candidate"
    result = ProjectCommitBoundary(services.projects).commit(
        base=base,
        candidate=candidate,
        origin="agentdock_interrupt",
        review_policy="require_review",
        review_boundary=ReviewBoundary(
            request_message_seq=2,
            request_id="request-2",
            interrupted_run_id="run-1",
            accepted_generation=base.generation,
            accepted_etag=base.etag,
        ),
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
        round_id="round-2",
    )
    assert result.review is not None
    return result.review


def test_project_snapshot_etag_patch_and_disjoint_stale_merge(
    tmp_path,
) -> None:
    app, _services, base = _app(tmp_path)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.get("/projects/project-1/project")
            unchanged = await client.get(
                "/projects/project-1/project",
                headers={"If-None-Match": first.headers["etag"]},
            )
            patch_name = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "command-name"},
                json={
                    "clientCommandId": "command-name",
                    "editSessionId": "edit-1",
                    "baseGeneration": 0,
                    "baseEtag": base.etag,
                    "operations": [
                        {
                            "op": "replace",
                            "path": "/name",
                            "value": "Agent name",
                            "expectedValueHash": hash_json_value("Initial"),
                        },
                    ],
                },
            )
            patch_description = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "command-description"},
                json={
                    "clientCommandId": "command-description",
                    "editSessionId": "edit-2",
                    "baseGeneration": 0,
                    "baseEtag": base.etag,
                    "operations": [
                        {
                            "op": "replace",
                            "path": "/description",
                            "value": "User description",
                            "expectedValueHash": hash_json_value("old"),
                        },
                    ],
                },
            )
        return first, unchanged, patch_name, patch_description

    first, unchanged, patch_name, patch_description = _run(scenario())
    assert first.status_code == 200
    assert first.json()["project"]["name"] == "Initial"
    assert unchanged.status_code == 304
    assert patch_name.status_code == 200
    assert patch_description.status_code == 200
    assert patch_description.json()["generation"] == 2
    assert patch_description.json()["project"]["name"] == "Agent name"
    assert (
        patch_description.json()["project"]["description"]
        == "User description"
    )


def test_patch_accepts_the_quoted_http_entity_tag_as_base_etag(
    tmp_path,
) -> None:
    app, _services, _base = _app(tmp_path)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            snapshot = await client.get("/projects/project-1/project")
            # The frontend prefers the HTTP ETag header, which carries the
            # quoted entity-tag form, and echoes it back as baseEtag.
            patched = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "command-quoted-etag"},
                json={
                    "clientCommandId": "command-quoted-etag",
                    "editSessionId": "edit-quoted",
                    "baseGeneration": snapshot.json()["generation"],
                    "baseEtag": snapshot.headers["etag"],
                    "operations": [
                        {
                            "op": "replace",
                            "path": "/name",
                            "value": "Quoted base name",
                            "expectedValueHash": hash_json_value("Initial"),
                        },
                    ],
                },
            )
        return snapshot, patched

    snapshot, patched = _run(scenario())
    assert snapshot.headers["etag"].startswith('"')
    assert patched.status_code == 200
    assert patched.json()["project"]["name"] == "Quoted base name"


def test_same_field_stale_patch_returns_cas_conflict(tmp_path) -> None:
    app, _services, base = _app(tmp_path)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        payload = {
            "editSessionId": "edit",
            "baseGeneration": 0,
            "baseEtag": base.etag,
            "operations": [
                {
                    "op": "replace",
                    "path": "/name",
                    "value": "first",
                    "expectedValueHash": hash_json_value("Initial"),
                },
            ],
        }
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "first"},
                json={**payload, "clientCommandId": "first"},
            )
            second = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "second"},
                json={**payload, "clientCommandId": "second"},
            )
        return first, second

    first, second = _run(scenario())
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "CAS_CONFLICT"
    assert second.json()["details"]["conflicts"][0]["pointer"] == "/name"


def test_invalid_external_project_keeps_last_good_and_reports_sync_error(
    tmp_path,
) -> None:
    app, services, _base = _app(tmp_path)
    # Seed the last-good cache before simulating an out-of-protocol writer.
    services.poller.open("project-1")
    services.projects.project_path("project-1").write_text(
        "{invalid",
        encoding="utf-8",
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/projects/project-1/project")

    result = _run(scenario())
    assert result.status_code == 503
    assert result.json()["code"] == "PROJECT_INVALID"
    assert result.json()["lastGoodGeneration"] == 0


def test_deleted_project_snapshot_does_not_serve_stale_last_good(
    tmp_path,
) -> None:
    app, services, _base = _app(tmp_path)
    services.poller.open("project-1")
    services.projects.delete("project-1")

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/projects/project-1/project")

    result = _run(scenario())
    assert result.status_code == 404
    assert services.poller.cached("project-1") is None


def test_active_review_poll_is_created_only_from_review_boundary(
    tmp_path,
) -> None:
    app, services, base = _app(tmp_path)
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Review candidate"
    ProjectCommitBoundary(services.projects).commit(
        base=base,
        candidate=candidate,
        origin="agentdock_interrupt",
        review_policy="require_review",
        review_boundary=ReviewBoundary(
            request_message_seq=2,
            request_id="request-2",
            interrupted_run_id="run-1",
            accepted_generation=base.generation,
            accepted_etag=base.etag,
        ),
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
        round_id="round-2",
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.get(
                "/projects/project-1/runtime/reviews/active",
            )
            second = await client.get(
                "/projects/project-1/runtime/reviews/active",
                headers={"If-None-Match": first.headers["etag"]},
            )
        return first, second

    first, second = _run(scenario())
    assert first.status_code == 200
    reviews = first.json()
    assert isinstance(reviews, list) and len(reviews) == 1
    assert reviews[0]["request_id"] == "request-2"
    assert second.status_code == 304


def test_patch_add_uses_explicit_missing_hash(tmp_path) -> None:
    app, _services, base = _app(tmp_path)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "add-field"},
                json={
                    "clientCommandId": "add-field",
                    "editSessionId": "edit",
                    "baseGeneration": 0,
                    "baseEtag": base.etag,
                    "operations": [
                        {
                            "op": "add",
                            "path": "/strategy/audience",
                            "value": "all",
                            "expectedValueHash": hash_json_value(MISSING),
                        },
                    ],
                },
            )

    # The field exists in the strict schema, so its missing-value precondition
    # fails before any mutation can be published.
    result = _run(scenario())
    assert result.status_code == 409
    assert result.json()["code"] == "CAS_CONFLICT"


def test_project_patch_replays_success_and_rejects_payload_drift(
    tmp_path,
) -> None:
    app, _services, base = _app(tmp_path)
    payload = {
        "clientCommandId": "command-replay",
        "editSessionId": "edit-1",
        "baseGeneration": base.generation,
        "baseEtag": base.etag,
        "operations": [
            {
                "op": "replace",
                "path": "/name",
                "value": "Replayed name",
                "expectedValueHash": hash_json_value("Initial"),
            },
        ],
    }

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "command-replay"},
                json=payload,
            )
            replay = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "command-replay"},
                json=payload,
            )
            drift = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "command-replay"},
                json={
                    **payload,
                    "operations": [
                        {
                            **payload["operations"][0],
                            "value": "Payload drift",
                        },
                    ],
                },
            )
        return first, replay, drift

    first, replay, drift = _run(scenario())
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.headers["etag"] == first.headers["etag"]
    assert drift.status_code == 409
    assert drift.json()["code"] == "CONFLICT"


def test_project_patch_recovers_crash_before_idempotency_completion(
    tmp_path,
    monkeypatch,
) -> None:
    app, services, base = _app(tmp_path)
    payload = {
        "clientCommandId": "crash-recovery-command",
        "editSessionId": "edit-crash",
        "baseGeneration": base.generation,
        "baseEtag": base.etag,
        "operations": [
            {
                "op": "replace",
                "path": "/name",
                "value": "Published exactly once",
                "expectedValueHash": hash_json_value("Initial"),
            },
        ],
    }

    class SimulatedCompletionWriteFailure(RuntimeError):
        pass

    original_complete = IdempotencyRecordStore.complete
    crashed = False

    def crash_before_completion(self, **kwargs):
        nonlocal crashed
        if (
            not crashed
            and kwargs["scope"] == "PATCH /projects/{projectId}/project"
        ):
            crashed = True
            raise SimulatedCompletionWriteFailure
        return original_complete(self, **kwargs)

    monkeypatch.setattr(
        IdempotencyRecordStore,
        "complete",
        crash_before_completion,
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            failed_completion = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "crash-recovery-command"},
                json=payload,
            )
            assert failed_completion.status_code == 503

            record_after_crash = IdempotencyRecordStore(
                services.projects.project_root("project-1")
                / "runtime"
                / "commands"
                / "idempotency",
            ).get(
                owner_id="project-1",
                scope="PATCH /projects/{projectId}/project",
                idempotency_key="crash-recovery-command",
            )
            assert record_after_crash is not None
            assert record_after_crash.status is IdempotencyStatus.IN_PROGRESS
            assert services.projects.read("project-1").generation == 1

            monkeypatch.setattr(
                IdempotencyRecordStore,
                "complete",
                original_complete,
            )
            return record_after_crash, await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "crash-recovery-command"},
                json=payload,
            )

    record_after_crash, replay = _run(scenario())
    assert replay.status_code == 200
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.json()["generation"] == 1
    assert replay.json()["project"]["name"] == "Published exactly once"
    assert services.projects.read("project-1").generation == 1

    transactions_root = (
        services.projects.project_root("project-1")
        / "runtime"
        / "transactions"
    )
    assert sorted(
        item.name for item in transactions_root.iterdir() if item.is_dir()
    ) == [record_after_crash.record_id]

    completed = IdempotencyRecordStore(
        services.projects.project_root("project-1")
        / "runtime"
        / "commands"
        / "idempotency",
    ).get(
        owner_id="project-1",
        scope="PATCH /projects/{projectId}/project",
        idempotency_key="crash-recovery-command",
    )
    assert completed is not None
    assert completed.status is IdempotencyStatus.COMPLETED


def test_failed_project_patch_is_terminal_and_replays_exact_error(
    tmp_path,
) -> None:
    app, services, base = _app(tmp_path)
    stale_payload = {
        "clientCommandId": "failed-command",
        "editSessionId": "edit-failed",
        "baseGeneration": base.generation,
        "baseEtag": base.etag,
        "operations": [
            {
                "op": "replace",
                "path": "/name",
                "value": "Stale write",
                "expectedValueHash": hash_json_value("Initial"),
            },
        ],
    }

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            winner = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "winner"},
                json={
                    **stale_payload,
                    "clientCommandId": "winner",
                    "operations": [
                        {
                            **stale_payload["operations"][0],
                            "value": "Winner",
                        },
                    ],
                },
            )
            first = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "failed-command"},
                json=stale_payload,
            )
            replay = await client.patch(
                "/projects/project-1/project",
                headers={"Idempotency-Key": "failed-command"},
                json=stale_payload,
            )
        return winner, first, replay

    winner, first, replay = _run(scenario())
    assert winner.status_code == 200
    assert first.status_code == 409
    assert first.json()["code"] == "CAS_CONFLICT"
    assert replay.status_code == first.status_code
    assert replay.json() == first.json()

    record = IdempotencyRecordStore(
        services.projects.project_root("project-1")
        / "runtime"
        / "commands"
        / "idempotency",
    ).get(
        owner_id="project-1",
        scope="PATCH /projects/{projectId}/project",
        idempotency_key="failed-command",
    )
    assert record is not None
    assert record.status is IdempotencyStatus.FAILED


def test_review_decision_replays_success_and_rejects_payload_drift(
    tmp_path,
) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    operation = review.operations[0]
    payload = {
        "decisionId": "decision-1",
        "decisionToken": review.decision_token,
        "decisions": [
            {
                "operation_id": operation.operation_id,
                "decision": "ACCEPT",
            },
        ],
    }
    url = f"/projects/project-1/runtime/reviews/{review.review_id}/decisions"

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                url,
                headers={"Idempotency-Key": "decision-1"},
                json=payload,
            )
            replay = await client.post(
                url,
                headers={"Idempotency-Key": "decision-1"},
                json=payload,
            )
            drift = await client.post(
                url,
                headers={"Idempotency-Key": "decision-1"},
                json={
                    **payload,
                    "decisions": [
                        {
                            "operation_id": operation.operation_id,
                            "decision": "REJECT",
                        },
                    ],
                },
            )
        return first, replay, drift

    first, replay, drift = _run(scenario())
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert drift.status_code == 409
    assert drift.json()["code"] == "CONFLICT"


def test_review_decision_recovers_crash_before_idempotency_completion(
    tmp_path,
    monkeypatch,
) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    payload = {
        "decisionId": "decision-completion-crash",
        "decisionToken": review.decision_token,
        "decisions": [
            {
                "operation_id": review.operations[0].operation_id,
                "decision": "ACCEPT",
            },
        ],
    }
    url = f"/projects/project-1/runtime/reviews/{review.review_id}/decisions"
    scope = (
        "POST /projects/{projectId}/runtime/reviews/"
        f"{review.review_id}/decisions"
    )

    class SimulatedCompletionWriteFailure(RuntimeError):
        pass

    original_complete = IdempotencyRecordStore.complete
    crashed = False

    def crash_before_completion(self, **kwargs):
        nonlocal crashed
        if not crashed and kwargs["scope"] == scope:
            crashed = True
            raise SimulatedCompletionWriteFailure
        return original_complete(self, **kwargs)

    monkeypatch.setattr(
        IdempotencyRecordStore,
        "complete",
        crash_before_completion,
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            failed_completion = await client.post(
                url,
                headers={"Idempotency-Key": "decision-completion-crash"},
                json=payload,
            )
            assert failed_completion.status_code == 503

            store = IdempotencyRecordStore(
                services.projects.project_root("project-1")
                / "runtime"
                / "commands"
                / "idempotency",
            )
            after_crash = store.get(
                owner_id="project-1",
                scope=scope,
                idempotency_key="decision-completion-crash",
            )
            assert after_crash is not None
            assert after_crash.status is IdempotencyStatus.IN_PROGRESS
            assert (
                services.reviews.get(
                    "project-1",
                    review.review_id,
                ).status.value
                == "RESOLVED"
            )

            monkeypatch.setattr(
                IdempotencyRecordStore,
                "complete",
                original_complete,
            )
            return store, await client.post(
                url,
                headers={"Idempotency-Key": "decision-completion-crash"},
                json=payload,
            )

    store, replay = _run(scenario())
    assert replay.status_code == 200
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.json()["status"] == "RESOLVED"
    assert services.projects.read("project-1").generation == 1

    completed = store.get(
        owner_id="project-1",
        scope=scope,
        idempotency_key="decision-completion-crash",
    )
    assert completed is not None
    assert completed.status is IdempotencyStatus.COMPLETED


def test_rejection_feedback_appends_exactly_one_action_specific_message(
    tmp_path,
) -> None:
    for action, expected_role, expected_channel, expected_text in (
        (
            "UNDO_ONLY",
            "system",
            "runtime",
            "没有要求重做",
        ),
        (
            "UNDO_AND_REGENERATE",
            "user",
            "agentdock",
            "明确要求重新生成",
        ),
    ):
        app, services, base = _app(tmp_path / action.lower())
        runtime = services.sessions.create_project_runtime(
            "project-1",
            session_id="session-1",
            conversation_id="conversation-1",
        )
        review = _pending_review(services, base)
        payload = {
            "decisionId": f"decision-{action.lower()}",
            "decisionToken": review.decision_token,
            "decisions": [
                {
                    "operation_id": review.operations[0].operation_id,
                    "decision": "REJECT",
                },
            ],
            "rejectionFeedback": {
                "action": action,
                "feedbackNote": "人物状态不对；保持身份一致",
            },
        }
        url = (
            f"/projects/project-1/runtime/reviews/{review.review_id}/decisions"
        )

        first, replay = _run(
            _post_review_decision_twice(app, url, payload),
        )
        assert first.status_code == 200
        assert replay.status_code == 200
        assert replay.headers["X-Idempotent-Replay"] == "true"

        messages = services.sessions.list_messages(
            "project-1",
            runtime.session.session_id,
            after_seq=0,
            limit=None,
        )
        assert len(messages) == 1
        assert messages[0].role == expected_role
        assert messages[0].channel.value == expected_channel
        assert messages[0].source == "review_rejection_feedback"
        assert messages[0].content_parts[0].text is not None
        assert expected_text in messages[0].content_parts[0].text
        assert "人物状态不对" in messages[0].content_parts[0].text

        restarted = CreatorFileServices.create(services.root)
        recovered_messages = restarted.sessions.list_messages(
            "project-1",
            runtime.session.session_id,
            after_seq=0,
            limit=None,
        )
        assert len(recovered_messages) == 1

        journal = services.reviews.get_decision_journal(
            "project-1",
            review.review_id,
            str(payload["decisionId"]),
        )
        assert journal.event is not None
        assert journal.event.rejection_feedback is not None
        assert journal.event.rejection_feedback.action.value == action


def test_rejection_feedback_requires_a_reject_decision(tmp_path) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    url = f"/projects/project-1/runtime/reviews/{review.review_id}/decisions"

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                url,
                headers={"Idempotency-Key": "invalid-feedback"},
                json={
                    "decisionId": "invalid-feedback",
                    "decisionToken": review.decision_token,
                    "decisions": [
                        {
                            "operation_id": review.operations[0].operation_id,
                            "decision": "ACCEPT",
                        },
                    ],
                    "rejectionFeedback": {"action": "UNDO_ONLY"},
                },
            )

    result = _run(scenario())
    assert result.status_code == 422


def test_accepting_generated_artifact_queues_automatic_resume(
    tmp_path,
    monkeypatch,
) -> None:
    _app_instance, services, _base = _app(tmp_path)
    runtime = services.sessions.create_project_runtime(
        "project-1",
        session_id="session-1",
        conversation_id="conversation-1",
    )
    operation = SimpleNamespace(
        operation_id="operation-storyboard",
        json_pointer=(
            "/assets/artifact_versions_by_id/artifact-version-storyboard"
        ),
        target_ref="element:ep22",
        after={
            "version_id": "artifact-version-storyboard",
            "owner_ref": "element:ep22",
            "name": "ep22 分镜图",
            "metadata": {"targetRef": "element:ep22"},
        },
    )
    journal = SimpleNamespace(
        state=ReviewDecisionJournalState.FINALIZED,
        rejection_feedback=None,
        rejection_targets=[],
        decisions=[
            SimpleNamespace(
                operation_id="operation-storyboard",
                decision="ACCEPT",
            ),
        ],
        review_before=SimpleNamespace(
            operations=[operation],
            request_message_seq=99,
        ),
    )
    monkeypatch.setattr(
        services.reviews,
        "get_decision_journal",
        lambda *_args: journal,
    )

    services._publish_review_followup(
        project_id="project-1",
        review_id="review-storyboard",
        decision_id="decision-accept-storyboard",
    )

    messages = services.sessions.list_messages(
        "project-1",
        runtime.session.session_id,
        after_seq=0,
        limit=None,
    )
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].source == "review_approval_resume"
    assert messages[0].channel.value == "agentdock"
    assert messages[0].classification.value == "review_revise"
    assert messages[0].content_parts[0].text is not None
    assert "审阅已通过" in messages[0].content_parts[0].text
    assert "不要要求用户输入 continue" in messages[0].content_parts[0].text
    assert messages[0].metadata["targets"] == [
        {
            "target_ref": "element:ep22",
            "artifact_version_id": "artifact-version-storyboard",
            "label": "ep22 分镜图",
        },
    ]


def test_startup_recovers_feedback_finalized_before_message_append(
    tmp_path,
) -> None:
    _app_instance, services, base = _app(tmp_path)
    runtime = services.sessions.create_project_runtime(
        "project-1",
        session_id="session-1",
        conversation_id="conversation-1",
    )
    review = _pending_review(services, base)
    services.reviews.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[
            ReviewDecisionItem(
                operation_id=review.operations[0].operation_id,
                decision="REJECT",
            ),
        ],
        rejection_feedback=ReviewRejectionFeedback(
            action=ReviewRejectionAction.UNDO_AND_REGENERATE,
            problemNote="风格不一致",
        ),
        decision_id="decision-before-crash",
    )
    assert (
        services.sessions.list_messages(
            "project-1",
            runtime.session.session_id,
            after_seq=0,
            limit=None,
        )
        == []
    )

    restarted = CreatorFileServices.create(services.root)
    messages = restarted.sessions.list_messages(
        "project-1",
        runtime.session.session_id,
        after_seq=0,
        limit=None,
    )
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content_parts[0].text is not None
    assert "风格不一致" in messages[0].content_parts[0].text
    serialized_feedback = messages[0].metadata["rejectionFeedback"]
    assert isinstance(serialized_feedback, dict)
    assert "feedbackNote" not in serialized_feedback

    replayed = CreatorFileServices.create(services.root)
    assert (
        len(
            replayed.sessions.list_messages(
                "project-1",
                runtime.session.session_id,
                after_seq=0,
                limit=None,
            ),
        )
        == 1
    )


def test_failed_review_decision_is_terminal_and_replays_exact_error(
    tmp_path,
) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    payload = {
        "decisionId": "failed-decision",
        "decisionToken": "stale-token",
        "decisions": [
            {
                "operation_id": review.operations[0].operation_id,
                "decision": "ACCEPT",
            },
        ],
    }
    url = f"/projects/project-1/runtime/reviews/{review.review_id}/decisions"

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                url,
                headers={"Idempotency-Key": "failed-decision"},
                json=payload,
            )
            replay = await client.post(
                url,
                headers={"Idempotency-Key": "failed-decision"},
                json=payload,
            )
        return first, replay

    first, replay = _run(scenario())
    assert first.status_code == 409
    assert first.json()["code"] == "CAS_CONFLICT"
    assert replay.status_code == first.status_code
    assert replay.json() == first.json()

    scope = (
        "POST /projects/{projectId}/runtime/reviews/"
        f"{review.review_id}/decisions"
    )
    record = IdempotencyRecordStore(
        services.projects.project_root("project-1")
        / "runtime"
        / "commands"
        / "idempotency",
    ).get(
        owner_id="project-1",
        scope=scope,
        idempotency_key="failed-decision",
    )
    assert record is not None
    assert record.status is IdempotencyStatus.FAILED


def test_review_reject_does_not_use_decision_id_as_a_path(tmp_path) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    malicious_id = "x/../../../../escaped"
    url = f"/projects/project-1/runtime/reviews/{review.review_id}/decisions"

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                url,
                headers={"Idempotency-Key": malicious_id},
                json={
                    "decisionId": malicious_id,
                    "decisionToken": review.decision_token,
                    "decisions": [
                        {
                            "operation_id": review.operations[0].operation_id,
                            "decision": "REJECT",
                        },
                    ],
                },
            )

    result = _run(scenario())
    assert result.status_code == 200
    assert not (tmp_path / "escaped").exists()


def test_missing_project_writes_do_not_create_a_phantom_directory(
    tmp_path,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            patch = await client.patch(
                "/projects/missing/project",
                headers={"Idempotency-Key": "missing-patch"},
                json={
                    "clientCommandId": "missing-patch",
                    "editSessionId": "edit",
                    "baseGeneration": 0,
                    "baseEtag": "etag",
                    "operations": [
                        {
                            "op": "replace",
                            "path": "/name",
                            "value": "name",
                            "expectedValueHash": hash_json_value("old"),
                        },
                    ],
                },
            )
            acquire = await client.post(
                "/projects/missing/runtime/blocks",
                json={
                    "jsonPointer": "/name",
                    "ownerKind": "user",
                    "ownerId": "user-1",
                    "baseFieldHash": "hash",
                },
            )
            renew = await client.patch(
                "/projects/missing/runtime/blocks/block-1",
                json={"token": "token"},
            )
            release = await client.request(
                "DELETE",
                "/projects/missing/runtime/blocks/block-1",
                json={"token": "token"},
            )
            review = await client.post(
                "/projects/missing/runtime/reviews/review-1/decisions",
                headers={"Idempotency-Key": "missing-decision"},
                json={
                    "decisionId": "missing-decision",
                    "decisionToken": "token",
                    "decisions": [
                        {"operation_id": "operation-1", "decision": "ACCEPT"},
                    ],
                },
            )
        return patch, acquire, renew, release, review

    results = _run(scenario())
    assert [result.status_code for result in results] == [
        404,
        404,
        404,
        404,
        404,
    ]
    assert not (tmp_path / "missing").exists()


def test_project_delete_between_patch_precheck_and_lifecycle_admission_is_404(
    tmp_path,
    monkeypatch,
) -> None:
    app, services, base = _app(tmp_path)
    initial_check_complete = asyncio.Event()
    allow_request_to_continue = asyncio.Event()
    original = project_file_routes._require_existing_project
    calls = 0

    async def pause_after_initial_check(file_services, project_id):
        nonlocal calls
        await original(file_services, project_id)
        calls += 1
        if calls == 1:
            initial_check_complete.set()
            await allow_request_to_continue.wait()

    monkeypatch.setattr(
        project_file_routes,
        "_require_existing_project",
        pause_after_initial_check,
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            request = asyncio.create_task(
                client.patch(
                    "/projects/project-1/project",
                    headers={"Idempotency-Key": "delete-race"},
                    json={
                        "clientCommandId": "delete-race",
                        "editSessionId": "edit-delete-race",
                        "baseGeneration": base.generation,
                        "baseEtag": base.etag,
                        "operations": [
                            {
                                "op": "replace",
                                "path": "/name",
                                "value": "Must not resurrect",
                                "expectedValueHash": hash_json_value(
                                    "Initial",
                                ),
                            },
                        ],
                    },
                ),
            )
            await asyncio.wait_for(initial_check_complete.wait(), timeout=1)
            await asyncio.to_thread(services.projects.delete, "project-1")
            allow_request_to_continue.set()
            return await request

    result = _run(scenario())
    assert result.status_code == 404
    assert not services.projects.project_root("project-1").exists()
