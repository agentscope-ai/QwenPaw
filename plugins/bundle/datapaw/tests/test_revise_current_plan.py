# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for batch revise_current_plan."""
import asyncio

from plugin_datapaw.core.orchestration.state import RuntimeStateManager
from plugin_datapaw.core.orchestration.task_graph import (
    PlanNodeChange,
    TaskGraph,
    TaskNode,
)


def _linear_graph() -> TaskGraph:
    return TaskGraph(
        name="Graph",
        description="desc",
        expected_outcome="outcome",
        nodes={
            "n1": TaskNode(
                node_id="n1",
                name="N1",
                description="d1",
                expected_outcome="o1",
                deps=[],
                state="done",
            ),
            "n2": TaskNode(
                node_id="n2",
                name="N2",
                description="d2",
                expected_outcome="o2",
                deps=["n1"],
                state="in_progress",
            ),
            "n3": TaskNode(
                node_id="n3",
                name="N3",
                description="d3",
                expected_outcome="o3",
                deps=["n2"],
                state="todo",
            ),
        },
    )


def test_apply_plan_changes_single_revise_marks_todo_downstream():
    graph = _linear_graph()
    graph.nodes["n3"].state = "in_progress"
    result = graph.apply_plan_changes(
        [
            PlanNodeChange(
                node_id="n2",
                action="revise",
                node=TaskNode(
                    node_id="n2",
                    name="N2 revised",
                    description="new d2",
                    expected_outcome="new o2",
                    deps=["n1"],
                ),
            ),
        ],
    )

    assert result.revised == ["n2"]
    assert result.downstream_reset == ["n3"]
    assert graph.nodes["n2"].state == "todo"
    assert graph.nodes["n2"].name == "N2 revised"
    assert graph.nodes["n3"].state == "todo"
    assert graph.nodes["n1"].state == "done"


def test_apply_plan_changes_batch_mixed_actions():
    graph = _linear_graph()
    result = graph.apply_plan_changes(
        [
            PlanNodeChange(
                node_id="n4",
                action="add",
                node=TaskNode(
                    node_id="n4",
                    name="N4",
                    description="d4",
                    expected_outcome="o4",
                    deps=["n2"],
                ),
            ),
            PlanNodeChange(node_id="n3", action="delete"),
            PlanNodeChange(
                node_id="n2",
                action="revise",
                node=TaskNode(
                    node_id="n2",
                    name="N2 batch",
                    description="d2b",
                    expected_outcome="o2b",
                    deps=["n1"],
                ),
            ),
        ],
    )

    assert result.added == ["n4"]
    assert result.deleted == ["n3"]
    assert result.revised == ["n2"]
    assert "n3" not in graph.nodes
    assert "n4" in graph.nodes
    assert graph.nodes["n2"].state == "todo"


def test_apply_plan_changes_rejects_invalid_atomically():
    graph = _linear_graph()
    before = graph.model_dump(mode="json")

    try:
        graph.apply_plan_changes(
            [
                PlanNodeChange(node_id="missing", action="delete"),
            ],
        )
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert graph.model_dump(mode="json") == before


def test_apply_plan_changes_todo_dedup_across_revised_nodes():
    graph = TaskGraph(
        name="Graph",
        description="desc",
        expected_outcome="outcome",
        nodes={
            "a": TaskNode(
                node_id="a",
                name="A",
                description="d",
                expected_outcome="o",
                deps=[],
                state="done",
            ),
            "b": TaskNode(
                node_id="b",
                name="B",
                description="d",
                expected_outcome="o",
                deps=["a"],
                state="done",
            ),
            "c": TaskNode(
                node_id="c",
                name="C",
                description="d",
                expected_outcome="o",
                deps=["a"],
                state="done",
            ),
            "d": TaskNode(
                node_id="d",
                name="D",
                description="d",
                expected_outcome="o",
                deps=["b", "c"],
                state="in_progress",
            ),
        },
    )
    result = graph.apply_plan_changes(
        [
            PlanNodeChange(
                node_id="b",
                action="revise",
                node=TaskNode(
                    node_id="b",
                    name="B2",
                    description="d",
                    expected_outcome="o",
                    deps=["a"],
                ),
            ),
            PlanNodeChange(
                node_id="c",
                action="revise",
                node=TaskNode(
                    node_id="c",
                    name="C2",
                    description="d",
                    expected_outcome="o",
                    deps=["a"],
                ),
            ),
        ],
    )

    assert result.revised == ["b", "c"]
    assert result.downstream_reset == ["d"]
    assert graph.nodes["d"].state == "todo"


def test_revise_current_plan_tool_sets_plan_mutated_once():
    state = RuntimeStateManager()
    state.current_plan = _linear_graph()
    notify_count = 0

    async def _count_notify(_event_type):
        nonlocal notify_count
        notify_count += 1

    state._notify_graph_change = _count_notify  # type: ignore[method-assign]

    response = asyncio.run(
        state.revise_current_plan(
            [
                PlanNodeChange(
                    node_id="n2",
                    action="revise",
                    node=TaskNode(
                        node_id="n2",
                        name="N2 tool",
                        description="d2",
                        expected_outcome="o2",
                        deps=["n1"],
                    ),
                ),
                PlanNodeChange(node_id="n3", action="delete"),
            ],
        ),
    )

    assert state._plan_just_mutated is True
    assert notify_count == 1
    assert "Applied 2 change(s)" in response.content[0]["text"]
    assert "n3" not in state.current_plan.nodes


def test_apply_plan_changes_rejects_unknown_dep_with_reason():
    graph = _linear_graph()
    before = graph.model_dump(mode="json")

    try:
        graph.apply_plan_changes(
            [
                PlanNodeChange(
                    node_id="n2",
                    action="revise",
                    node=TaskNode(
                        node_id="n2",
                        name="N2",
                        description="d2",
                        expected_outcome="o2",
                        deps=["n9"],
                    ),
                ),
            ],
        )
    except ValueError as exc:
        msg = str(exc)
        assert "Invalid dependency" in msg
        assert "unknown deps" in msg
        assert "n9" in msg
    else:
        raise AssertionError("expected ValueError")

    assert graph.model_dump(mode="json") == before


def test_apply_plan_changes_rejects_self_dependency():
    graph = _linear_graph()

    try:
        graph.apply_plan_changes(
            [
                PlanNodeChange(
                    node_id="n2",
                    action="revise",
                    node=TaskNode(
                        node_id="n2",
                        name="N2",
                        description="d2",
                        expected_outcome="o2",
                        deps=["n2"],
                    ),
                ),
            ],
        )
    except ValueError as exc:
        assert "cannot list itself in deps" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_apply_plan_changes_rejects_cycle_with_reason():
    graph = _linear_graph()
    before = graph.model_dump(mode="json")

    try:
        graph.apply_plan_changes(
            [
                PlanNodeChange(
                    node_id="n1",
                    action="revise",
                    node=TaskNode(
                        node_id="n1",
                        name="N1",
                        description="d1",
                        expected_outcome="o1",
                        deps=["n3"],
                    ),
                ),
            ],
        )
    except ValueError as exc:
        msg = str(exc)
        assert "Invalid topology" in msg
        assert "cycle" in msg.lower()
    else:
        raise AssertionError("expected ValueError")

    assert graph.model_dump(mode="json") == before


def test_apply_plan_changes_rejects_mutual_add_cycle():
    graph = TaskGraph(
        name="Graph",
        description="desc",
        expected_outcome="outcome",
        nodes={},
    )

    try:
        graph.apply_plan_changes(
            [
                PlanNodeChange(
                    node_id="a",
                    action="add",
                    node=TaskNode(
                        node_id="a",
                        name="A",
                        description="d",
                        expected_outcome="o",
                        deps=["b"],
                    ),
                ),
                PlanNodeChange(
                    node_id="b",
                    action="add",
                    node=TaskNode(
                        node_id="b",
                        name="B",
                        description="d",
                        expected_outcome="o",
                        deps=["a"],
                    ),
                ),
            ],
        )
    except ValueError as exc:
        assert "cycle" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_apply_plan_changes_revise_deps_success():
    graph = _linear_graph()
    result = graph.apply_plan_changes(
        [
            PlanNodeChange(
                node_id="n3",
                action="revise",
                node=TaskNode(
                    node_id="n3",
                    name="N3",
                    description="d3",
                    expected_outcome="o3",
                    deps=["n1"],
                ),
            ),
        ],
    )

    assert result.revised == ["n3"]
    assert graph.nodes["n3"].deps == ["n1"]
    assert graph.nodes["n3"].state == "todo"


def _qwenchat_observation_graph() -> TaskGraph:
    return TaskGraph(
        name="QwenChat 12月访问趋势分析",
        description="desc",
        expected_outcome="outcome",
        nodes={
            "n1_data_fetch": TaskNode(
                node_id="n1_data_fetch",
                name="数据获取",
                description="d1",
                expected_outcome="o1",
                deps=[],
            ),
            "n2_metric_observation": TaskNode(
                node_id="n2_metric_observation",
                name="指标基础观测",
                description="d2",
                expected_outcome="o2",
                deps=["n1_data_fetch"],
            ),
            "n3_anomaly_detection": TaskNode(
                node_id="n3_anomaly_detection",
                name="异常波动检测",
                description="d3",
                expected_outcome="o3",
                deps=["n1_data_fetch"],
            ),
            "n4_attribution": TaskNode(
                node_id="n4_attribution",
                name="维度下拆归因",
                description="d4",
                expected_outcome="o4",
                deps=["n2_metric_observation", "n3_anomaly_detection"],
            ),
            "n5_report": TaskNode(
                node_id="n5_report",
                name="报告生成",
                description="d5",
                expected_outcome="o5",
                deps=[
                    "n2_metric_observation",
                    "n3_anomaly_detection",
                    "n4_attribution",
                ],
            ),
        },
    )


def test_apply_plan_changes_add_without_inner_node_id_and_revise_dep():
    graph = _qwenchat_observation_graph()
    result = graph.apply_plan_changes(
        [
            PlanNodeChange(
                node_id="n1_data_fetch_active_user",
                action="add",
                node=TaskNode(
                    name="补充获取激活用户数",
                    description="获取激活用户数日粒度数据",
                    expected_outcome="激活用户数 CSV",
                    deps=[],
                ),
            ),
            PlanNodeChange(
                node_id="n2_metric_observation",
                action="revise",
                node=TaskNode(
                    name="指标基础观测",
                    description="基于多份 CSV 做观测",
                    expected_outcome="观测结果 CSV",
                    deps=["n1_data_fetch", "n1_data_fetch_active_user"],
                ),
            ),
        ],
    )

    assert result.added == ["n1_data_fetch_active_user"]
    assert result.revised == ["n2_metric_observation"]
    assert "n1_data_fetch_active_user" in graph.nodes
    assert graph.nodes["n2_metric_observation"].deps == [
        "n1_data_fetch",
        "n1_data_fetch_active_user",
    ]


def test_apply_plan_changes_rejects_add_node_id_mismatch():
    graph = _linear_graph()

    try:
        graph.apply_plan_changes(
            [
                PlanNodeChange(
                    node_id="n4",
                    action="add",
                    node=TaskNode(
                        node_id="n9",
                        name="N4",
                        description="d4",
                        expected_outcome="o4",
                        deps=[],
                    ),
                ),
            ],
        )
    except ValueError as exc:
        assert "node_id mismatch" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_revise_current_plan_tool_returns_topology_error():
    state = RuntimeStateManager()
    state.current_plan = _linear_graph()

    response = asyncio.run(
        state.revise_current_plan(
            [
                PlanNodeChange(
                    node_id="n2",
                    action="revise",
                    node=TaskNode(
                        node_id="n2",
                        name="N2",
                        description="d2",
                        expected_outcome="o2",
                        deps=["missing"],
                    ),
                ),
            ],
        ),
    )

    text = response.content[0]["text"]
    assert "Invalid dependency" in text
    assert "unknown deps" in text
