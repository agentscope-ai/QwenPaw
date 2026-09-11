# -*- coding: utf-8 -*-
"""Whether Computer Use reports itself usable, and on what grounds.

The desktop shell offers a control endpoint on every platform it runs on, but
the native helper is built only for Windows and macOS. Treating the endpoint as
the whole answer registered the tool on Linux, where every call could do
nothing
but report the runtime unavailable.
"""

from __future__ import annotations

import pytest

from qwenpaw.app.computer_use import runtime as runtime_module
from qwenpaw.app.computer_use.runtime import HostRuntimeProvider, RuntimeStatus

_CONTROL_ENV = {
    "QWENPAW_COMPUTER_USE_CONTROL_HOST": "127.0.0.1",
    "QWENPAW_COMPUTER_USE_CONTROL_PORT": "51234",
    "QWENPAW_COMPUTER_USE_CONTROL_TOKEN": "token",
}


@pytest.fixture(autouse=True)
def _reachable_host(monkeypatch: pytest.MonkeyPatch):
    """Present a reachable desktop host, so only the platform varies."""
    for name, value in _CONTROL_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(HostRuntimeProvider, "_capability", None)
    yield
    monkeypatch.setattr(HostRuntimeProvider, "_capability", None)


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_a_platform_with_a_helper_is_available(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    monkeypatch.setattr(runtime_module.sys, "platform", platform)
    status = HostRuntimeProvider.status()
    assert status == RuntimeStatus(
        supported_platform=True,
        host_reachable=True,
    )
    assert HostRuntimeProvider.is_available() is True


@pytest.mark.parametrize("platform", ["linux", "freebsd"])
def test_a_platform_without_a_helper_is_not_available(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    monkeypatch.setattr(runtime_module.sys, "platform", platform)
    status = HostRuntimeProvider.status()
    # The host is reachable, and that used to be the entire test.
    assert status.host_reachable is True
    assert status.supported_platform is False
    assert HostRuntimeProvider.is_available() is False


def test_a_supported_platform_without_a_host_is_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reported apart, so a caller can say which precondition is missing."""
    monkeypatch.setattr(runtime_module.sys, "platform", "win32")
    for name in _CONTROL_ENV:
        monkeypatch.delenv(name, raising=False)
    status = HostRuntimeProvider.status()
    assert status.supported_platform is True
    assert status.host_reachable is False
    assert HostRuntimeProvider.is_available() is False
