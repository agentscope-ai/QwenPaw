# -*- coding: utf-8 -*-
"""Staleness policy for image publishes when the Project moves mid-render.

Reproduces the 2026-08-07 fan-out incident: four storyboards rendered in
parallel, the first commit bumped the generation, and the whole-project
staleness gate quarantined the other three finished (billed) renders.
"""
from __future__ import annotations

import asyncio

import pytest

from domain.errors import ConflictError
from services.media_files.image_execution import FileImageExecutionService
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"fanout-image" * 16

PROJECT_ID = "image-fanout-project"
ELEMENT_ID = "r2v-fanout-1"


class _MutatingImageProvider:
    """Succeeds normally, but commits a Project change mid-render.

    This reproduces the fan-out race: a sibling task's import (or any
    other commit) lands while this render is at the provider, so the
    task's frozen input etag no longer matches at publish time.
    """

    def __init__(self, services: CreatorFileServices, mutate) -> None:
        self._services = services
        self._mutate = mutate
        self.calls = 0

    async def generate(self, **_kwargs):
        self.calls += 1
        base = self._services.projects.read(PROJECT_ID)
        candidate = base.project.model_dump(mode="json")
        self._mutate(candidate)
        self._services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
        )
        return {"content": _PNG, "media_type": "image/png"}


def _element(element_id: str = ELEMENT_ID) -> TimelineElement:
    shot = Shot(
        shot_id=f"{element_id}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=4,
    )
    return TimelineElement(
        element_id=element_id,
        label="猫追老鼠",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="Image Fanout")
    project.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ] = _element()
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    return services


def _execute(services, provider, key="storyboard-key"):
    return asyncio.run(
        FileImageExecutionService(services, provider=provider).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key=key,
        ),
    )


def test_sibling_commit_during_render_does_not_quarantine(
    tmp_path,
    monkeypatch,
) -> None:
    """An etag drift that leaves the render inputs intact still publishes.

    The candidate is rebuilt from the *current* snapshot, so the commit
    boundary already merges disjoint pointers safely — the gate only has
    to recognize that this task's inputs and target are untouched.
    """

    services = _services(tmp_path, monkeypatch)

    def bump_description(candidate: dict) -> None:
        candidate["description"] = "sibling committed while rendering"

    provider = _MutatingImageProvider(services, bump_description)
    result = _execute(services, provider)

    assert result.artifact_version_id
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ]
    assert element.outputs["storyboard"].slot_id == (
        f"element:{ELEMENT_ID}:storyboard"
    )
    assert finished.description == "sibling committed while rendering"


def test_deleted_target_mid_render_still_quarantines(
    tmp_path,
    monkeypatch,
) -> None:
    """Losing the target Element mid-render keeps fail-closed."""

    services = _services(tmp_path, monkeypatch)

    def drop_element(candidate: dict) -> None:
        timeline = candidate["timelines"]["items"]["timeline:main"]
        del timeline["elements_by_id"][ELEMENT_ID]

    provider = _MutatingImageProvider(services, drop_element)
    with pytest.raises(ConflictError, match="结果已隔离"):
        _execute(services, provider)


def test_redispatch_rescues_quarantined_stale_result(
    tmp_path,
    monkeypatch,
) -> None:
    """A quarantined-but-paid render is imported, not re-rendered.

    Re-dispatch with the same idempotency key lands on the terminal
    durable slot; once the render inputs validate again the stored
    result commits without a second provider call (billed once).
    """

    services = _services(tmp_path, monkeypatch)
    removed: dict = {}

    def drop_element(candidate: dict) -> None:
        timeline = candidate["timelines"]["items"]["timeline:main"]
        removed["element"] = timeline["elements_by_id"].pop(ELEMENT_ID)

    provider = _MutatingImageProvider(services, drop_element)
    with pytest.raises(ConflictError, match="结果已隔离"):
        _execute(services, provider)
    assert provider.calls == 1

    # The element comes back (same id), making the stored result valid
    # again — the exact shape of the fan-out incident after its inputs
    # settle.
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    timeline = candidate["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"][ELEMENT_ID] = removed["element"]
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )

    result = _execute(services, provider)

    assert provider.calls == 1  # no second render, no second bill
    assert result.replayed is True
    assert result.artifact_version_id
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ]
    assert element.outputs["storyboard"].slot_id == (
        f"element:{ELEMENT_ID}:storyboard"
    )
