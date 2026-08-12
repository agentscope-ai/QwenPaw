# -*- coding: utf-8 -*-
"""Artifact coordinator overlap boundaries."""

from pathlib import Path

from qwenpaw.agents.artifacts import ArtifactCoordinator


async def test_complete_rechecks_overlap_after_final_scan(
    tmp_path: Path,
) -> None:
    coordinator = ArtifactCoordinator()
    first = await coordinator.begin(
        "turn-1",
        {"workspace": tmp_path},
    )

    # The final scan for the first turn is in progress here. A late turn
    # must still mark the first turn overlapped before its completion boundary.
    second = await coordinator.begin(
        "turn-2",
        {"workspace": tmp_path},
    )

    assert await coordinator.complete(first) is True
    assert await coordinator.complete(second) is True

    third = await coordinator.begin(
        "turn-3",
        {"workspace": tmp_path},
    )

    assert await coordinator.complete(third) is False
