# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Real Host↔Engine HTTP/SSE and SQLite recovery; no provider calls.

Opt in with QWENPAW_TEST_ENGINE_SOURCE and QWENPAW_TEST_ENGINE_PYTHON pointing
to the compatible Engine checkout and its own installed environment.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from pathlib import Path

import httpx
import pytest

from qwenpaw.pawapp.tasks import (
    TaskCoordinator,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
)
from tests.pawapp_data_task_support import load_data_task_bridge

BRIDGE = load_data_task_bridge()
TOKEN = "pawapp-test-service-token"
SCOPE = TaskScope(
    principal_id="alice",
    workspace_id="sales",
    app_id="qwenpaw-data",
)


class EngineProcess:
    def __init__(self, tmp_path, source, python):
        self.home = tmp_path / "engine"
        self.home.mkdir()
        self.source = source
        self.python = python
        self.base = ""
        self.process = None
        self.log = None

    async def start(self):
        port_file = self.home / "port"
        port_file.unlink(missing_ok=True)
        env = {
            key: os.environ[key]
            for key in (
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "LANG",
                "TMPDIR",
                "TEMP",
                "TMP",
            )
            if key in os.environ
        }
        env.update(
            {
                "PYTHONPATH": os.pathsep.join(
                    str(self.source / "packages" / package / "src")
                    for package in (
                        "qwenpaw-data-host-core",
                        "qwenpaw-data-context",
                        "qwenpaw-data-skills",
                    )
                ),
                "QWENPAW_DATA_HOME": str(self.home),
                "QWENPAW_DATA_API_TOKEN": TOKEN,
                "QWENPAW_DATA_BIZ_LINK_ENABLED": "0",
                "QWENPAW_DATA_FOLLOWUP_ENABLED": "0",
            },
        )
        script = (
            Path(__file__).resolve().parents[1]
            / "fixtures/pawapp_task_engine.py"
        )
        # Owned across start/stop; the fixture's finally closes it.
        # pylint: disable-next=consider-using-with
        self.log = (self.home / "server.log").open("w", encoding="utf-8")
        # pylint: disable-next=consider-using-with
        self.process = subprocess.Popen(
            [str(self.python), str(script), str(self.home), str(port_file)],
            env=env,
            cwd=self.home,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        async with httpx.AsyncClient(trust_env=False, timeout=0.5) as http:
            for _ in range(300):
                if self.process.poll() is not None:
                    break
                if port_file.exists():
                    port = port_file.read_text(encoding="utf-8")
                    if not port.isdecimal():
                        await asyncio.sleep(0.05)
                        continue
                    self.base = f"http://127.0.0.1:{port}"
                    try:
                        if (
                            await http.get(self.base + "/health")
                        ).status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                await asyncio.sleep(0.05)
        await self.stop()
        pytest.fail((self.home / "server.log").read_text(encoding="utf-8"))

    async def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            await asyncio.to_thread(self.process.wait, timeout=10)
        if self.log is not None:
            self.log.close()

    def endpoint(self):
        return self.base, TOKEN

    async def release(self):
        async with httpx.AsyncClient(trust_env=False) as http:
            response = await http.post(
                self.base + "/__test__/release",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            response.raise_for_status()

    def count_runs(self):
        with sqlite3.connect(self.home / "host/host.db") as db:
            return db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]


@pytest.fixture
async def engine(tmp_path):
    source = os.environ.get("QWENPAW_TEST_ENGINE_SOURCE")
    python = os.environ.get("QWENPAW_TEST_ENGINE_PYTHON")
    if not source or not python:
        pytest.skip("requires the protocol-1 Engine checkout and interpreter")
    service = EngineProcess(tmp_path, Path(source), Path(python))
    try:
        await service.start()
        yield service
    finally:
        await service.stop()


async def allow_data(scope, action, origin, inputs):
    """Test policy; production identity/resource checks are separate."""
    assert scope == SCOPE
    assert action.app_id == "qwenpaw-data"
    assert origin.engagement in action.engagements
    assert inputs["datasource_id"] == "sales"


def coordinator(store, adapter):
    result = TaskCoordinator(store, authorize=allow_data)
    result.register(BRIDGE.data_action_descriptor(), adapter)
    return result


def origin(engagement):
    if engagement == "direct":
        return TaskOrigin(
            engagement="direct",
            origin_ref="data:1",
            app_session_ref="data:1",
        )
    return TaskOrigin(
        engagement="delegated",
        origin_ref="main:1",
        return_session_ref="main:1",
    )


async def dispatch(
    boundary,
    engagement="delegated",
    text="finish",
    request_id="r1",
):
    return await boundary.dispatch(
        SCOPE,
        "analyze",
        request_id=request_id,
        inputs={"text": text, "datasource_id": "sales"},
        origin=origin(engagement),
    )


@pytest.mark.parametrize("engagement", ["direct", "delegated"])
async def test_real_engine_dispatch_result_and_delivery(
    tmp_path,
    engine,
    engagement,
):
    store = await TaskStore.open(tmp_path / "host/tasks.db")
    adapter = BRIDGE.DataTaskAdapter(
        engine.endpoint,
        executor_id="engine:test",
    )
    boundary = coordinator(store, adapter)
    try:
        submitted = await dispatch(boundary, engagement)
        result = await asyncio.wait_for(
            boundary.consume(SCOPE, submitted.handle.task_id),
            10,
        )
        assert result.handle.status == "succeeded"
        assert result.handle.text_result == "Revenue is 42."
        retry = await dispatch(boundary, engagement)
        assert retry.handle.task_id == result.handle.task_id
        assert engine.count_runs() == 1
        deliveries = await store.pending_deliveries(
            SCOPE,
            result.handle.task_id,
        )
        assert any(item.kind == "continuation" for item in deliveries) == (
            engagement == "delegated"
        )
        assert {item.target_ref for item in deliveries} == {
            "data:1" if engagement == "direct" else "main:1",
        }
    finally:
        await adapter.aclose()


class LostResponseTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, before_accept):
        self.inner = httpx.AsyncHTTPTransport()
        self.before_accept = before_accept
        self.lost = False

    async def handle_async_request(self, request):
        lose = request.method == "POST" and not self.lost
        if lose and self.before_accept:
            self.lost = True
            raise httpx.ConnectError("test: before acceptance")
        response = await self.inner.handle_async_request(request)
        if lose:
            self.lost = True
            await response.aread()
            await response.aclose()
            raise httpx.ReadError("test: accepted response lost")
        return response

    async def aclose(self):
        await self.inner.aclose()


async def test_concurrent_delegations_keep_separate_runs(tmp_path, engine):
    store = await TaskStore.open(tmp_path / "host/tasks.db")
    adapter = BRIDGE.DataTaskAdapter(
        engine.endpoint,
        executor_id="engine:test",
    )
    boundary = coordinator(store, adapter)
    try:
        submitted = await asyncio.gather(
            *(
                dispatch(boundary, request_id=f"r{index % 3}")
                for index in range(9)
            ),
        )
        tasks = {item.handle.task_id for item in submitted}
        assert len(tasks) == 3
        results = await asyncio.wait_for(
            asyncio.gather(
                *(boundary.consume(SCOPE, task_id) for task_id in tasks),
            ),
            10,
        )
        assert {item.handle.status for item in results} == {"succeeded"}
        assert (
            len({item.handle.executor_run_ref.session_id for item in results})
            == 3
        )
        assert engine.count_runs() == 3
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("before_accept", [True, False])
async def test_host_reopen_reconciles_uncertain_submission(
    tmp_path,
    engine,
    before_accept,
):
    path = tmp_path / "host/tasks.db"
    store = await TaskStore.open(path)
    adapter = BRIDGE.DataTaskAdapter(
        engine.endpoint,
        executor_id="engine:test",
        transport=LostResponseTransport(before_accept=before_accept),
    )
    try:
        with pytest.raises(TaskStoreError, match="engine_unavailable"):
            await dispatch(coordinator(store, adapter))
    finally:
        await adapter.aclose()
    # Resolve the durable Host identity without triggering another submission.
    task = await store.create(
        SCOPE,
        BRIDGE.data_action_descriptor(),
        request_id="r1",
        inputs={"text": "finish", "datasource_id": "sales"},
        origin=origin("delegated"),
    )
    fresh_adapter = BRIDGE.DataTaskAdapter(
        engine.endpoint,
        executor_id="engine:test",
    )
    fresh = coordinator(await TaskStore.open(path), fresh_adapter)
    try:
        accepted = await fresh.reconcile(SCOPE, task.handle.task_id)
        assert accepted.handle.submission_id == task.handle.submission_id
        result = await asyncio.wait_for(
            fresh.consume(SCOPE, task.handle.task_id),
            10,
        )
        assert result.handle.status == "succeeded"
        assert result.handle.text_result == "Revenue is 42."
        assert engine.count_runs() == 1
    finally:
        await fresh_adapter.aclose()


async def wait_for_partial(store, task_id):
    for _ in range(200):
        task = await store.get(SCOPE, task_id)
        if task.handle.text_result == "Revenue is ":
            return task
        await asyncio.sleep(0.02)
    pytest.fail("Host did not persist the partial result")


@pytest.mark.parametrize("restart_engine", [False, True])
async def test_resume_partial_result_after_disconnect_or_engine_restart(
    tmp_path,
    engine,
    restart_engine,
):
    path = tmp_path / "host/tasks.db"
    store = await TaskStore.open(path)
    adapter = BRIDGE.DataTaskAdapter(
        engine.endpoint,
        executor_id="engine:test",
    )
    boundary = coordinator(store, adapter)
    task = await dispatch(boundary, text="pause")
    consumer = asyncio.create_task(
        boundary.consume(SCOPE, task.handle.task_id),
    )
    try:
        partial = await wait_for_partial(store, task.handle.task_id)
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        await adapter.aclose()
    if restart_engine:
        await engine.stop()
        await engine.start()
    else:
        await engine.release()
    fresh_adapter = BRIDGE.DataTaskAdapter(
        engine.endpoint,
        executor_id="engine:test",
    )
    fresh_store = await TaskStore.open(path)
    fresh = coordinator(fresh_store, fresh_adapter)
    try:
        await fresh.reconcile(SCOPE, task.handle.task_id)
        result = await asyncio.wait_for(
            fresh.consume(SCOPE, task.handle.task_id),
            10,
        )
        assert (
            result.handle.executor_run_ref == partial.handle.executor_run_ref
        )
        assert result.handle.status == (
            "interrupted" if restart_engine else "succeeded"
        )
        assert result.handle.text_result == (
            "Revenue is " if restart_engine else "Revenue is 42."
        )
        assert engine.count_runs() == 1
        events = await fresh_store.events(SCOPE, task.handle.task_id)
        source_sequences = [
            item.payload["sequence"]
            for item in events
            if item.kind == "executor"
        ]
        assert len(source_sequences) == len(set(source_sequences))
    finally:
        await fresh_adapter.aclose()
