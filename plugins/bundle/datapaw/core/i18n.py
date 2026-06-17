# -*- coding: utf-8 -*-
"""Localized message catalog for DataPaw LLM-facing strings.

DataPaw drives all LLM-facing strings (tool responses, prompt fragments,
`_pending_edits` summaries, `_analysis_environment_hint`, `handle_interrupt`
user messages) through this catalog so they switch with
``agent_config.language``. Developer-facing strings (logger output, HTTP
error detail, code comments, docstrings) stay English regardless of locale.

Public surface:

- ``Lang``: the literal type for accepted language tags.
- ``tr(key, lang, **fmt)``: catalog lookup + ``str.format`` substitution.
  Unknown ``key`` returns the key itself (defensive fallback); unknown
  ``lang`` falls back to ``_DEFAULT_LANG`` (``"zh"``).

Add a new message:

1. Pick a dotted namespace key
   (``module.purpose``, e.g. ``edit.sop_loaded_head``).
2. Add ``{"zh": "...", "en": "..."}`` under that key in ``_MESSAGES``.
3. Reference it at the call site:
   ``tr("module.purpose", self.lang, **fmt)``.
"""
from __future__ import annotations

from typing import Literal


Lang = Literal["zh", "en"]
_DEFAULT_LANG: Lang = "zh"


# Single flat dictionary, key uses dotted namespace by source module.
_MESSAGES: dict[str, dict[str, str]] = {
    # --- path_context.py ---------------------------------------------------
    "path.empty": {
        "zh": "文件路径不能为空",
        "en": "File path must not be empty.",
    },
    "path.skills_unmounted": {
        "zh": "Skills 目录未挂载，无法访问 {target}。",
        "en": "Skills directory is not mounted; cannot access {target}.",
    },
    "path.skills_escape": {
        "zh": (
            "[沙箱安全限制] Skills 路径越界（可能含 ../）：{fp!r} "
            "解析为 {resolved}，必须在 {root} 下。"
        ),
        "en": (
            "[Sandbox] Skills path escapes mount (possibly contains '..'): "
            "{fp!r} resolves to {resolved}, must be under {root}."
        ),
    },
    "path.workspace_escape": {
        "zh": (
            "[沙箱安全限制] 路径越界（可能含 ../）：{fp!r} " "解析为 {resolved}，必须在挂载目录 {root} 下。"
        ),
        "en": (
            "[Sandbox] Path escapes mount (possibly contains '..'): "
            "{fp!r} resolves to {resolved}, must be under {root}."
        ),
    },
    "path.absolute_forbidden": {
        "zh": (
            "[沙箱安全限制] 不允许访问沙箱挂载目录以外的绝对路径："
            "{fp!r}。请使用相对路径（如 'chart.png'）或 /workspace/ 前缀。"
        ),
        "en": (
            "[Sandbox] Absolute paths outside the sandbox mount are "
            "forbidden: {fp!r}. Use a relative path (e.g. 'chart.png') "
            "or a /workspace/ prefix."
        ),
    },
    # --- orchestration/state.py update_subtask_state -----------------------
    "state.node_not_found": {
        "zh": "未找到节点 '{node_id}'。",
        "en": "Node '{node_id}' not found.",
    },
    "state.invalid_state": {
        "zh": (
            "状态 '{state}' 无效，必须是 "
            "todo / in_progress / failed / abandoned 之一。"
        ),
        "en": (
            "Invalid state '{state}'. Must be one of "
            "todo/in_progress/failed/abandoned."
        ),
    },
    "state.already_running": {
        "zh": (
            "已有节点 {ids} 正在执行。"
            "请先完成当前节点"
            "（调用 finish_subtask 或"
            " update_subtask_state 设置为 done/failed），"
            "再开始执行节点 '{node_id}'。"
        ),
        "en": (
            "Nodes {ids} are already in_progress. "
            "Finish them first (call finish_subtask or "
            "update_subtask_state with done/failed) "
            "before starting node '{node_id}'."
        ),
    },
    # --- agents/base.py format_pending_edits -------------------------------
    "edit.sop_unnamed": {
        "zh": "未命名",
        "en": "(unnamed)",
    },
    "edit.sop_loaded_head": {
        "zh": "已加载 SOP 模板「{name}」（{n} 个节点）",
        "en": "SOP template '{name}' loaded ({n} nodes)",
    },
    "edit.sop_loaded_replaced": {
        "zh": "，已替换旧图 {gid}",
        "en": ", replacing old graph {gid}",
    },
    "edit.sop_loaded_body": {
        "zh": (
            "{head}。这是用户提供的执行计划，请按 ready 节点的 deps "
            "顺序逐步执行；如无修改诉求，不要再调用 create_plan。"
        ),
        "en": (
            "{head}. This is the user-provided execution plan; advance "
            "ready nodes in deps order. Do not call create_plan unless "
            "modification is needed."
        ),
    },
    "edit.dag_merged": {
        "zh": (
            "用户修订了任务图「{name}」：\n"
            "- 新增节点：{added}\n"
            "- 修改节点：{modified}（结构变更会重置下游为 todo）\n"
            "- 删除节点：{removed}\n"
            "- 用户显式改变状态：{overridden}\n"
            "- 下游重置为 todo：{downstream_reset}\n"
            "- 已 done 节点保留进度，请勿重新执行。"
        ),
        "en": (
            "The user revised task graph '{name}':\n"
            "- added: {added}\n"
            "- modified: {modified} "
            "(structural changes reset downstream to todo)\n"
            "- removed: {removed}\n"
            "- explicit state overrides: {overridden}\n"
            "- downstream reset to todo: {downstream_reset}\n"
            "- done nodes keep their progress; do not re-execute."
        ),
    },
    "edit.node_edited": {
        "zh": "用户在任务面板修改了节点 `{nid}`：{changes}",
        "en": "User edited node `{nid}` in the task panel: {changes}",
    },
    "edit.node_downstream_reset_warn": {
        "zh": "  → 下游节点 {downstream_reset} 已重置为 todo，需要重跑。",
        "en": "  → downstream nodes {downstream_reset} reset to todo; re-run required.",
    },
    "edit.graph_replaced": {
        "zh": "当前活跃图被前端替换。请检查新的 current_plan 并按其执行。",
        "en": (
            "The active graph was replaced by the frontend. Inspect "
            "current_plan and follow it."
        ),
    },
    "edit.unknown": {
        "zh": "未知外部变更：{raw}",
        "en": "Unknown external edit: {raw}",
    },
    "edit.no_pending": {
        "zh": "(no pending edits)",
        "en": "(no pending edits)",
    },
    "edit.notify_prefix": {
        "zh": "[外部变更通知]",
        "en": "[External edit notice]",
    },
    # --- agents/base.py handle_interrupt -----------------------------------
    "intr.paused_head": {
        "zh": "任务已暂停。当前进度：",
        "en": "Task paused. Current progress:",
    },
    "intr.options": {
        "zh": (
            "你可以：\n"
            "- 直接说「继续」恢复执行\n"
            "- 告诉我需要修改的内容（如「灵敏度改成 2.0」）\n"
            "- 在任务面板中修改后点击继续"
        ),
        "en": (
            "You can:\n"
            "- say 'continue' to resume\n"
            "- tell me what to change (e.g. 'set sensitivity to 2.0')\n"
            "- edit nodes in the task panel and click continue"
        ),
    },
    "intr.no_plan": {
        "zh": "已中断。有什么需要调整的吗？",
        "en": "Interrupted. Anything to adjust?",
    },
    # --- agents/base.py _analysis_environment_hint -------------------------
    "env.hint": {
        "zh": (
            "<datapaw-analysis-environment>\n"
            "当前 DataPaw 分析环境：host workspace。\n"
            "- 命令通过 `execute_shell_command` 执行；工作目录是 agent workspace。\n"
            "- 本机 artifacts 根目录：`{root}`\n"
            "- 引用产物时使用 `artifacts/<session_id>/<graph_id>/<node_id>/...`；"
            "`finish_subtask(files=...)` 的 path 使用相对 artifacts 根的路径"
            "（不带 `artifacts/` 前缀）。\n"
            "</datapaw-analysis-environment>"
        ),
        "en": (
            "<datapaw-analysis-environment>\n"
            "Current DataPaw analysis environment: host workspace.\n"
            "- Run commands via `execute_shell_command`; "
            "the working directory is the agent workspace.\n"
            "- Artifacts root on this host: `{root}`\n"
            "- Reference artifacts as "
            "`artifacts/<session_id>/<graph_id>/<node_id>/...`; "
            "for `finish_subtask(files=...)`, use paths relative to the "
            "artifacts root (no `artifacts/` prefix).\n"
            "</datapaw-analysis-environment>"
        ),
    },
    # --- agents_setup.py ---------------------------------------------------
    "agent.description": {
        "zh": "数据分析多步规划 agent，基于 DAG 任务图分阶段推进",
        "en": (
            "Data-analysis multi-step planning agent driven by a "
            "DAG task graph."
        ),
    },
}


def tr(key: str, lang: str | None = None, **fmt: object) -> str:
    """Look up a localized template and apply ``str.format`` substitution.

    Unknown ``key`` returns the key itself (defensive — should also be
    flagged by a logger.warning, but we never raise here).
    Unknown ``lang`` falls back to ``_DEFAULT_LANG``.
    """
    entry = _MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(lang or _DEFAULT_LANG) or entry.get(_DEFAULT_LANG, key)
    return text.format(**fmt) if fmt else text


__all__ = ["Lang", "tr"]
