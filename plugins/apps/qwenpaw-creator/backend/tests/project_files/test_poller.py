# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import timedelta
import os

import pytest

from services.project_files.models import Project
from services.project_files.poller import ProjectPoller
from services.project_files.store import ProjectNotFound, ProjectStore


def test_poller_keeps_last_good_when_external_write_is_invalid(
    tmp_path,
) -> None:
    store = ProjectStore(tmp_path.resolve())
    created = store.create(Project.new(project_id="project-1", name="Good"))
    poller = ProjectPoller(store)
    healthy = poller.open("project-1")
    assert healthy.snapshot == created
    assert healthy.sync_status == "healthy"

    target = store.project_path("project-1")
    target.write_text("{invalid", encoding="utf-8")
    os.utime(target, None)
    invalid = poller.poll_once("project-1", force=True)

    assert invalid.sync_status == "invalid"
    assert invalid.snapshot == created
    assert invalid.last_error


def test_note_commit_cannot_roll_cache_back_to_an_older_snapshot(
    tmp_path,
) -> None:
    store = ProjectStore(tmp_path.resolve())
    first = store.create(Project.new(project_id="project-1", name="Initial"))
    poller = ProjectPoller(store)
    poller.open("project-1")
    raw = first.project.model_dump(mode="python")
    raw.update(
        generation=1,
        name="New",
        updated_at=first.project.updated_at + timedelta(seconds=1),
    )
    second = store.replace(
        "project-1",
        Project.model_validate(raw),
        expected_etag=first.etag,
    )

    poller.note_commit(second)
    replay = poller.note_commit(first)

    assert replay.snapshot == second
    assert poller.poll_once("project-1").snapshot == second


def test_poller_evicts_last_good_snapshot_after_project_deletion(
    tmp_path,
) -> None:
    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id="project-1", name="Good"))
    poller = ProjectPoller(store)
    assert poller.open("project-1").snapshot is not None

    store.delete("project-1")

    with pytest.raises(ProjectNotFound):
        poller.poll_once("project-1", force=True)
    assert poller.cached("project-1") is None
