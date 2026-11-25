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
        "productionStage": project.settings.production_stage,
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
    # In the script stage every media node is gated by the script itself;
    # naming that gate matters, because the generic "waiting for earlier
    # work" wording leaves first-time users without a next action.
    script_gate = evidence.get("productionStage") == "script"
    nodes = evidence["requested"] or evidence["blockers"]
    for node in nodes[:8]:
        status = _STATUS_LABELS[node["status"]]
        if script_gate and node["status"] == "gated":
            status = "等待确认剧本，尚未开始"
        lines.append(f"- {node['label']}：{status}。")
    if len(nodes) > 8:
        lines.append(f"另有 {len(nodes) - 8} 项可在创作总览中查看。")
    counts = evidence["counts"]
    gated_wording = "等待确认剧本" if script_gate else "等待前置内容"
    lines.append(
        "\n当前制作任务："
        f"{counts.get('running', 0)} 项正在生成，"
        f"{counts.get('ready', 0)} 项待派发，"
        f"{counts.get('failed', 0) + counts.get('stale', 0)} 项需要修正或更新，"
        f"{counts.get('gated', 0)} 项{gated_wording}，"
        f"{counts.get('waiting_review', 0)} 项等待审阅。",
    )
    if script_gate and counts.get("gated", 0):
        lines.append(
            "剧本尚未确认：请点击蓝图页顶部的「确认剧本并继续」，" "确认后才会开始生成图片／视频。",
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
