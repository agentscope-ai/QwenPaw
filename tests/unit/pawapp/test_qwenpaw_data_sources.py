# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Runtime reconciliation of qwenpaw-data ``source:{id}`` dependencies."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAIN_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "main.py"
)


def _load_backend():
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_data_main_under_test",
        MAIN_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog(*sources: tuple[str, str]) -> dict:
    return {
        "records": [
            {"datasource_id": source_id, "datasource_name": name}
            for source_id, name in sources
        ],
    }


@pytest.mark.asyncio
async def test_source_reconcile_adds_renames_and_removes() -> None:
    module = _load_backend()
    module._gateway.json = AsyncMock(
        return_value=_catalog(("pg", "Demo PG"), ("neo", "Neo4j")),
    )

    await module._reconcile_source_dependencies(force=True)

    assert sorted(module.app.dependencies.ids(prefix="source:")) == [
        "source:neo",
        "source:pg",
    ]

    # One source renamed, the other deleted from the management console.
    module._gateway.json = AsyncMock(return_value=_catalog(("pg", "Prod PG")))
    await module._reconcile_source_dependencies(force=True)

    assert module.app.dependencies.ids(prefix="source:") == ["source:pg"]
    status = await module.app.dependencies.get("source:pg", force=True)
    assert status["display_name"] == "Prod PG"


@pytest.mark.asyncio
async def test_source_reconcile_keeps_catalog_when_service_is_down() -> None:
    module = _load_backend()
    module._gateway.json = AsyncMock(return_value=_catalog(("pg", "Demo PG")))
    await module._reconcile_source_dependencies(force=True)

    module._gateway.json = AsyncMock(
        side_effect=HTTPException(status_code=503),
    )
    await module._reconcile_source_dependencies(force=True)

    # A downed context service must not mass-drop known sources.
    assert module.app.dependencies.ids(prefix="source:") == ["source:pg"]


@pytest.mark.asyncio
async def test_source_reconcile_is_throttled_between_polls() -> None:
    module = _load_backend()
    module._gateway.json = AsyncMock(return_value=_catalog(("pg", "Demo PG")))

    await module._reconcile_source_dependencies(force=True)
    calls_after_first = module._gateway.json.await_count
    # The UI polls every five seconds; unforced runs inside the throttle
    # window must not hit the upstream catalog again.
    await module._reconcile_source_dependencies()

    assert module._gateway.json.await_count == calls_after_first
