# -*- coding: utf-8 -*-
"""Safe conversion of external automations to QwenPaw cron jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ..app.crons.models import CronJobSpec
from .models import SourceScheduledTask

_MAX_PROVENANCE_DEPTH = 4
_MAX_PROVENANCE_ITEMS = 64
_MAX_PROVENANCE_TEXT = 2048
_LOCAL_EXECUTION_ENVIRONMENTS = frozenset(
    {
        "host",
        "local",
        "local-host",
        "local-machine",
        "local_host",
        "local_machine",
        "native",
    },
)


def imported_job_id(provider_id: str, source_id: str) -> str:
    """Return a stable id so repeated imports never duplicate a task."""
    return str(
        uuid5(
            NAMESPACE_URL,
            f"qwenpaw:scheduled-task:{provider_id}:{source_id}",
        ),
    )


def imported_job_source(job: CronJobSpec) -> tuple[str, str] | None:
    """Read a migration source key from a QwenPaw job, if present."""
    for container in (job.meta, job.dispatch.meta):
        portability = container.get("portability")
        if not isinstance(portability, dict):
            continue
        provider = portability.get("source")
        source_id = portability.get("source_id")
        if (
            isinstance(provider, str)
            and provider.strip()
            and isinstance(source_id, str)
            and source_id.strip()
        ):
            return provider.strip(), source_id.strip()
    return None


def _request_input(prompt: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "type": "message",
            "content": [{"type": "text", "text": prompt}],
        },
    ]


def _schedule_payload(task: SourceScheduledTask) -> dict[str, Any]:
    if task.schedule_type == "cron":
        if not task.cron.strip():
            raise ValueError("定时任务缺少 cron 表达式。")
        return {
            "type": "cron",
            "cron": task.cron.strip(),
            "timezone": task.timezone or "UTC",
        }
    if task.schedule_type == "once":
        if task.run_at is None:
            raise ValueError("单次定时任务缺少执行时间。")
        run_at = task.run_at
        if run_at.tzinfo is None:
            raise ValueError("单次定时任务的执行时间缺少时区。")
        if run_at <= datetime.now(timezone.utc):
            raise ValueError("单次定时任务已经过期，仅保留在迁移审计中。")
        return {
            "type": "once",
            "run_at": run_at,
            "timezone": task.timezone or "UTC",
        }
    reason = str(task.metadata.get("unsupported_reason") or "无法等价转换")
    raise ValueError(f"不支持的第三方调度规则：{reason}")


def _bounded_text(value: Any, limit: int = _MAX_PROVENANCE_TEXT) -> str:
    """Return control-free text suitable for persisted provenance."""
    if not isinstance(value, str):
        return ""
    return "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " "
        for character in value[:limit]
    ).strip()


def _bounded_provenance(value: Any, *, depth: int = 0) -> Any:
    """Bound untrusted provider metadata before placing it in a cron job."""
    if depth >= _MAX_PROVENANCE_DEPTH:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:_MAX_PROVENANCE_ITEMS]:
            key = _bounded_text(str(raw_key), 128)
            if not key or key in result:
                continue
            result[key] = _bounded_provenance(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [
            _bounded_provenance(item, depth=depth + 1)
            for item in value[:_MAX_PROVENANCE_ITEMS]
        ]
    return _bounded_text(str(value))


def is_nonlocal_workspace(metadata: dict[str, Any]) -> bool:
    """Identify source workspaces that must never bind to a local path."""
    if _bounded_text(metadata.get("source_target_remote_authority")):
        return True
    if _bounded_text(metadata.get("target_remote_authority")):
        return True
    if metadata.get("remote_unverified") is True:
        return True
    workspace_status = _bounded_text(metadata.get("workspace_status")).lower()
    if workspace_status == "remote_unverified":
        return True
    environment = metadata.get("execution_environment")
    if environment is None or environment == "":
        return False
    if isinstance(environment, dict):
        environment = environment.get("kind") or environment.get("type")
    normalized = _bounded_text(environment).lower().replace(" ", "-")
    return not normalized or normalized not in _LOCAL_EXECUTION_ENVIRONMENTS


def build_imported_job(
    provider_id: str,
    task: SourceScheduledTask,
    *,
    target_user_id: str = "cron",
    target_session_id: str = "",
) -> CronJobSpec:
    """Build an isolated and provenance-rich QwenPaw job.

    This validates structure only.  It deliberately does not execute the
    prompt or probe any command mentioned by it.
    """
    prompt = task.prompt.strip()
    if not prompt:
        raise ValueError("定时任务缺少要交给 Agent 的提示词。")
    source_cwd = _bounded_text(task.cwd)
    source_metadata = _bounded_provenance(task.metadata)
    if not isinstance(source_metadata, dict):
        source_metadata = {}
    nonlocal_workspace = is_nonlocal_workspace(source_metadata)
    # Never reinterpret a remote/container path as a same-spelled local path.
    # Merely probing it would create a misleading availability claim.
    cwd_available = bool(
        not nonlocal_workspace
        and source_cwd
        and Path(source_cwd).expanduser().is_dir(),
    )
    session_id = target_session_id or (
        f"import:{provider_id}:scheduled:{task.source_id}"
    )
    request_context: dict[str, Any] = {
        "source": "cron",
        "portability_review_required": True,
    }
    if cwd_available:
        request_context["project_dir"] = str(
            Path(source_cwd).expanduser().resolve(),
        )
    portability = {
        "schema_version": "1",
        "source": provider_id,
        "source_id": task.source_id,
        "source_enabled": task.enabled,
        "source_cwd": source_cwd,
        "source_cwd_available": cwd_available,
        "source_cwd_remote_or_unverified": nonlocal_workspace,
        "source_cwd_binding": (
            "omitted_remote_or_unverified"
            if nonlocal_workspace
            else "local"
            if cwd_available
            else "omitted_unavailable"
        ),
        "source_schedule": {
            "type": task.schedule_type,
            "cron": task.cron,
            "run_at": task.run_at.isoformat() if task.run_at else None,
            "timezone": task.timezone,
        },
        "requires_review": True,
        "safety": "disabled_until_explicit_promotion",
        "fidelity": str(task.metadata.get("fidelity") or "converted"),
        "source_metadata": source_metadata,
    }
    return CronJobSpec.model_validate(
        {
            "id": imported_job_id(provider_id, task.source_id),
            "name": task.name.strip() or f"Imported {provider_id} task",
            # Imported schedules require explicit review and a separate
            # enable action before they can run.
            "enabled": False,
            "schedule": _schedule_payload(task),
            "task_type": "agent",
            "request": {
                "input": _request_input(prompt),
                "request_context": request_context,
            },
            "dispatch": {
                "type": "channel",
                "channel": "console",
                "target": {
                    "user_id": target_user_id,
                    "session_id": session_id,
                },
                "mode": "final",
                "silent": True,
                "meta": {"portability": portability},
            },
            "runtime": {
                "max_concurrency": 1,
                "timeout_seconds": 120,
                "misfire_grace_seconds": 60,
                "share_session": False,
                # AUTO keeps risky actions gated if a user later enables it.
                "tool_safety": True,
            },
            "save_result_to_inbox": True,
            "meta": {"portability": portability},
        },
    )


__all__ = [
    "build_imported_job",
    "imported_job_id",
    "imported_job_source",
    "is_nonlocal_workspace",
]
