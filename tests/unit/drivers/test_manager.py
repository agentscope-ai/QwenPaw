# -*- coding: utf-8 -*-
"""Tests for DriverManager startup lifecycle behavior."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import qwenpaw.drivers.manager as manager_module
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import AsyncDriverCardStore


class _MemoryCardStore(AsyncDriverCardStore):
    """Minimal in-memory card store for manager lifecycle tests."""

    def __init__(self, cards: list[DriverCard]) -> None:
        self._cards = {card.name: card for card in cards}

    async def list_paths(self) -> list[Path]:
        return [Path(f"{name}.yaml") for name in self._cards]

    async def load_path(self, path: Path) -> DriverCard:
        return self._cards[path.stem]


def _card(name: str, *, enabled: bool = True) -> DriverCard:
    return DriverCard(
        name=name,
        protocol="test",
        endpoint={},
        enabled=enabled,
    )


def _manager(tmp_path: Path, cards: list[DriverCard]) -> DriverManager:
    return DriverManager(
        cards_dir=tmp_path,
        credential_store=AsyncCredentialStore(tmp_path / "credentials.yaml"),
        card_store=_MemoryCardStore(cards),
    )


def _handler(card: DriverCard) -> SimpleNamespace:
    return SimpleNamespace(
        name=card.name,
        card=card,
        shutdown=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_build_drivers_initializes_enabled_handlers_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cards = [_card("alpha"), _card("beta"), _card("gamma")]
    manager = _manager(tmp_path, cards)
    active = 0
    peak = 0

    async def build_handler(card: DriverCard):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _handler(card)

    monkeypatch.setattr(manager, "_build_and_init_handler", build_handler)

    await manager.build_drivers()

    assert peak == len(cards)
    assert set(manager._handlers) == {"alpha", "beta", "gamma"}


@pytest.mark.asyncio
async def test_build_drivers_bounds_parallel_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cards = [_card(f"driver-{index}") for index in range(6)]
    manager = _manager(tmp_path, cards)
    monkeypatch.setattr(
        manager_module,
        "_DRIVER_STARTUP_CONCURRENCY",
        2,
        raising=False,
    )
    active = 0
    peak = 0

    async def build_handler(card: DriverCard):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _handler(card)

    monkeypatch.setattr(manager, "_build_and_init_handler", build_handler)

    await manager.build_drivers()

    assert peak == 2
    assert len(manager._handlers) == len(cards)


@pytest.mark.asyncio
async def test_build_drivers_isolates_failures_and_skips_disabled_cards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cards = [
        _card("healthy"),
        _card("broken"),
        _card("disabled", enabled=False),
    ]
    manager = _manager(tmp_path, cards)
    old_handler = _handler(_card("old"))
    manager._handlers = {"old": old_handler}
    attempted: list[str] = []

    async def build_handler(card: DriverCard):
        attempted.append(card.name)
        if card.name == "broken":
            raise RuntimeError("failed to connect")
        return _handler(card)

    monkeypatch.setattr(manager, "_build_and_init_handler", build_handler)

    await manager.build_drivers()

    assert attempted == ["healthy", "broken"]
    assert set(manager._handlers) == {"healthy"}
    old_handler.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_drivers_cancellation_closes_unpublished_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cards = [_card("ready"), _card("blocked")]
    manager = _manager(tmp_path, cards)
    old_handler = _handler(_card("old"))
    ready_handler = _handler(cards[0])
    manager._handlers = {"old": old_handler}
    blocked_started = asyncio.Event()
    never_release = asyncio.Event()

    async def build_handler(card: DriverCard):
        if card.name == "ready":
            return ready_handler
        blocked_started.set()
        await never_release.wait()
        return _handler(card)

    monkeypatch.setattr(manager, "_build_and_init_handler", build_handler)
    build_task = asyncio.create_task(manager.build_drivers())
    await asyncio.wait_for(blocked_started.wait(), timeout=1)
    await asyncio.sleep(0)

    build_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await build_task

    ready_handler.shutdown.assert_awaited_once()
    old_handler.shutdown.assert_not_awaited()
    assert manager._handlers == {"old": old_handler}
