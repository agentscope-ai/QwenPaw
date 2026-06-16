# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DataPaw DAG backing store and broadcaster."""
import asyncio


def test_dag_broadcaster_push_drops_full_queue():
    from plugin_datapaw.core.orchestration.dag_store import DAGBroadcaster

    sid = "s-broadcast"
    queue = DAGBroadcaster.subscribe(sid, maxsize=1)
    try:
        DAGBroadcaster.push(sid, {"n": 1})
        DAGBroadcaster.push(sid, {"n": 2})

        assert queue.get_nowait() == {"n": 1}
        assert queue.empty()
    finally:
        DAGBroadcaster.unsubscribe(sid, queue)


def test_dag_store_write_fans_out_before_persist(tmp_path):
    from plugin_datapaw.core.orchestration.dag_store import DAGStore

    store = DAGStore(tmp_path, user_id="default")
    seen = []

    def on_write(sid, snapshot):
        seen.append(
            (
                sid,
                snapshot,
                store.dag_path(sid).exists(),
            ),
        )

    store.on_write(on_write)

    asyncio.run(store.write("s1", {"current_plan": {"id": "g1"}}))

    assert seen == [
        ("s1", {"current_plan": {"id": "g1"}}, False),
    ]
    assert asyncio.run(store.read("s1")) == {"current_plan": {"id": "g1"}}
    assert store.dag_path("s1") == tmp_path / "dag" / "default_s1.json"
    assert not (tmp_path / "s1" / "dag.json").exists()


def test_runtime_state_notify_writes_dag_store(tmp_path):
    from plugin_datapaw.core.orchestration.dag_store import DAGStore
    from plugin_datapaw.core.orchestration.state import RuntimeStateManager
    from plugin_datapaw.core.orchestration.task_graph import (
        TaskGraph,
        TaskNode,
    )
    from plugin_datapaw.core.orchestration.events import TaskEventType

    state = RuntimeStateManager()
    state.configure_dag_store(
        DAGStore(tmp_path, user_id="default"),
        session_id="s1",
    )
    state.current_plan = TaskGraph(
        name="Graph",
        description="desc",
        expected_outcome="outcome",
        nodes={
            "n1": TaskNode(
                node_id="n1",
                name="Node",
                description="desc",
                expected_outcome="outcome",
            ),
        },
    )

    asyncio.run(state._notify_graph_change(TaskEventType.GRAPH_UPDATED))

    saved = asyncio.run(state._dag_store.read("s1"))
    assert saved["current_plan"]["name"] == "Graph"
    assert saved["current_plan"]["nodes"]["n1"]["name"] == "Node"


def test_tasks_persist_pn_writes_dag_store(tmp_path):
    from plugin_datapaw.core.orchestration.dag_store import DAGStore
    from plugin_datapaw.core.routers.tasks_utils import PnContext, persist_pn

    ctx = PnContext(
        session=object(),
        session_id="s1",
        user_id="u1",
        dag_store=DAGStore(tmp_path, user_id="u1"),
        pn={"current_plan": {"id": "g1"}},
    )

    asyncio.run(persist_pn(ctx))

    assert asyncio.run(ctx.dag_store.read("s1")) == {
        "current_plan": {"id": "g1"},
    }
    assert (tmp_path / "dag" / "u1_s1.json").exists()


def test_format_sse_includes_event_id_and_task_status_event():
    from plugin_datapaw.core.orchestration.dag_store import format_sse

    frame = format_sse({"sequence_number": 7, "current_plan": {"id": "g1"}})

    assert frame.startswith("id: 7\nevent: task_status\n")
    assert '"current_plan": {"id": "g1"}' in frame
    assert frame.endswith("\n\n")
