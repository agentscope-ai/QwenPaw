# -*- coding: utf-8 -*-
"""Tests for the guards that keep shared tool state from being corrupted."""
# Both guards are module-private on purpose; exercising them directly is the
# point of these tests.
# pylint: disable=protected-access

import threading

from computer_use_tool import access as access_module
from computer_use_tool import client as client_module
from computer_use_tool import dispatch
from computer_use_tool.protocol import ComputerUseProtocolError


def test_the_rate_limit_cap_holds_under_concurrent_callers():
    # The host runs one event loop per workspace, each on its own thread, so
    # the limiter is reached from several threads at once. This pins the
    # invariant -- the cap is never exceeded -- rather than the mechanism:
    # under the GIL the unguarded read-modify-write is narrow enough that it
    # cannot be made to overshoot here, but that is a property of the current
    # interpreter, not of the code, and a free-threaded build removes it.
    dispatch._action_times.clear()
    refused = []
    barrier = threading.Barrier(8)

    def call() -> None:
        barrier.wait()
        for _ in range(20):
            try:
                dispatch._check_rate_limit()
            except ComputerUseProtocolError as error:
                refused.append(error)
                return

    threads = [threading.Thread(target=call) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(dispatch._action_times) == dispatch._MAX_ACTIONS_PER_MINUTE
    assert refused


def test_the_client_cache_evicts_idle_sessions_when_full(monkeypatch):
    class _Idle:
        has_active_turn = False

    class _Busy:
        has_active_turn = True

    cache = {
        f"idle-{index}": _Idle()
        for index in range(
            client_module._MAX_CACHED_CLIENTS - 1,
        )
    }
    cache["busy"] = _Busy()
    monkeypatch.setattr(client_module, "_clients", cache)

    client_module._evict_idle_clients()

    # The cache was at capacity, so idle sessions are dropped until it is not.
    assert len(cache) < client_module._MAX_CACHED_CLIENTS
    # A session with a turn in flight is never evicted: its client owns the
    # turn id needed to end that turn.
    assert "busy" in cache


def test_the_client_cache_leaves_room_untouched_below_capacity(monkeypatch):
    class _Idle:
        has_active_turn = False

    cache = {"one": _Idle(), "two": _Idle()}
    monkeypatch.setattr(client_module, "_clients", cache)

    client_module._evict_idle_clients()

    assert set(cache) == {"one", "two"}


def test_the_access_store_is_a_single_shared_instance(monkeypatch):
    # Concurrent first-callers on different threads must all receive the same
    # store; without the double-checked lock two could each build one and half
    # the callers would read from an instance the other half never writes to.
    monkeypatch.setattr(access_module, "_access_store", None)
    seen = []
    barrier = threading.Barrier(8)

    def acquire() -> None:
        barrier.wait()
        seen.append(access_module.get_computer_use_access_store())

    threads = [threading.Thread(target=acquire) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(store) for store in seen}) == 1
