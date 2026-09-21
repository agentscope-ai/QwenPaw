# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""HTTP authorization, blocked setup and lifecycle recovery invariants."""

import asyncio
from dataclasses import replace
import hashlib
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app import auth
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.pawapp.artifact_routes import router as artifact_router
from qwenpaw.pawapp.artifacts import ArtifactStore
from qwenpaw.pawapp.handoffs import HandoffStore
from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    CommandLookup,
    ExecutorEvent,
    ExecutorRunRef,
    SubmissionLookup,
    TaskScope,
    TaskStore,
    TaskStoreError,
    grant_routes,
)
from qwenpaw.pawapp.tasks.binding import ActionRegistration, Readiness
from qwenpaw.pawapp.tasks.contracts import content_digest
from qwenpaw.pawapp.tasks.grant_routes import router as grant_router
from qwenpaw.pawapp.tasks.policy import FileTaskPolicy, TaskGrant, TaskPolicy
from qwenpaw.pawapp.tasks.routes import HostOrigins, router
from qwenpaw.pawapp.tasks.runtime import HostTaskRuntime
from qwenpaw.pawapp.setup import (
    ReadinessResult,
    SetupCheckRegistration,
    SetupCoordinator,
    SetupEntryDescriptor,
    SetupEntryRegistration,
    SetupOpenAction,
    SetupRequirement,
    SetupResult,
    SetupStore,
)
from qwenpaw.pawapp.setup.routes import router as setup_router
from tests.pawapp_data_task_support import load_data_task_bridge

ACTION = load_data_task_bridge().data_action_descriptor()
SCOPE = TaskScope(
    principal_id="alice",
    workspace_id="sales",
    app_id="qwenpaw-data",
)
PREFIX = "/api/pawapps/qwenpaw-data/workspaces/sales"
BODY = {
    "request_id": "req-1",
    "engagement": "delegated",
    "chat_id": "main",
    "inputs": {"text": "private prompt", "datasource_id": "sales"},
}


class Executor:
    submission_protocol_version = 1

    def __init__(self, runs):
        self.runs = runs
        self.closed = False
        self.ready = Readiness(state="ready")
        self.release = asyncio.Event()
        self.release.set()
        self.commands = {}
        self.command_calls = []

    async def readiness(self, scope, inputs):
        del scope, inputs
        return self.ready

    async def submit(self, submission):
        key = submission.handle.submission_id
        return self.runs.setdefault(
            key,
            ExecutorRunRef(
                executor_id="engine",
                session_id="session-" + key,
                run_id=key,
            ),
        )

    async def query(self, submission):
        run = self.runs.get(submission.handle.submission_id)
        return SubmissionLookup(
            state="accepted" if run else "not_found",
            run_ref=run,
        )

    async def attach(self, submission):
        await self.release.wait()
        project_id = submission.handle.executor_run_ref.session_id
        yield ExecutorEvent(
            run_ref=submission.handle.executor_run_ref,
            sequence=0,
            cursor="0",
            status="succeeded",
            text_result="42",
            detail={
                "project_ref": {
                    "schema_version": 1,
                    "app_id": submission.handle.scope.app_id,
                    "project_id": project_id,
                    "kind": "analysis-session",
                    "revision": 1,
                },
            },
        )

    async def command(self, submission, command):
        self.command_calls.append(
            (submission.handle.task_id, command.command_id),
        )
        return self.commands.setdefault(
            command.command_id,
            CommandLookup(state="accepted"),
        )

    async def query_command(self, submission, command):
        del submission
        return self.commands.get(
            command.command_id,
            CommandLookup(state="not_found"),
        )

    async def aclose(self):
        self.closed = True


class DeferredSetupExecutor(Executor):
    async def attach(self, submission):
        await self.release.wait()
        if submission.handle.replay_cursor is None:
            yield ExecutorEvent(
                run_ref=submission.handle.executor_run_ref,
                sequence=0,
                cursor="setup:0",
                status="waiting_for_setup",
                setup_need={
                    "requirement_id": "analysis-model-deferred",
                    "reason_code": "analysis_model_missing",
                    "reason": "Configure an analysis model.",
                },
            )
            return
        yield ExecutorEvent(
            run_ref=submission.handle.executor_run_ref,
            sequence=1,
            cursor="done:1",
            status="succeeded",
            text_result="42",
        )


@pytest.fixture
async def host(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "has_registered_users", lambda: True)
    monkeypatch.setattr(
        auth,
        "verify_token",
        {
            "alice-token": "alice",
            "bob-token": "bob",
        }.get,
    )
    monkeypatch.setattr(
        auth,
        "_get_config_cached",
        lambda: (
            SimpleNamespace(security=SimpleNamespace(allow_no_auth_hosts=[])),
            0,
        ),
    )
    monkeypatch.setattr(auth, "resolve_client_ip", lambda request: "192.0.2.1")
    monkeypatch.setattr(
        grant_routes,
        "workspace_enabled",
        AsyncMock(return_value=True),
    )
    chats = {
        "main": ChatSpec(
            id="main",
            user_id="alice",
            session_id="main-session",
        ),
        "direct": ChatSpec(
            id="direct",
            user_id="alice",
            session_id="pawapp:qwenpaw-data:one",
            meta={"pawapp": {"app_id": "qwenpaw-data", "agent_id": "sales"}},
        ),
        "bob": ChatSpec(id="bob", user_id="bob", session_id="bob-session"),
    }
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            get_chat=AsyncMock(side_effect=chats.get),
        ),
    )
    manager = SimpleNamespace(get_agent=AsyncMock(return_value=workspace))
    origins = HostOrigins(manager, AsyncMock(return_value=True))
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        TaskPolicy(
            grants=(
                TaskGrant(
                    scope=SCOPE,
                    action_id=ACTION.action_id,
                    descriptor_digest=ACTION.descriptor_digest,
                    input_values={"datasource_id": ["sales"]},
                ),
            ),
        ).model_dump_json(),
    )
    store = await TaskStore.open(tmp_path / "tasks.db")
    artifacts = await ArtifactStore.open(tmp_path / "artifacts")
    handoffs = await HandoffStore.open(
        tmp_path / "handoffs.sqlite3",
        artifacts,
    )
    setup_store = await SetupStore.open(tmp_path / "setup.sqlite3")
    runs = {}
    adapters = []

    def factory():
        adapter = Executor(runs)
        adapters.append(adapter)
        return adapter

    registrations = {
        (SCOPE.app_id, ACTION.action_id): ActionRegistration(
            action=ACTION,
            factory=factory,
            settings_entry="/apps/qwenpaw-data",
            capability_id="data_analysis",
            capability_label="Analyze data",
            capability_summary=(
                "Run governed analysis against an approved data source."
            ),
            capability_risk="analysis",
        ),
    }
    setup_holder = [
        SetupCoordinator(
            checks=lambda: {},
            entries=lambda: {},
            store=setup_store,
        ),
    ]

    def runtime(task_store):
        return HostTaskRuntime(
            task_store,
            policy=FileTaskPolicy(policy_path),
            registrations=lambda: registrations,
            authorize_origin=origins,
            artifacts=artifacts,
            handoffs=handoffs,
            setup=setup_holder[0],
            interval=0.01,
        )

    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(router, prefix="/api")
    app.include_router(grant_router, prefix="/api")
    app.include_router(artifact_router, prefix="/api")
    app.include_router(setup_router, prefix="/api")
    app.state.pawapp_task_origins = origins
    app.state.pawapp_tasks = runtime(store)
    app.state.pawapp_artifacts = artifacts
    app.state.pawapp_setup = setup_holder[0]
    await app.state.pawapp_tasks.start()
    await app.state.pawapp_tasks.describe(SCOPE, "analyze")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://host",
        headers={"Authorization": "Bearer alice-token"},
    ) as client:
        yield SimpleNamespace(
            app=app,
            client=client,
            store=store,
            runs=runs,
            adapters=adapters,
            registrations=registrations,
            policy_path=policy_path,
            runtime=runtime,
            chats=chats,
            artifacts=artifacts,
            handoffs=handoffs,
            setup_holder=setup_holder,
            setup_store=setup_store,
        )
    await app.state.pawapp_tasks.aclose()


async def settled(host, task_id):
    async with asyncio.timeout(3):
        while True:
            item = await host.store.get(SCOPE, task_id)
            if item.handle.status == "succeeded":
                return item
            await asyncio.sleep(0.01)


async def test_app_resolves_optional_input_before_scoped_authorization(host):
    action = ActionDescriptor(
        app_id=SCOPE.app_id,
        action_id="list-directory",
        summary="List one authorized directory.",
        engagements=("delegated", "direct"),
        input_schema={
            "type": "object",
            "properties": {"directory": {"type": "string"}},
            "additionalProperties": False,
        },
        output_types=("text/plain",),
        permissions=("filesystem.directory.read",),
        effects=("filesystem_read",),
        adapter_ref="fixture.directory.v1",
    )
    selected = {"directory": "/allowed"}

    async def resolve_inputs(_scope, inputs):
        return {"directory": inputs.get("directory", selected["directory"])}

    await host.app.state.pawapp_tasks.aclose()
    host.registrations.clear()
    host.registrations[(SCOPE.app_id, action.action_id)] = ActionRegistration(
        action=action,
        factory=lambda: Executor(host.runs),
        settings_entry="/apps/qwenpaw-data",
        input_resolver=resolve_inputs,
    )
    host.policy_path.write_text(
        TaskPolicy(
            grants=(
                TaskGrant(
                    scope=SCOPE,
                    action_id=action.action_id,
                    descriptor_digest=action.descriptor_digest,
                    input_values={"directory": ["/allowed"]},
                ),
            ),
        ).model_dump_json(),
    )
    host.app.state.pawapp_tasks = host.runtime(host.store)
    await host.app.state.pawapp_tasks.start()

    body = {
        "request_id": "directory-request-1",
        "engagement": "delegated",
        "chat_id": "main",
        "inputs": {},
    }
    response = await host.client.post(
        PREFIX + "/actions/list-directory/tasks",
        json=body,
    )
    assert response.status_code == 202
    task_id = response.json()["task"]["task_id"]
    completed = await settled(host, task_id)
    assert completed.inputs == {"directory": "/allowed"}

    selected["directory"] = "/changed-after-acceptance"
    replay = await host.client.post(
        PREFIX + "/actions/list-directory/tasks",
        json=body,
    )
    assert replay.status_code == 202
    assert replay.json()["task"]["task_id"] == task_id

    denied = await host.client.post(
        PREFIX + "/actions/list-directory/tasks",
        json={
            **body,
            "request_id": "directory-request-denied",
            "inputs": {"directory": "/denied"},
        },
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "action_forbidden"


async def test_operator_manages_live_digest_pinned_action_grants(host):
    path = "/api/pawapps/workspaces/sales/task-grants"

    initial = await host.client.get(path)
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["revision"] == 0
    assert payload["actions"] == [
        {
            "app_id": "qwenpaw-data",
            "action_id": "analyze",
            "summary": ACTION.summary,
            "descriptor_digest": ACTION.descriptor_digest,
            "input_schema": ACTION.input_schema,
            "permissions": list(ACTION.permissions),
            "effects": list(ACTION.effects),
            "settings_entry": "/apps/qwenpaw-data",
            "enabled": True,
            "stale": False,
            "input_values": {"datasource_id": ["sales"]},
        },
    ]

    changed = await host.client.put(
        path + "/actions/qwenpaw-data/analyze",
        json={
            "expected_revision": 0,
            "enabled": True,
            "input_values": {"datasource_id": ["sales", "forecast"]},
        },
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == 1
    saved = TaskPolicy.model_validate_json(host.policy_path.read_text())
    assert saved.revision == 1
    assert saved.grants[0].descriptor_digest == ACTION.descriptor_digest
    assert saved.grants[0].input_values == {
        "datasource_id": ["sales", "forecast"],
    }

    conflict = await host.client.put(
        path + "/actions/qwenpaw-data/analyze",
        json={"expected_revision": 0, "enabled": False},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "task_policy_conflict"

    revoked = await host.client.put(
        path + "/actions/qwenpaw-data/analyze",
        json={"expected_revision": 1, "enabled": False},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revision"] == 2
    assert revoked.json()["actions"][0]["enabled"] is False
    forbidden = await host.client.get(PREFIX + "/actions/analyze")
    assert forbidden.status_code == 403


async def test_capability_grant_updates_bundle_atomically(host):
    second_action = ActionDescriptor.model_validate(
        {
            **ACTION.model_dump(mode="python"),
            "action_id": "list-records",
            "summary": "List approved records.",
            "adapter_ref": "fixture.list-records.v1",
        },
    )
    host.registrations[(SCOPE.app_id, second_action.action_id)] = (
        ActionRegistration(
            action=second_action,
            factory=lambda: Executor(host.runs),
            settings_entry="/apps/qwenpaw-data",
            capability_id="data_analysis",
            capability_label="Analyze data",
            capability_summary=(
                "Run governed analysis against an approved data source."
            ),
            capability_risk="analysis",
        )
    )
    runtime = host.app.state.pawapp_tasks
    catalog = await runtime.grant_catalog(
        SCOPE.principal_id,
        SCOPE.workspace_id,
    )
    capability = next(
        item
        for item in catalog["capabilities"]
        if item["capability_id"] == "data_analysis"
    )
    assert capability["action_ids"] == ["analyze", "list-records"]
    assert capability["partial"] is True

    path = "/api/pawapps/workspaces/sales/task-grants"
    granted = await host.client.put(
        path + "/capabilities/qwenpaw-data/data_analysis",
        json={"expected_revision": 0, "enabled": True},
    )
    assert granted.status_code == 200
    assert granted.json()["revision"] == 1
    assert granted.json()["capabilities"][0]["enabled"] is True

    saved = TaskPolicy.model_validate_json(host.policy_path.read_text())
    assert [grant.action_id for grant in saved.grants] == [
        "analyze",
        "list-records",
    ]
    assert saved.grants[0].input_values == {
        "datasource_id": ["sales"],
    }
    assert saved.grants[1].input_values == {}

    revoked = await host.client.put(
        path + "/capabilities/qwenpaw-data/data_analysis",
        json={"expected_revision": 1, "enabled": False},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revision"] == 2
    assert TaskPolicy.model_validate_json(
        host.policy_path.read_text(),
    ).grants == ()


async def test_grant_management_rejects_forged_scope_and_constraints(host):
    path = "/api/pawapps/workspaces/sales/task-grants"

    forged = await host.client.get(
        path,
        headers={"X-Agent-Id": "another-workspace"},
    )
    assert forged.status_code == 403
    assert forged.json()["detail"] == "task_scope_mismatch"

    invalid = await host.client.put(
        path + "/actions/qwenpaw-data/analyze",
        json={
            "expected_revision": 0,
            "enabled": True,
            "input_values": {"unknown_resource": ["sales"]},
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_grant_constraints"
    assert (
        TaskPolicy.model_validate_json(
            host.policy_path.read_text(),
        ).revision
        == 0
    )


async def test_private_action_is_not_publicly_exposed_or_dispatchable(host):
    private_action = ActionDescriptor.model_validate(
        {
            **ACTION.model_dump(mode="python"),
            "action_id": "internal-analyze",
            "summary": "Analyze data inside the App.",
            "adapter_ref": "fixture.internal-analyze.v1",
        },
    )
    private_registration = ActionRegistration(
        action=private_action,
        factory=lambda: Executor(host.runs),
        settings_entry="/apps/qwenpaw-data",
        exposure="app_private",
    )
    private_key = (SCOPE.app_id, private_action.action_id)
    host.registrations[private_key] = private_registration
    runtime = host.app.state.pawapp_tasks

    catalog = await runtime.catalog(SCOPE.principal_id, SCOPE.workspace_id)
    assert [item["action_id"] for item in catalog] == [ACTION.action_id]
    grant_catalog = await runtime.grant_catalog(
        SCOPE.principal_id,
        SCOPE.workspace_id,
    )
    assert [item["action_id"] for item in grant_catalog["actions"]] == [
        ACTION.action_id,
    ]

    with pytest.raises(TaskStoreError) as hidden:
        await runtime.describe(SCOPE, private_action.action_id)
    assert hidden.value.code == "action_not_found"

    with pytest.raises(TaskStoreError) as immutable:
        await runtime.set_action_grant(
            SCOPE,
            private_action.action_id,
            enabled=True,
            input_values={},
            expected_revision=0,
        )
    assert immutable.value.code == "action_not_found"
    policy = await runtime.policy.read()
    assert policy.revision == 0
    assert [grant.action_id for grant in policy.grants] == [ACTION.action_id]

    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    with pytest.raises(TaskStoreError) as rejected:
        await runtime.dispatch(
            SCOPE,
            private_action.action_id,
            request_id="private-request",
            inputs=BODY["inputs"],
            origin=origin,
        )
    assert rejected.value.code == "action_not_found"
    assert await host.store.find_request(SCOPE, "private-request") is None


async def test_create_video_grant_cannot_authorize_private_actions(host):
    public_action = ActionDescriptor.model_validate(
        {
            **ACTION.model_dump(mode="python"),
            "action_id": "create-video",
            "summary": "Create a video.",
            "adapter_ref": "fixture.create-video.v1",
        },
    )
    private_actions = tuple(
        ActionDescriptor.model_validate(
            {
                **ACTION.model_dump(mode="python"),
                "action_id": action_id,
                "summary": f"Run private {action_id} work.",
                "adapter_ref": f"fixture.{action_id}.v1",
            },
        )
        for action_id in ("generate-storyboard", "generate-video")
    )
    await host.app.state.pawapp_tasks.aclose()
    host.registrations.clear()
    public_key = (SCOPE.app_id, public_action.action_id)
    host.registrations[public_key] = ActionRegistration(
        action=public_action,
        factory=lambda: Executor(host.runs),
        settings_entry="/apps/qwenpaw-data",
    )
    for private_action in private_actions:
        host.registrations[(SCOPE.app_id, private_action.action_id)] = (
            ActionRegistration(
                action=private_action,
                factory=lambda: Executor(host.runs),
                settings_entry="/apps/qwenpaw-data",
                exposure="app_private",
            )
        )
    host.policy_path.write_text(
        TaskPolicy(
            grants=(
                TaskGrant(
                    scope=SCOPE,
                    action_id=public_action.action_id,
                    descriptor_digest=public_action.descriptor_digest,
                    input_values={"datasource_id": ["sales"]},
                ),
            ),
        ).model_dump_json(),
    )
    runtime = host.runtime(host.store)
    host.app.state.pawapp_tasks = runtime
    await runtime.start()
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )

    accepted = await runtime.dispatch(
        SCOPE,
        public_action.action_id,
        request_id="create-video-request",
        inputs=BODY["inputs"],
        origin=origin,
    )
    assert accepted["task"].action_id == "create-video"

    for private_action in private_actions:
        request_id = f"private-{private_action.action_id}-request"
        with pytest.raises(TaskStoreError) as rejected:
            await runtime.dispatch(
                SCOPE,
                private_action.action_id,
                request_id=request_id,
                inputs=BODY["inputs"],
                origin=origin,
            )
        assert rejected.value.code == "action_not_found"
        assert await host.store.find_request(SCOPE, request_id) is None


async def test_grant_catalog_marks_changed_descriptors_for_review(host):
    host.policy_path.write_text(
        TaskPolicy(
            revision=8,
            grants=(
                TaskGrant(
                    scope=SCOPE,
                    action_id=ACTION.action_id,
                    descriptor_digest="0" * 64,
                    input_values={"datasource_id": ["sales"]},
                ),
            ),
        ).model_dump_json(),
    )

    response = await host.client.get(
        "/api/pawapps/workspaces/sales/task-grants",
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 8
    action = response.json()["actions"][0]
    assert action["enabled"] is False
    assert action["stale"] is True
    assert action["input_values"] == {}


async def test_open_task_issues_scoped_handoff_to_existing_project(host):
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    task_id = response.json()["task"]["task_id"]
    submission = await settled(host, task_id)

    opened = await host.client.post(PREFIX + f"/tasks/{task_id}/open")
    assert opened.status_code == 200
    action = opened.json()["action"]
    assert action["project_ref"] == submission.handle.project_ref.model_dump(
        mode="json",
    )
    expected_path = f"/apps/qwenpaw-data?handoff={action['handoff_id']}"
    assert action["path"] == expected_path
    assert "private prompt" not in action["path"]
    replay = await host.client.post(PREFIX + f"/tasks/{task_id}/open")
    assert replay.json()["action"] == action

    resolved = await host.client.get(
        PREFIX + f"/handoffs/{action['handoff_id']}",
    )
    assert resolved.status_code == 200
    context = resolved.json()["handoff"]["context"]
    assert context["project_ref"] == action["project_ref"]

    denied = await host.client.get(
        PREFIX + f"/handoffs/{action['handoff_id']}",
        headers={"Authorization": "Bearer bob-token"},
    )
    assert denied.status_code == 404
    wrong_app = await host.client.get(
        "/api/pawapps/other/workspaces/sales/handoffs/" + action["handoff_id"],
    )
    assert wrong_app.status_code == 404


async def test_artifact_content_rejects_another_principal(host):
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    task_id = response.json()["task"]["task_id"]
    submission = await settled(host, task_id)
    content = b"report"
    ref = await host.artifacts.publish(
        submission,
        {
            "source_id": "source-1",
            "name": "report.md",
            "path": "reports/report.md",
            "media_type": "text/markdown",
            "size_bytes": len(content),
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        },
        content,
    )
    artifact_path = f"/artifacts/{ref.artifact_id}"
    path = PREFIX + artifact_path + f"/versions/{ref.version}/content"
    allowed = await host.client.get(path)
    assert allowed.status_code == 200
    assert allowed.content == content
    forbidden = await host.client.get(
        path,
        headers={"Authorization": "Bearer bob-token"},
    )
    assert forbidden.status_code == 404


async def test_artifact_collection_route_is_scoped(host):
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    task_id = response.json()["task"]["task_id"]
    submission = await settled(host, task_id)
    content = b"report"
    ref = await host.artifacts.publish(
        submission,
        {
            "source_id": "source-collection",
            "name": "report.md",
            "path": "reports/report.md",
            "media_type": "text/markdown",
            "size_bytes": len(content),
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        },
        content,
    )

    collection = await host.client.get(PREFIX + "/artifacts")
    assert collection.status_code == 200
    assert collection.json()["items"][0]["artifact_id"] == ref.artifact_id
    assert collection.json()["total_count"] >= 1

    filtered = await host.client.get(
        PREFIX + "/artifacts?media_type=video/mp4",
    )
    assert filtered.status_code == 200
    assert filtered.json()["total_count"] == 0

    forbidden = await host.client.get(
        PREFIX + "/artifacts",
        headers={"Authorization": "Bearer bob-token"},
    )
    assert forbidden.status_code == 200
    assert forbidden.json()["total_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "engagement,chat_id",
    [("direct", "direct"), ("delegated", "main")],
)
async def test_authenticated_dispatch_and_replay(host, engagement, chat_id):
    body = {**BODY, "engagement": engagement, "chat_id": chat_id}
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=body,
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["task_id"]
    result = await settled(host, task_id)
    assert result.handle.text_result == "42"
    again = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=body,
    )
    assert again.json()["task"]["task_id"] == task_id
    assert len(host.runs) == 1
    read = await host.client.get(PREFIX + "/tasks/" + task_id)
    assert "inputs" not in read.json()
    events = await host.client.get(PREFIX + f"/tasks/{task_id}/events?after=1")
    assert all(event["sequence"] > 1 for event in events.json()["events"])
    deliveries = await host.store.pending_deliveries(SCOPE, task_id)
    assert any(d.kind == "continuation" for d in deliveries) == (
        engagement == "delegated"
    )


@pytest.mark.asyncio
async def test_authentication_and_each_scope_claim(host):
    url = PREFIX + "/actions/analyze/tasks"
    host.client.headers.pop("Authorization")
    assert (await host.client.post(url, json=BODY)).status_code == 401
    host.client.headers["Authorization"] = "Bearer alice-token"
    for headers, query in (
        ({"X-User-Id": "bob"}, "?user_id=alice"),
        ({"X-Channel": "other"}, "?channel=console"),
        ({"X-Agent-Id": "other"}, ""),
        ({"X-PawApp-Id": "other"}, ""),
        ({}, "?user_id=alice&user_id=bob"),
    ):
        response = await host.client.post(
            url + query,
            json=BODY,
            headers=headers,
        )
        assert response.status_code == 403
    injected = await host.client.post(
        url,
        json={**BODY, "principal_id": "bob"},
    )
    assert injected.status_code == 422
    assert not host.runs


@pytest.mark.asyncio
async def test_policy_resources_and_origin_ownership(host):
    url = PREFIX + "/actions/analyze/tasks"
    for body, status in (
        ({**BODY, "chat_id": "bob"}, 404),
        ({**BODY, "chat_id": "direct"}, 404),
        ({**BODY, "engagement": "direct"}, 404),
        (
            {**BODY, "inputs": {**BODY["inputs"], "datasource_id": "payroll"}},
            403,
        ),
    ):
        assert (await host.client.post(url, json=body)).status_code == status
    host.policy_path.unlink()
    assert (await host.client.post(url, json=BODY)).status_code == 403
    assert not host.runs
    with sqlite3.connect(host.store.path) as db:
        audit = db.execute("SELECT outcome FROM task_audit").fetchall()
        assert ("action_forbidden",) in audit
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_blocked_setup_creates_no_task_or_latent_execution(host):
    host.adapters[0].ready = Readiness(
        state="blocked",
        reason="analysis_model_missing",
    )
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    assert response.status_code == 200
    assert response.json() == {
        "state": "blocked",
        "reason": "analysis_model_missing",
        "setup": "unsupported_setup",
        "settings_entry": "/apps/qwenpaw-data",
    }
    assert await host.store.find_request(SCOPE, BODY["request_id"]) is None
    host.adapters[0].ready = Readiness(state="ready")
    await asyncio.sleep(0.03)
    assert not host.runs
    ready = await host.client.post(
        PREFIX + "/actions/analyze/prepare",
        json=BODY,
    )
    assert ready.json() == {"state": "ready"}
    assert not host.runs


@pytest.mark.asyncio
async def test_answer_and_cancel_routes_use_scoped_durable_commands(host):
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    waiting = await host.store.create(
        SCOPE,
        ACTION,
        request_id="waiting-route",
        inputs=BODY["inputs"],
        origin=origin,
    )
    await host.store.begin_submission(SCOPE, waiting.handle.task_id)
    ref = ExecutorRunRef(
        executor_id="engine",
        session_id="session-waiting-route",
        run_id="run-waiting-route",
    )
    host.runs[waiting.handle.submission_id] = ref
    await host.store.record_accepted(SCOPE, waiting.handle.task_id, ref)
    await host.store.apply_event(
        SCOPE,
        waiting.handle.task_id,
        ExecutorEvent(
            run_ref=ref,
            sequence=0,
            cursor="0",
            status="waiting_for_input",
            detail={
                "input_request": {
                    "request_id": "question-route",
                    "questions": [
                        {
                            "question": "Which period?",
                            "options": [{"label": "Q1"}, {"label": "Q2"}],
                        },
                    ],
                },
            },
        ),
    )
    host.adapters[0].release.clear()
    answer = await host.client.post(
        PREFIX + f"/tasks/{waiting.handle.task_id}/answer",
        json={
            "command_id": "answer-route",
            "request_id": "question-route",
            "answers": [
                {
                    "question": "Which period?",
                    "selected_options": ["Q1"],
                },
            ],
        },
    )
    assert answer.status_code == 200
    assert answer.json()["command"]["state"] == "accepted"
    assert (
        await host.client.post(
            PREFIX + f"/tasks/{waiting.handle.task_id}/answer",
            json={
                "command_id": "answer-route",
                "request_id": "question-route",
                "answers": [
                    {
                        "question": "Which period?",
                        "selected_options": ["Q1"],
                    },
                ],
            },
        )
    ).json() == answer.json()
    assert (
        await host.client.get(
            PREFIX + f"/tasks/{waiting.handle.task_id}",
            headers={"Authorization": "Bearer bob-token"},
        )
    ).status_code == 404

    pending = await host.store.create(
        SCOPE,
        ACTION,
        request_id="cancel-route",
        inputs=BODY["inputs"],
        origin=origin,
    )
    cancelled = await host.client.post(
        PREFIX + f"/tasks/{pending.handle.task_id}/cancel",
        json={"reason": "No longer needed"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["command"]["state"] == "accepted"
    assert (
        await host.store.get(SCOPE, pending.handle.task_id)
    ).handle.status == "cancelled"


@pytest.mark.asyncio
async def test_answer_route_accepts_approval_waits(host):
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    waiting = await host.store.create(
        SCOPE,
        ACTION,
        request_id="approval-route",
        inputs=BODY["inputs"],
        origin=origin,
    )
    await host.store.begin_submission(SCOPE, waiting.handle.task_id)
    ref = ExecutorRunRef(
        executor_id="engine",
        session_id="session-approval-route",
        run_id="run-approval-route",
    )
    host.runs[waiting.handle.submission_id] = ref
    await host.store.record_accepted(SCOPE, waiting.handle.task_id, ref)
    await host.store.apply_event(
        SCOPE,
        waiting.handle.task_id,
        ExecutorEvent(
            run_ref=ref,
            sequence=0,
            cursor="approval",
            status="waiting_for_approval",
            detail={
                "input_request": {
                    "request_id": "approval-request",
                    "questions": [
                        {
                            "question": "Run once?",
                            "options": [
                                {"label": "Approve once"},
                                {"label": "Do not run"},
                            ],
                        },
                    ],
                },
            },
        ),
    )
    host.adapters[0].release.clear()

    response = await host.client.post(
        PREFIX + f"/tasks/{waiting.handle.task_id}/answer",
        json={
            "command_id": "approval-answer",
            "request_id": "approval-request",
            "answers": [
                {
                    "question": "Run once?",
                    "selected_options": ["Approve once"],
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["command"]["state"] == "accepted"
    assert host.adapters[0].command_calls == [
        (waiting.handle.task_id, "approval-answer"),
    ]


@pytest.mark.asyncio
async def test_command_wake_is_replayed_after_active_worker_exits(
    host,
    tmp_path,
):
    store = await TaskStore.open(tmp_path / "rewake.db")
    runtime = host.runtime(store)
    await runtime._sync()
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    task = await store.create(
        SCOPE,
        ACTION,
        request_id="rewake",
        inputs=BODY["inputs"],
        origin=origin,
    )
    blocker = asyncio.create_task(asyncio.Event().wait())
    key = (SCOPE.app_id, ACTION.action_id)
    runtime._workers[task.handle.task_id] = (key, blocker)
    runtime._retry_at[task.handle.task_id] = float("inf")
    runtime._wake(task, force=True)
    assert task.handle.task_id in runtime._forced_rewake
    blocker.cancel()
    await asyncio.gather(blocker, return_exceptions=True)
    await asyncio.sleep(0)
    assert runtime._workers[task.handle.task_id][1] is not blocker
    await runtime.aclose()


@pytest.mark.asyncio
async def test_read_scope_and_idempotency_conflict(host):
    url = PREFIX + "/actions/analyze/tasks"
    response = await host.client.post(url, json=BODY)
    task_id = response.json()["task"]["task_id"]
    await settled(host, task_id)
    other = {**BODY, "inputs": {**BODY["inputs"], "text": "changed"}}
    assert (await host.client.post(url, json=other)).status_code == 409
    for suffix in ("", "/events"):
        for prefix, headers in (
            (PREFIX, {"Authorization": "Bearer bob-token"}),
            (PREFIX.replace("sales", "other"), {}),
            (PREFIX.replace("qwenpaw-data", "another-app"), {}),
        ):
            read = await host.client.get(
                prefix + f"/tasks/{task_id}" + suffix,
                headers=headers,
            )
            assert read.status_code == 404


@pytest.mark.asyncio
async def test_restart_reconciles_task_after_action_becomes_private(host):
    host.adapters[0].release.clear()
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    task_id = response.json()["task"]["task_id"]
    async with asyncio.timeout(3):
        while True:
            submission = await host.store.get(SCOPE, task_id)
            if submission.handle.executor_run_ref is not None:
                break
            await asyncio.sleep(0.01)
    await host.app.state.pawapp_tasks.aclose()
    assert host.adapters[0].closed
    key = (SCOPE.app_id, ACTION.action_id)
    host.registrations[key] = replace(
        host.registrations[key],
        exposure="app_private",
    )
    host.store = await TaskStore.open(host.store.path)
    host.app.state.pawapp_tasks = host.runtime(host.store)
    await host.app.state.pawapp_tasks.start()
    completed = await settled(host, task_id)
    assert completed.handle.status == "succeeded"
    task_response = await host.client.get(PREFIX + "/tasks/" + task_id)
    assert task_response.status_code == 200
    assert len(host.runs) == 1


@pytest.mark.asyncio
async def test_unload_stops_consumers_and_closes_adapter(host):
    host.adapters[0].release.clear()
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    task_id = response.json()["task"]["task_id"]
    host.registrations.clear()
    async with asyncio.timeout(3):
        while not host.adapters[0].closed:
            await asyncio.sleep(0.01)
    submission = await host.store.get(SCOPE, task_id)
    assert submission.handle.status != "succeeded"
    action_response = await host.client.get(PREFIX + "/actions/analyze")
    assert action_response.status_code == 404


@pytest.mark.asyncio
async def test_v1_store_migrates_without_losing_work(host):
    await host.app.state.pawapp_tasks.aclose()
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    task = await host.store.create(
        SCOPE,
        ACTION,
        request_id="old",
        inputs=BODY["inputs"],
        origin=origin,
    )
    with sqlite3.connect(host.store.path) as db:
        db.execute("DROP TABLE task_audit")
        db.execute("PRAGMA user_version = 1")
    reopened = await TaskStore.open(host.store.path)
    assert await reopened.get(SCOPE, task.handle.task_id) == task
    assert (await reopened.recoverable())[0] == task
    await reopened.audit(SCOPE, "analyze", "dispatch", "authorized")


def test_action_registration_is_owned_lazy_and_removed_on_unload(monkeypatch):
    from qwenpaw.pawapp import PawApp
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.registry import PluginRegistry

    monkeypatch.setattr(PluginRegistry, "_instance", None)
    registry = PluginRegistry()
    api = PluginApi(plugin_id="qwenpaw-data", config={})
    api.set_registry(registry)
    calls = []
    resolver = AsyncMock()
    registration = ActionRegistration(
        action=ACTION,
        factory=lambda: calls.append(True),
        settings_entry="/apps/qwenpaw-data",
        input_resolver=resolver,
        exposure="app_private",
    )
    app = PawApp("Data", app_id="qwenpaw-data")
    app.task_action(registration).register(api)
    assert not calls
    stored = registry.get_task_actions()[(ACTION.app_id, ACTION.action_id)]
    assert stored.action == ACTION
    assert stored.action is not ACTION
    assert stored.input_resolver is resolver
    assert stored.exposure == "app_private"
    with pytest.raises(ValueError, match="belong"):
        registry.register_task_action("different-app", registration)
    registry.unregister_plugin("qwenpaw-data")
    assert not registry.get_task_actions()


@pytest.mark.asyncio
async def test_recovery_rechecks_revoked_policy_before_readiness_or_send(host):
    await host.app.state.pawapp_tasks.aclose()
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    task = await host.store.create(
        SCOPE,
        ACTION,
        request_id="recover",
        inputs=BODY["inputs"],
        origin=origin,
    )
    host.policy_path.unlink()
    host.app.state.pawapp_tasks = host.runtime(host.store)
    await host.app.state.pawapp_tasks.start()
    async with asyncio.timeout(3):
        while True:
            item = await host.store.get(SCOPE, task.handle.task_id)
            if item.handle.recovery_reason == "action_forbidden":
                break
            await asyncio.sleep(0.01)
    assert not host.runs


@pytest.mark.asyncio
async def test_readiness_rechecked_before_engine_submission(host):
    probes = []

    async def readiness(scope, inputs):
        del scope, inputs
        probes.append(True)
        if len(probes) == 1:
            return Readiness(state="ready")
        return Readiness(state="blocked", reason="analysis_model_missing")

    host.adapters[0].readiness = readiness
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    assert response.status_code == 202
    task_id = response.json()["task"]["task_id"]
    async with asyncio.timeout(3):
        while True:
            item = await host.store.get(SCOPE, task_id)
            if item.handle.recovery_reason == "analysis_model_missing":
                break
            await asyncio.sleep(0.01)
    assert not host.runs
    assert item.handle.status == "pending"


@pytest.mark.asyncio
async def test_generic_setup_blocks_without_creating_latent_task(host):
    # pylint: disable=too-many-statements
    configured = [False]
    opened_requests = []
    requirement = SetupRequirement(
        id="analysis-model",
        summary="Configure an analysis model",
        required_for=(ACTION.action_id,),
        authority="AppLocal",
        setup_entry_ref="agent-models",
        check_ref="data.analysis-model-ready",
    )

    async def check(_scope, _inputs):
        now = time.time()
        return ReadinessResult(
            requirement_id=requirement.id,
            state="ready" if configured[0] else "needs_configuration",
            reason_code=None if configured[0] else "analysis_model_missing",
            checked_revision=3,
            checked_at=now,
            expires_at=now + 30,
        )

    async def open_entry(request):
        opened_requests.append(request.request_id)
        return SetupOpenAction(
            app_id=request.scope.app_id,
            request_id=request.request_id,
            entry_id=request.entry_id,
            presentation=request.presentation,
            path="/apps/qwenpaw-data/settings/models",
        )

    entry = SetupEntryRegistration(
        descriptor=SetupEntryDescriptor(
            id="agent-models",
            entry_ref="data.agent-models",
            focus="analysis-model",
            presentations=("app_entry",),
        ),
        opener=open_entry,
    )
    setup = SetupCoordinator(
        checks=lambda: {
            (SCOPE.app_id, requirement.id): SetupCheckRegistration(
                requirement=requirement,
                checker=check,
            ),
        },
        entries=lambda: {(SCOPE.app_id, "agent-models"): entry},
        store=host.setup_store,
    )
    await host.app.state.pawapp_tasks.aclose()
    current = host.registrations[(SCOPE.app_id, ACTION.action_id)]
    host.registrations[(SCOPE.app_id, ACTION.action_id)] = ActionRegistration(
        action=current.action,
        factory=current.factory,
        settings_entry=current.settings_entry,
        requirement_ids=(requirement.id,),
    )
    host.setup_holder[0] = setup
    host.app.state.pawapp_setup = setup
    host.app.state.pawapp_tasks = host.runtime(host.store)
    await host.app.state.pawapp_tasks.start()

    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )

    assert response.status_code == 200
    assert response.json()["state"] == "blocked"
    assert response.json()["setup"] == "required"
    assert response.json()["setup_entries"] == ["agent-models"]
    assert response.json()["readiness"]["results"][0]["state"] == (
        "needs_configuration"
    )
    assert await host.store.find_request(SCOPE, BODY["request_id"]) is None
    assert not host.runs

    setup_body = {
        "chat_id": BODY["chat_id"],
        "engagement": BODY["engagement"],
        "inputs": BODY["inputs"],
        "presentation": "app_entry",
    }
    created = await host.client.post(
        PREFIX + "/actions/analyze/setup-requests",
        json=setup_body,
        headers={"Idempotency-Key": "setup-intent-1"},
    )
    assert created.status_code == 201, created.text
    assert "private prompt" not in created.text
    request_id = created.json()["request"]["request_id"]
    assert created.json()["request"]["state"] == "requested"
    assert created.json()["request"]["expected_revisions"] == {
        requirement.id: 3,
    }
    replayed = await host.client.post(
        PREFIX + "/actions/analyze/setup-requests",
        json=setup_body,
        headers={"Idempotency-Key": "setup-intent-1"},
    )
    assert replayed.status_code == 200
    assert replayed.headers["X-Idempotent-Replay"] == "true"
    assert replayed.json()["request"]["request_id"] == request_id
    conflict = await host.client.post(
        PREFIX + "/actions/analyze/setup-requests",
        json={**setup_body, "scopes": ["other-scope"]},
        headers={"Idempotency-Key": "setup-intent-1"},
    )
    assert conflict.status_code == 409
    input_conflict = await host.client.post(
        PREFIX + "/actions/analyze/setup-requests",
        json={
            **setup_body,
            "inputs": {**setup_body["inputs"], "text": "changed prompt"},
        },
        headers={"Idempotency-Key": "setup-intent-1"},
    )
    assert input_conflict.status_code == 409
    revision_conflict = await host.client.post(
        PREFIX + "/actions/analyze/setup-requests",
        json={**setup_body, "expected_revisions": {requirement.id: 2}},
        headers={"Idempotency-Key": "setup-intent-2"},
    )
    assert revision_conflict.status_code == 409

    opened = await host.client.post(
        PREFIX + f"/setup-requests/{request_id}/open",
    )
    assert opened.status_code == 200
    assert opened.json()["request"]["state"] == "opened"
    assert opened.json()["open_action"]["path"].startswith(
        "/apps/qwenpaw-data/settings/models",
    )

    saved = await setup.complete(
        SCOPE,
        SetupResult(
            request_id=request_id,
            result_id="setup-result-1",
            outcome="saved",
            changed_requirement_ids=(requirement.id,),
            config_revisions={requirement.id: 1},
        ),
    )
    assert saved.request.state == "saved"
    assert not host.runs
    assert await host.store.find_request(SCOPE, BODY["request_id"]) is None
    queried = await host.client.get(PREFIX + f"/setup-requests/{request_id}")
    assert queried.json()["request"]["state"] == "saved"
    denied = await host.client.get(
        PREFIX + f"/setup-requests/{request_id}",
        headers={"Authorization": "Bearer bob-token"},
    )
    assert denied.status_code == 404
    wrong_app = await host.client.get(
        "/api/pawapps/other/workspaces/sales/setup-requests/" + request_id,
    )
    assert wrong_app.status_code == 404

    cancelled = await host.client.post(
        PREFIX + "/actions/analyze/setup-requests",
        json=setup_body,
        headers={"Idempotency-Key": "setup-intent-cancelled"},
    )
    cancelled_id = cancelled.json()["request"]["request_id"]
    await host.client.post(PREFIX + f"/setup-requests/{cancelled_id}/cancel")
    closed = await host.client.post(
        PREFIX + f"/setup-requests/{cancelled_id}/open",
    )
    assert closed.status_code == 409
    assert opened_requests == [request_id]

    configured[0] = True
    dispatched = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    assert dispatched.status_code == 202, dispatched.text


@pytest.mark.asyncio
@pytest.mark.parametrize("restart_before_retry", [False, True])
async def test_deferred_setup_retry_and_restart_recovery(
    host,
    restart_before_retry,
):
    configured = [False]
    requirement = SetupRequirement(
        id="analysis-model-deferred",
        summary="Configure an analysis model",
        required_for=(ACTION.action_id,),
        authority="AppLocal",
        setup_entry_ref="agent-models",
        check_ref="data.analysis-model-ready",
    )

    async def check(_scope, _inputs):
        now = time.time()
        return ReadinessResult(
            requirement_id=requirement.id,
            state="ready" if configured[0] else "needs_configuration",
            reason_code=None if configured[0] else "analysis_model_missing",
            checked_revision=1,
            checked_at=now,
            expires_at=now + 30,
        )

    async def open_entry(request):
        return SetupOpenAction(
            app_id=request.scope.app_id,
            request_id=request.request_id,
            entry_id=request.entry_id,
            presentation=request.presentation,
            path="/apps/qwenpaw-data/settings/models",
        )

    entry = SetupEntryRegistration(
        descriptor=SetupEntryDescriptor(
            id="agent-models",
            entry_ref="data.agent-models",
            focus="analysis-model",
            presentations=("app_entry",),
        ),
        opener=open_entry,
    )
    setup = SetupCoordinator(
        checks=lambda: {
            (SCOPE.app_id, requirement.id): SetupCheckRegistration(
                requirement=requirement,
                checker=check,
            ),
        },
        entries=lambda: {(SCOPE.app_id, "agent-models"): entry},
        store=host.setup_store,
    )

    def factory():
        adapter = DeferredSetupExecutor(host.runs)
        host.adapters.append(adapter)
        return adapter

    await host.app.state.pawapp_tasks.aclose()
    current = host.registrations[(SCOPE.app_id, ACTION.action_id)]
    host.registrations[(SCOPE.app_id, ACTION.action_id)] = ActionRegistration(
        action=current.action,
        factory=factory,
        settings_entry=current.settings_entry,
        deferred_requirement_ids=(requirement.id,),
    )
    host.setup_holder[0] = setup
    host.app.state.pawapp_setup = setup
    host.app.state.pawapp_tasks = host.runtime(host.store)
    await host.app.state.pawapp_tasks.start()

    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["task_id"]

    async def wait_for_attempt(attempt):
        async with asyncio.timeout(3):
            while True:
                submission = await host.store.get(SCOPE, task_id)
                if submission.handle.setup_attempt == attempt:
                    return submission
                await asyncio.sleep(0.01)

    first = await wait_for_attempt(1)
    first_id = first.handle.setup_request_id
    first_record = await setup.get(SCOPE, first_id)
    assert first_record.request.task_id == task_id
    assert first_record.request.requirement_ids == (requirement.id,)
    assert first_record.request.attempt == 1
    assert first_record.request.input_digest == content_digest(first.inputs)

    await setup.open(SCOPE, first_id)
    await setup.complete(
        SCOPE,
        SetupResult(
            request_id=first_id,
            result_id="setup-result-1",
            outcome="saved",
            changed_requirement_ids=(requirement.id,),
            config_revisions={requirement.id: 2},
        ),
    )
    if restart_before_retry:
        await host.app.state.pawapp_tasks.aclose()
        host.store = await TaskStore.open(host.store.path)
        host.app.state.pawapp_tasks = host.runtime(host.store)
        await host.app.state.pawapp_tasks.start()

    second = await wait_for_attempt(2)
    second_id = second.handle.setup_request_id
    assert second_id != first_id
    second_record = await setup.get(SCOPE, second_id)
    assert second_record.request.attempt == 2
    assert second_record.request.task_id == task_id

    await host.app.state.pawapp_tasks.aclose()
    host.store = await TaskStore.open(host.store.path)
    host.app.state.pawapp_tasks = host.runtime(host.store)
    await host.app.state.pawapp_tasks.start()
    configured[0] = True
    await setup.open(SCOPE, second_id)
    await setup.complete(
        SCOPE,
        SetupResult(
            request_id=second_id,
            result_id="setup-result-2",
            outcome="saved",
            changed_requirement_ids=(requirement.id,),
            config_revisions={requirement.id: 3},
        ),
    )

    completed = await settled(host, task_id)
    assert completed.handle.setup_request_id is None
    assert completed.handle.setup_attempt == 2
    with sqlite3.connect(host.setup_store.path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM setup_requests",
        ).fetchone()[0]
    assert count == 2
