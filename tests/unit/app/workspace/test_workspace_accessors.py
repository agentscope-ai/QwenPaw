# -*- coding: utf-8 -*-
"""Tests for Workspace service accessors."""

from types import SimpleNamespace

from qwenpaw.app.workspace.workspace import Workspace


def test_terminal_manager_is_a_property_like_other_services():
    terminal_manager = object()
    workspace = Workspace.__new__(Workspace)
    setattr(
        workspace,
        "_service_manager",
        SimpleNamespace(services={"terminal_manager": terminal_manager}),
    )

    assert workspace.terminal_manager is terminal_manager
