# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""HTTP authorization, blocked setup and lifecycle recovery invariants."""

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app import auth
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.pawapp.tasks import (
    ExecutorEvent,
    ExecutorRunRef,
    SubmissionLookup,
    TaskScope,
    TaskStore,
)
from qwenpaw.pawapp.tasks.binding import ActionRegistration, Readiness
from qwenpaw.pawapp.tasks.policy import FileTaskPolicy, TaskGrant, TaskPolicy
from qwenpaw.pawapp.tasks.routes import HostOrigins, router
from qwenpaw.pawapp.tasks.runtime import HostTaskRuntime
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
        yield ExecutorEvent(
            run_ref=submission.handle.executor_run_ref,
            sequence=0,
            cursor="0",
            status="succeeded",
            text_result="42",
        )

    async def aclose(self):
        self.closed = True


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
        ),
    }

    def runtime(task_store):
        return HostTaskRuntime(
            task_store,
            policy=FileTaskPolicy(policy_path),
            registrations=lambda: registrations,
            authorize_origin=origins,
            interval=0.01,
        )

    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(router, prefix="/api")
    app.state.pawapp_task_origins = origins
    app.state.pawapp_tasks = runtime(store)
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
        )
    await app.state.pawapp_tasks.aclose()


async def settled(host, task_id):
    async with asyncio.timeout(3):
        while True:
            item = await host.store.get(SCOPE, task_id)
            if item.handle.status == "succeeded":
                return item
            await asyncio.sleep(0.01)


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
async def test_host_restart_recovers_accepted_task_without_second_run(host):
    host.adapters[0].release.clear()
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=BODY,
    )
    task_id = response.json()["task"]["task_id"]
    async with asyncio.timeout(3):
        while (
            await host.store.get(SCOPE, task_id)
        ).handle.executor_run_ref is None:
            await asyncio.sleep(0.01)
    await host.app.state.pawapp_tasks.aclose()
    assert host.adapters[0].closed
    host.store = await TaskStore.open(host.store.path)
    host.app.state.pawapp_tasks = host.runtime(host.store)
    await host.app.state.pawapp_tasks.start()
    await settled(host, task_id)
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
    assert (await host.store.get(SCOPE, task_id)).handle.status != "succeeded"
    assert (
        await host.client.get(PREFIX + "/actions/analyze")
    ).status_code == 404


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
    registration = ActionRegistration(
        action=ACTION,
        factory=lambda: calls.append(True),
        settings_entry="/apps/qwenpaw-data",
    )
    app = PawApp("Data", app_id="qwenpaw-data")
    app.task_action(registration).register(api)
    assert not calls
    assert (
        registry.get_task_actions()[(ACTION.app_id, ACTION.action_id)].action
        == ACTION
    )
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
