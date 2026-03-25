# -*- coding: utf-8 -*-
"""B2: Workflow preset templates for Agent Teams.

Provides one-call creation of common multi-agent collaboration patterns
with pre-wired task dependencies.

Built-in templates:
  - research-report: 调研 → 起草 → 审查 → 发布
  - code-review:     实现 → 审查 → 修复 → 合并
  - custom:          用户自定义任务列表和依赖关系

Usage:
    from copaw.teams.workflow import create_workflow
    tasks = create_workflow(
        board=task_board,
        template_name="research-report",
        created_by="lead-agent",
        context={"topic": "DeerFlow 架构分析"},
    )
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """A single step in a workflow template."""
    key: str                          # unique key within template, used for dep refs
    title_tpl: str                    # title template, supports {topic} etc.
    description_tpl: str = ""
    depends_on_keys: List[str] = field(default_factory=list)  # keys of predecessor steps
    assigned_to: Optional[str] = None
    priority: str = "normal"
    required_skills: List[str] = field(default_factory=list)
    timeout_minutes: int = 0


# Built-in workflow templates
_TEMPLATES: Dict[str, List[WorkflowStep]] = {
    "research-report": [
        WorkflowStep(
            key="research",
            title_tpl="调研：{topic}",
            description_tpl="收集、整理与 {topic} 相关的资料，形成调研摘要。",
            priority="high",
        ),
        WorkflowStep(
            key="draft",
            title_tpl="起草报告：{topic}",
            description_tpl="基于调研摘要，起草完整报告初稿。",
            depends_on_keys=["research"],
        ),
        WorkflowStep(
            key="review",
            title_tpl="审查报告：{topic}",
            description_tpl="审查报告初稿，提出修改意见或批准。",
            depends_on_keys=["draft"],
        ),
        WorkflowStep(
            key="publish",
            title_tpl="发布：{topic}",
            description_tpl="将审查通过的报告发布到指定渠道。",
            depends_on_keys=["review"],
        ),
    ],
    "code-review": [
        WorkflowStep(
            key="implement",
            title_tpl="实现：{feature}",
            description_tpl="实现功能 {feature}，完成后提交代码。",
            priority="high",
        ),
        WorkflowStep(
            key="review",
            title_tpl="代码审查：{feature}",
            description_tpl="审查 {feature} 的实现，检查代码质量和逻辑正确性。",
            depends_on_keys=["implement"],
        ),
        WorkflowStep(
            key="fix",
            title_tpl="修复问题：{feature}",
            description_tpl="根据审查意见修复 {feature} 中的问题。",
            depends_on_keys=["review"],
        ),
        WorkflowStep(
            key="merge",
            title_tpl="合并：{feature}",
            description_tpl="将 {feature} 的修复合并到主分支。",
            depends_on_keys=["fix"],
        ),
    ],
}


def create_workflow(
    board,  # TaskBoard instance
    template_name: str,
    created_by: str,
    context: Optional[Dict[str, str]] = None,
    steps: Optional[List[Dict]] = None,
    priority: str = "normal",
) -> List:
    """Create a workflow from a template on the given TaskBoard.

    Args:
        board:         TaskBoard instance to create tasks on.
        template_name: One of the built-in template names, or 'custom'.
        created_by:    Agent ID of the workflow creator.
        context:       Variables for title/description templates (e.g. {'topic': '...'}).
        steps:         Required when template_name='custom'. List of step dicts:
                       [{key, title, description, depends_on_keys, assigned_to,
                         priority, required_skills, timeout_minutes}, ...]
        priority:      Default task priority for all steps.

    Returns:
        List of created TeamTask objects in step order.
    """
    context = context or {}

    # Generate a unique workflow_id to group all tasks
    workflow_id = f"wf-{template_name}-{str(uuid4())[:8]}"

    if template_name == "custom":
        if not steps:
            raise ValueError("template_name='custom' requires 'steps' list")
        template = []
        for s in steps:
            template.append(WorkflowStep(
                key=s["key"],
                title_tpl=s.get("title", s["key"]),
                description_tpl=s.get("description", ""),
                depends_on_keys=s.get("depends_on_keys", []),
                assigned_to=s.get("assigned_to"),
                priority=s.get("priority", priority),
                required_skills=s.get("required_skills", []),
                timeout_minutes=s.get("timeout_minutes", 0),
            ))
    else:
        template = _TEMPLATES.get(template_name)
        if not template:
            raise ValueError(
                f"Unknown template '{template_name}'. "
                f"Available: {list(_TEMPLATES.keys()) + ['custom']}"
            )

    # First pass: create all tasks, record key → task_id mapping
    key_to_id: Dict[str, str] = {}
    key_to_task = {}
    for step in template:
        title = step.title_tpl.format(**context)
        description = step.description_tpl.format(**context)
        # Resolve depends_on_keys to actual task IDs from previous steps
        depends_on_ids = [key_to_id[k] for k in step.depends_on_keys if k in key_to_id]
        task = board.add_task(
            title=title,
            description=description,
            created_by=created_by,
            assigned_to=step.assigned_to,
            depends_on=depends_on_ids,
            priority=step.priority or priority,
            required_skills=step.required_skills,
            workflow_id=workflow_id,
        )
        key_to_id[step.key] = task.id
        key_to_task[step.key] = task
        logger.info(
            "Workflow '%s' step '%s' created: task_id=%s, depends_on=%s",
            template_name, step.key, task.id, depends_on_ids,
        )

    created_tasks = [key_to_task[s.key] for s in template]
    logger.info(
        "Workflow '%s' created: %d tasks by %s",
        template_name, len(created_tasks), created_by,
    )
    return created_tasks


def list_templates() -> List[str]:
    """Return names of all built-in workflow templates."""
    return list(_TEMPLATES.keys()) + ["custom"]
