# -*- coding: utf-8 -*-
"""Per-project media call budget: the wallet fuse for unattended runs.

Call counts are the honest spend metric — every task record of a
billable media kind is one provider invocation, counted from durable
facts (no new persisted state, same philosophy as the work graph).
FAILED tasks count too: most failures (safety rejections, quality
retries) happen after the billable request was sent.
"""

from __future__ import annotations

from domain.enums import TaskKind
from domain.errors import ValidationError
from models.config import get_media_call_budget
from services.project_files.facade import CreatorFileServices
from services.runtime_files.execution_store import ProjectExecutionStore


_BILLABLE_KINDS = frozenset(
    {TaskKind.IMAGE_GENERATION, TaskKind.R2V_GENERATION},
)


class MediaCallBudgetExhausted(ValidationError):
    """The project spent its media call budget; a human must raise it."""


def media_call_count(services: CreatorFileServices, project_id: str) -> int:
    store = ProjectExecutionStore(services.root)
    return sum(
        1
        for task in store.list_tasks(project_id)
        if task.kind in _BILLABLE_KINDS
    )


def ensure_media_call_budget(
    services: CreatorFileServices,
    project_id: str,
) -> None:
    """Raise loudly before a billable call once the budget is spent."""

    budget = get_media_call_budget()
    used = media_call_count(services, project_id)
    if used < budget:
        return
    raise MediaCallBudgetExhausted(
        f"项目媒体生成调用已达上限（{used}/{budget} 次）。这是防失控的"
        "安全熔断：请在配置 agent_runtime.media_call_budget 中调高上限后"
        "继续，或由用户确认后重试。",
    )


__all__ = [
    "MediaCallBudgetExhausted",
    "ensure_media_call_budget",
    "media_call_count",
]
