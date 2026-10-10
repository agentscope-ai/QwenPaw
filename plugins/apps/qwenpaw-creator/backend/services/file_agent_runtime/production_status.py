# -*- coding: utf-8 -*-
"""Production receipts derived from durable outputs, never model prose."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from services.project_files.models import Project, narrative_timeline_ids

from .work_graph import WorkGraph, WorkNode, WorkNodeStatus


def node_feedback(node: WorkNode, graph: WorkGraph) -> dict[str, Any]:
    """Expose actionable failures and dependencies to the Agent."""
    by_id = graph.by_id
    return {
        "nodeId": node.node_id,
        "label": node.label,
        "status": node.status.value,
        "error": node.error,
        "missing": [
            by_id[reason].label if reason in by_id else reason
            for reason in node.missing
        ],
    }


def production_evidence(
    graph: WorkGraph,
    project: Project,
    requested_node_ids: Iterable[str] = (),
) -> dict[str, Any]:
    requested = set(requested_node_ids)
    bundle = graph.by_id.get("bundle:project")
    return {
        "generation": graph.generation,
        "counts": dict(Counter(node.status.value for node in graph.nodes)),
        "requested": [
            node_feedback(node, graph)
            for node in graph.nodes
            if node.node_id in requested
        ],
        "blockers": [
            node_feedback(node, graph)
            for node in graph.nodes
            if node.status in {WorkNodeStatus.FAILED, WorkNodeStatus.STALE}
        ],
        "bundle": node_feedback(bundle, graph) if bundle else None,
        "unplannedTimelines": (
            [
                project.timelines.items[timeline_id].title or timeline_id
                for timeline_id in narrative_timeline_ids(project)
                if not any(
                    element.enabled
                    for element in project.timelines.items[
                        timeline_id
                    ].elements_by_id.values()
                )
            ]
            if bundle
            else []
        ),
    }


_STATUS_LABELS = {
    "done": "已完成",
    "running": "正在生成",
    "ready": "待派发，尚未开始",
    "waiting_review": "等待审阅",
    "failed": "生成失败，需要修正后重新请求",
    "stale": "已有版本已过期，需要重新生成",
    "gated": "等待前置内容，尚未开始",
}


def production_summary(evidence: dict[str, Any], receipt: str = "") -> str:
    """Own the final production report, including mixed-success requests.

    The model may continue authoring/repairing via tools. Once it ends the
    production turn, neither an optimistic final answer nor its text stream
    may override these verified task and artifact facts.
    """
    lines = ["已核实的制作进度："]
    if receipt:
        lines.append(receipt)
    nodes = evidence["requested"] or evidence["blockers"]
    for node in nodes[:8]:
        lines.append(
            f"- {node['label']}：{_STATUS_LABELS[node['status']]}。",
        )
    if len(nodes) > 8:
        lines.append(f"另有 {len(nodes) - 8} 项可在创作总览中查看。")
    counts = evidence["counts"]
    lines.append(
        "\n当前制作任务："
        f"{counts.get('running', 0)} 项正在生成，"
        f"{counts.get('ready', 0)} 项待派发，"
        f"{counts.get('failed', 0) + counts.get('stale', 0)} 项需要修正或更新，"
        f"{counts.get('gated', 0)} 项等待前置内容，"
        f"{counts.get('waiting_review', 0)} 项等待审阅。",
    )
    if evidence["unplannedTimelines"]:
        lines.append(
            f"还有 {len(evidence['unplannedTimelines'])} 个剧情节点尚未拆分镜头，"
            "未计入已有镜头的完成数量。",
        )
    if bundle := evidence["bundle"]:
        lines.append(
            "互动包所需产物已齐备，可以发起导出。"
            if bundle["status"] == "done"
            else "互动包尚未就绪，暂时不能作为完整作品交付。",
        )
    return "\n".join(lines)
