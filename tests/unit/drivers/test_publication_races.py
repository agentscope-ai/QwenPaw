# -*- coding: utf-8 -*-
"""Driver publication must not undo a completed policy/configuration update."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from qwenpaw.app.driver_config_service import DriverConfigService
from qwenpaw.drivers.contracts import DriverCard, DriverPolicy
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.errors import DriverCardError, DriverPermissionDeniedError
from qwenpaw.drivers.handler import DriverHandler
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import save_config_card


class Handler(DriverHandler):
    closed = False
    gate = None

    async def _setup(self):
        if self.gate is not None:
            self.gate[0].set()
            await self.gate[1].wait()

    async def _teardown(self):
        self.closed = True

    async def permitted(self):
        try:
            await self._authorize_invocation(
                "user:fixture",
                request_context={"approval_level": "off"},
            )
        except DriverPermissionDeniedError:
            return False
        return True


def card(effect="allow", name="fixture"):
    return DriverCard(
        name=name,
        protocol="fixture",
        endpoint={},
        policy=DriverPolicy(default_effect=effect),
    )


@pytest.fixture
async def manager(tmp_path):
    value = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    value.register_handler_type("fixture", Handler)
    await value.register_driver(card())
    try:
        yield value
    finally:
        await value.shutdown_all()


def hold_next(manager, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    built = []
    original = manager._build_handler

    def build(value):
        result = original(value)
        if not built:
            result.gate = (started, release)
        built.append(result)
        return result

    monkeypatch.setattr(manager, "_build_handler", build)
    return started, release, built


async def stored(manager):
    return await manager.card_store.load("fixture", protocol="fixture")


@pytest.mark.parametrize("operation", ["reload", "register", "build"])
@pytest.mark.parametrize("effect", ["deny", "allow"])
async def test_policy_ack_invalidates_pending_publication(
    manager,
    monkeypatch,
    operation,
    effect,
):
    initial = "allow" if effect == "deny" else "deny"
    await manager.sync_driver_policy(card(initial))
    started, release, built = hold_next(manager, monkeypatch)
    pending = {
        "reload": lambda: manager.reload_driver("fixture"),
        "register": lambda: manager.register_driver(card(initial)),
        "build": manager.build_drivers,
    }[operation]
    task = asyncio.create_task(pending())
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.wait_for(manager.sync_driver_policy(card(effect)), 2)
    assert await manager._handlers["fixture"].permitted() is (
        effect == "allow"
    )
    release.set()
    with pytest.raises(DriverCardError):
        await task
    assert built[0].closed
    assert (await stored(manager)).policy.default_effect == effect
    assert await manager._handlers["fixture"].permitted() is (
        effect == "allow"
    )


@pytest.mark.parametrize(
    "change",
    ["delete", "recreate", "shutdown", "duplicate", "policy-aba"],
)
async def test_pending_reload_cannot_outlive_newer_generation(
    manager,
    monkeypatch,
    change,
):
    started, release, built = hold_next(manager, monkeypatch)
    task = asyncio.create_task(manager.reload_driver("fixture"))
    await asyncio.wait_for(started.wait(), 2)
    if change in ("delete", "recreate"):
        await manager.delete_driver("fixture")
        if change == "recreate":
            await manager.register_driver(card())
    elif change == "shutdown":
        await manager.shutdown_all()
    elif change == "duplicate":
        await manager.reload_driver("fixture")
    else:
        await manager.sync_driver_policy(card("deny"))
        await manager.sync_driver_policy(card("allow"))
    release.set()
    with pytest.raises(DriverCardError):
        await task
    assert built[0].closed
    if change in ("delete", "shutdown"):
        assert "fixture" not in manager._handlers
    else:
        assert manager._handlers["fixture"] is not built[0]


async def test_unrelated_driver_update_does_not_discard_reload(
    manager,
    monkeypatch,
):
    await manager.register_driver(card(name="other"))
    started, release, built = hold_next(manager, monkeypatch)
    task = asyncio.create_task(manager.reload_driver("fixture"))
    await asyncio.wait_for(started.wait(), 2)
    await manager.sync_driver_policy(card("deny", "other"))
    release.set()
    await task
    assert manager._handlers["fixture"] is built[0]
    assert not built[0].closed


@pytest.mark.parametrize("operation", ["reload", "register", "build"])
async def test_cancelled_initialization_closes_candidate(
    manager,
    monkeypatch,
    operation,
):
    started, _, built = hold_next(manager, monkeypatch)
    pending = {
        "reload": lambda: manager.reload_driver("fixture"),
        "register": lambda: manager.register_driver(card()),
        "build": manager.build_drivers,
    }[operation]
    task = asyncio.create_task(pending())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert built[0].closed
    assert manager._handlers["fixture"] is not built[0]


async def test_refresh_reads_under_the_same_policy_transaction(
    manager,
    monkeypatch,
):
    entered, release = asyncio.Event(), asyncio.Event()
    original = manager.card_store.load_path
    first = True

    async def paused(path):
        nonlocal first
        value = await original(path)
        if first:
            first = False
            entered.set()
            await release.wait()
        return value

    monkeypatch.setattr(manager.card_store, "load_path", paused)
    refresh = asyncio.create_task(manager.refresh_driver("fixture"))
    await asyncio.wait_for(entered.wait(), 2)
    deny = asyncio.create_task(manager.sync_driver_policy(card("deny")))
    await asyncio.sleep(0)
    assert not deny.done()
    release.set()
    await refresh
    await deny
    assert not await manager._handlers["fixture"].permitted()
    assert (await stored(manager)).policy.default_effect == "deny"


async def test_service_config_and_policy_writes_merge_only_their_fields(
    manager,
    tmp_path,
):
    service = DriverConfigService(
        SimpleNamespace(workspace_dir=tmp_path, driver_manager=manager),
    )
    stale = await stored(manager)
    await service.save_policy(card("deny"))
    stale.endpoint = {"version": "new"}
    await service.save_card(stale, reload_driver=False)
    assert (await stored(manager)).policy.default_effect == "deny"
    stale_policy = card("allow")
    await service.save_policy(stale_policy)
    assert (await stored(manager)).endpoint == {"version": "new"}
    assert (await stored(manager)).policy.default_effect == "allow"
    # Mail's synchronous writer shares the atomic preserve-policy operation.
    await service.save_policy(card("deny"))
    save_config_card(stale, manager.cards_dir)
    assert (await stored(manager)).policy.default_effect == "deny"


async def test_deleted_policy_target_is_not_recreated(manager):
    await manager.delete_driver("fixture")
    with pytest.raises(DriverCardError):
        await manager.sync_driver_policy(card("deny"))
    assert await manager.card_store.stored_path("fixture") is None


async def test_policy_ack_retires_an_incompatible_active_protocol(manager):
    manager.register_handler_type("replacement", Handler)
    previous = manager._handlers["fixture"]
    current = card("deny")
    current.protocol = "replacement"
    await manager.save_driver_config(current)
    await manager.sync_driver_policy(current)
    assert previous.closed
    assert "fixture" not in manager._handlers


@pytest.mark.parametrize("change", ["remove", "shutdown"])
async def test_transient_initialization_cannot_outlive_cleanup(
    manager,
    monkeypatch,
    change,
):
    started, release, built = hold_next(manager, monkeypatch)
    task = asyncio.create_task(
        manager.replace_transient_drivers("scope", [card(name="transient")]),
    )
    await asyncio.wait_for(started.wait(), 2)
    if change == "remove":
        await manager.remove_transient_drivers("scope")
    else:
        await manager.shutdown_all()
    release.set()
    with pytest.raises(DriverCardError):
        await task
    assert built[0].closed
    assert "transient" not in manager._handlers


async def test_bulk_cancellation_closes_completed_and_pending_candidates(
    manager,
    monkeypatch,
):
    await manager.register_driver(card(name="other"))
    started, _, built = hold_next(manager, monkeypatch)
    task = asyncio.create_task(manager.build_drivers())
    await asyncio.wait_for(started.wait(), 2)
    while len(built) < 2:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(handler.closed for handler in built)


async def test_external_card_change_invalidates_pending_reload(
    manager,
    monkeypatch,
):
    started, release, built = hold_next(manager, monkeypatch)
    task = asyncio.create_task(manager.reload_driver("fixture"))
    await asyncio.wait_for(started.wait(), 2)
    await manager.card_store.save(card("deny"))
    release.set()
    with pytest.raises(DriverCardError):
        await task
    assert built[0].closed
    await manager.refresh_driver("fixture")
    assert not await manager._handlers["fixture"].permitted()


@pytest.mark.parametrize(
    "operation",
    ["policy", "delete", "reload", "register", "build"],
)
async def test_cancelled_retirement_remains_owned_by_manager(
    manager,
    monkeypatch,
    operation,
):
    previous = manager._handlers["fixture"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def teardown():
        entered.set()
        await release.wait()
        previous.closed = True

    monkeypatch.setattr(previous, "_teardown", teardown)
    if operation == "policy":
        manager.register_handler_type("replacement", Handler)
        replacement = card("deny")
        replacement.protocol = "replacement"
        await manager.save_driver_config(replacement)
        pending = manager.sync_driver_policy(replacement)
    else:
        pending = {
            "delete": lambda: manager.delete_driver("fixture"),
            "reload": lambda: manager.reload_driver("fixture"),
            "register": lambda: manager.register_driver(card()),
            "build": manager.build_drivers,
        }[operation]()
    task = asyncio.create_task(pending)
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await manager.shutdown_all()
    assert previous.closed
    assert not manager._cleanup_tasks


@pytest.mark.parametrize(
    "operation",
    ["register", "config", "policy", "delete", "import"],
)
async def test_cancelled_storage_write_finishes_before_next_ack(
    manager,
    monkeypatch,
    operation,
):
    from qwenpaw.drivers import storage

    started, release = threading.Event(), threading.Event()
    target, method = {
        "register": (manager.card_store, "_save_sync"),
        "config": (storage, "save_config_card"),
        "policy": (manager.card_store, "_save_policy_sync"),
        "delete": (manager.card_store, "_delete_sync"),
        "import": (manager.card_store, "_save_if_absent_sync"),
    }[operation]
    original = getattr(target, method)
    first = True

    def paused(*args):
        nonlocal first
        if first:
            first = False
            started.set()
            assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(target, method, paused)
    pending = {
        "register": lambda: manager.register_driver(card()),
        "config": lambda: manager.save_driver_config(card()),
        "policy": lambda: manager.sync_driver_policy(card()),
        "delete": lambda: manager.delete_driver("fixture"),
        "import": lambda: manager.save_driver_if_absent(card()),
    }[operation]()
    task = asyncio.create_task(pending)
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    # Recreate after a cancelled delete; other operations exercise a policy ACK.
    next_update = (
        manager.register_driver(card("deny"))
        if operation == "delete"
        else manager.sync_driver_policy(card("deny"))
    )
    deny = asyncio.create_task(next_update)
    try:
        await asyncio.sleep(0.01)
        assert not task.done()
        assert not deny.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await deny
    assert (await stored(manager)).policy.default_effect == "deny"
    await manager.reload_driver("fixture")
    assert not await manager._handlers["fixture"].permitted()
