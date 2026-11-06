# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Startup budget tests for the local runtime provisioner."""

from __future__ import annotations

import pytest

import qwenpaw.hub.local_provisioner as provisioner_module
from qwenpaw.hub.local_provisioner import _default_start_timeout


def test_windows_start_timeout_matches_e2e_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provisioner_module.sys, "platform", "win32")
    assert _default_start_timeout() == 120.0


def test_non_windows_start_timeout_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provisioner_module.sys, "platform", "linux")
    assert _default_start_timeout() == 30.0


def test_explicit_start_timeout_overrides_platform_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Isolator:
        name = "none"

    monkeypatch.setattr(provisioner_module.sys, "platform", "win32")
    provisioner = provisioner_module.LocalProcessRuntimeProvisioner(
        start_timeout=45.0,
        isolator=_Isolator(),
    )
    assert provisioner._start_timeout == 45.0
