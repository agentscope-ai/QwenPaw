# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.portability.models import SourceScheduledTask
from qwenpaw.portability.scheduled_tasks import (
    build_imported_job,
    imported_job_id,
    imported_job_source,
)


def test_build_imported_job_is_stable_disabled_and_safe(tmp_path) -> None:
    task = SourceScheduledTask(
        source_id="source-task",
        name="Daily report",
        schedule_type="cron",
        cron="0 9 * * 1",
        timezone="Asia/Shanghai",
        prompt="Create the daily report",
        cwd=str(tmp_path),
        enabled=True,
        metadata={"model": "source-only-model"},
    )

    first = build_imported_job("codex", task)
    second = build_imported_job("codex", task)

    assert first.id == second.id == imported_job_id("codex", "source-task")
    assert first.enabled is False
    assert first.schedule.cron == "0 9 * * mon"
    assert first.runtime.tool_safety is True
    assert first.runtime.share_session is False
    assert first.dispatch.silent is True
    assert first.request is not None
    assert first.request.model_dump()["request_context"]["project_dir"] == str(
        tmp_path.resolve(),
    )
    assert imported_job_source(first) == ("codex", "source-task")
    assert first.meta["portability"]["source_enabled"] is True
    assert first.meta["portability"]["requires_review"] is True
    assert "promoted_at" not in first.meta["portability"]
    assert "promoted_by" not in first.meta["portability"]
    assert first.request.request_context["portability_review_required"] is True
    assert first.meta["portability"]["requires_review"] is True


@pytest.mark.parametrize(
    "metadata",
    [
        {"source_target_remote_authority": "ssh-remote+host"},
        {"target_remote_authority": "dev-container"},
        {"remote_unverified": True},
        {"workspace_status": "remote_unverified"},
        {"execution_environment": "cloud"},
    ],
)
def test_build_imported_job_never_binds_remote_cwd_that_exists_locally(
    tmp_path,
    metadata,
) -> None:
    task = SourceScheduledTask(
        source_id="remote-cwd",
        name="Remote workspace",
        schedule_type="cron",
        cron="0 9 * * *",
        prompt="Review the remote repository",
        cwd=str(tmp_path),
        metadata=metadata,
    )

    job = build_imported_job("qoder", task)

    assert job.request is not None
    assert "project_dir" not in job.request.model_dump()["request_context"]
    portability = job.meta["portability"]
    assert portability["source_cwd_available"] is False
    assert portability["source_cwd_remote_or_unverified"] is True
    assert portability["source_cwd_binding"] == (
        "omitted_remote_or_unverified"
    )
    assert portability["requires_review"] is True
