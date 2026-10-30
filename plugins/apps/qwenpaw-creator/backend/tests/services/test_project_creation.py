# -*- coding: utf-8 -*-
"""Focused identity-receipt tests for atomic Project creation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.errors import ConflictError, StorageIntegrityError
from schemas.projects import ProjectCreateRequest
from services.project_files.facade import CreatorFileServices

pytestmark = pytest.mark.unit


def _request(
    request_id: str = "video-workflow-creation-1",
    *,
    initial_goal: str | None = "Build the exact video plan.",
) -> ProjectCreateRequest:
    return ProjectCreateRequest(
        clientRequestId=request_id,
        name="Workflow Project",
        description="Created for a video workflow.",
        scenario="general",
        aspectRatio="16:9",
        resolution="720P",
        initialGoal=initial_goal,
    )


def _session_path(services: CreatorFileServices, project_id: str) -> Path:
    return next(
        (services.root / project_id / "runtime" / "sessions").glob(
            "*/session.json",
        ),
    )


def _rewrite_session(
    services: CreatorFileServices,
    project_id: str,
    mutate,
) -> None:
    path = _session_path(services, project_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_identity_creation_persists_and_replays_exact_runtime_ids(
    tmp_path: Path,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    request = _request()

    first = services.project_creation.create_with_runtime_identity(request)
    replay = services.project_creation.create_with_runtime_identity(request)
    lookup = services.project_creation.lookup_with_runtime_identity(request)

    assert lookup is not None
    assert replay == first == lookup
    assert first.goal_id is not None
    assert first.initial_message_id is not None
    response = first.response
    session = services.sessions.get_project_session(response.project_id)
    receipt = session.metadata["projectCreate"]["runtimeBootstrap"]
    assert receipt == {
        "schemaVersion": 1,
        "goalId": first.goal_id,
        "initialMessageId": first.initial_message_id,
    }

    goal = services.sessions.get_goal(response.project_id, first.goal_id)
    messages = services.sessions.list_messages(
        response.project_id,
        response.creator_session_id,
    )
    assert goal.goal_id == first.goal_id
    assert goal.intent == request.initial_goal
    assert [message.message_id for message in messages] == [
        first.initial_message_id,
    ]
    assert messages[0].content_parts[0].text == request.initial_goal


def test_creation_without_initial_goal_persists_explicit_null_identities(
    tmp_path: Path,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    request = _request("video-workflow-no-goal", initial_goal=None)

    result = services.project_creation.create_with_runtime_identity(request)

    assert result.goal_id is None
    assert result.initial_message_id is None
    assert services.project_creation.create(request) == result.response
    session = services.sessions.get_project_session(result.response.project_id)
    assert session.metadata["projectCreate"]["runtimeBootstrap"] == {
        "schemaVersion": 1,
        "goalId": None,
        "initialMessageId": None,
    }


@pytest.mark.parametrize("field", ["goalId", "initialMessageId"])
def test_identity_lookup_rejects_tampered_bootstrap_id(
    tmp_path: Path,
    field: str,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    request = _request(f"video-workflow-tamper-{field}")
    result = services.project_creation.create_with_runtime_identity(request)

    def mutate(payload: dict) -> None:
        payload["metadata"]["projectCreate"]["runtimeBootstrap"][
            field
        ] = "tampered-runtime-id"

    _rewrite_session(services, result.response.project_id, mutate)

    with pytest.raises(StorageIntegrityError):
        services.project_creation.lookup_with_runtime_identity(request)


def test_identity_lookup_rejects_tampered_persisted_goal(
    tmp_path: Path,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    request = _request("video-workflow-tampered-goal")
    result = services.project_creation.create_with_runtime_identity(request)
    assert result.goal_id is not None
    goal_path = (
        services.root
        / result.response.project_id
        / "runtime"
        / "goals"
        / f"{result.goal_id}.json"
    )
    payload = json.loads(goal_path.read_text(encoding="utf-8"))
    payload["intent"] = "A different persisted goal."
    goal_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(StorageIntegrityError):
        services.project_creation.lookup_with_runtime_identity(request)


def test_legacy_receipt_remains_publicly_readable_but_has_no_identity_api(
    tmp_path: Path,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    request = _request("legacy-project-create-receipt")
    result = services.project_creation.create_with_runtime_identity(request)

    def mutate(payload: dict) -> None:
        del payload["metadata"]["projectCreate"]["runtimeBootstrap"]

    _rewrite_session(services, result.response.project_id, mutate)

    assert services.project_creation.lookup(request) == result.response
    assert services.project_creation.create(request) == result.response
    with pytest.raises(ConflictError):
        services.project_creation.lookup_with_runtime_identity(request)
