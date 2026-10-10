# -*- coding: utf-8 -*-
"""Recovering after the native helper goes away.

The capability names a pipe or socket the helper is listening on. It used to be
cached for the life of the process with no way to retire it, so a helper that
crashed left the client reconnecting to a name that answered nothing -- for
every request thereafter, until the backend restarted. The desktop host notices
the dead child and will issue a new capability, but only if asked.
"""

from __future__ import annotations

import pytest

from qwenpaw.app.computer_use import runtime as runtime_module
from qwenpaw.app.computer_use.runtime import (
    HostRuntimeProvider,
    RuntimeCapability,
)


def _capability(pipe: str) -> RuntimeCapability:
    return RuntimeCapability(
        _pipe_name=pipe,
        _secret="secret",
        protocol_version=runtime_module.COMPUTER_USE_PROTOCOL_VERSION,
    )


@pytest.fixture(autouse=True)
def _clean_provider(monkeypatch: pytest.MonkeyPatch):
    """Start from a provider that holds nothing and sees no environment."""
    monkeypatch.setattr(HostRuntimeProvider, "_capability", None)
    monkeypatch.setattr(HostRuntimeProvider, "_environment_spent", False)
    for name in (
        "QWENPAW_COMPUTER_USE_PIPE",
        "QWENPAW_COMPUTER_USE_CAPABILITY",
        "QWENPAW_COMPUTER_USE_PROTOCOL",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    monkeypatch.setattr(HostRuntimeProvider, "_capability", None)
    monkeypatch.setattr(HostRuntimeProvider, "_environment_spent", False)


def test_a_dead_endpoint_is_replaced_by_asking_the_host_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = iter([_capability("pipe-first"), _capability("pipe-second")])
    monkeypatch.setattr(
        runtime_module,
        "_control_endpoint",
        object,
    )
    monkeypatch.setattr(
        runtime_module,
        "_request_capability",
        lambda _control: next(issued),
    )

    first = HostRuntimeProvider.acquire_capability()
    assert first is not None
    assert first.names_same_endpoint(_capability("pipe-first"))
    # Cached, so the host is not troubled again while it works.
    assert HostRuntimeProvider.acquire_capability() is first

    HostRuntimeProvider.invalidate_capability(first)

    second = HostRuntimeProvider.acquire_capability()
    assert second is not None
    assert second.names_same_endpoint(_capability("pipe-second"))


def test_invalidating_an_endpoint_already_replaced_keeps_the_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two clients can fail over the same dead helper at once.

    The second one must not discard the replacement the first already obtained,
    or they would take turns invalidating each other's capability.
    """
    monkeypatch.setattr(runtime_module, "_control_endpoint", object)
    monkeypatch.setattr(
        runtime_module,
        "_request_capability",
        lambda _control: _capability("pipe-new"),
    )
    HostRuntimeProvider.acquire_capability()

    HostRuntimeProvider.invalidate_capability(_capability("pipe-old"))

    held = HostRuntimeProvider.get_capability()
    assert held is not None
    assert held.names_same_endpoint(_capability("pipe-new"))


def test_a_spent_environment_capability_stops_being_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment value is a bootstrap, not a permanent answer.

    It is handed over when the backend is spawned. Once its endpoint is gone,
    returning it again would loop forever, since clearing the cached capability
    cannot clear an environment variable.
    """
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_PIPE", "pipe-from-env")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CAPABILITY", "secret")
    monkeypatch.setenv(
        "QWENPAW_COMPUTER_USE_PROTOCOL",
        str(runtime_module.COMPUTER_USE_PROTOCOL_VERSION),
    )

    injected = HostRuntimeProvider.get_capability()
    assert injected is not None
    assert injected.names_same_endpoint(_capability("pipe-from-env"))

    HostRuntimeProvider.invalidate_capability(injected)

    assert HostRuntimeProvider.get_capability() is None
    # And the next acquire goes to the host rather than back to the
    # environment.
    monkeypatch.setattr(runtime_module, "_control_endpoint", object)
    monkeypatch.setattr(
        runtime_module,
        "_request_capability",
        lambda _control: _capability("pipe-fresh"),
    )
    replacement = HostRuntimeProvider.acquire_capability()
    assert replacement is not None
    assert replacement.names_same_endpoint(_capability("pipe-fresh"))


def test_an_incompatible_desktop_capability_is_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_PIPE", "pipe-old")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CAPABILITY", "secret")
    monkeypatch.setenv(
        "QWENPAW_COMPUTER_USE_PROTOCOL",
        str(runtime_module.COMPUTER_USE_PROTOCOL_VERSION + 1),
    )

    assert HostRuntimeProvider.get_capability() is None


def test_no_host_and_no_environment_means_no_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "_control_endpoint", lambda: None)
    assert HostRuntimeProvider.acquire_capability() is None
