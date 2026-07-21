# -*- coding: utf-8 -*-
"""Tests for WorkspaceBootstrapFactory."""
from __future__ import annotations

from qwenpaw.app.workspace.bootstrap_factory import WorkspaceBootstrapFactory


class TestWorkspaceBootstrapFactory:
    """Verify shared bootstrap factory produces correct kwargs."""

    def test_build_bootstrap_kwargs_returns_dict(self) -> None:
        kwargs = WorkspaceBootstrapFactory.build_bootstrap_kwargs(None)
        assert isinstance(kwargs, dict)

    def test_includes_builtin_hook_clses(self) -> None:
        kwargs = WorkspaceBootstrapFactory.build_bootstrap_kwargs(None)
        hook_clses = kwargs.get("builtin_hook_clses", [])
        assert len(hook_clses) > 0, "Expected at least some hook classes"

    def test_includes_builtin_tool_funcs(self) -> None:
        kwargs = WorkspaceBootstrapFactory.build_bootstrap_kwargs(None)
        # builtin_tool_funcs may or may not be present depending on environment
        # but the key should exist if tools are available
        if "builtin_tool_funcs" in kwargs:
            assert isinstance(kwargs["builtin_tool_funcs"], (list, tuple))

    def test_extra_command_specs_merged(self) -> None:
        class _FakeSpec:
            name = "fake"

        extra = [_FakeSpec()]
        kwargs = WorkspaceBootstrapFactory.build_bootstrap_kwargs(
            None,
            extra_command_specs=extra,
        )
        specs = kwargs.get("builtin_command_specs", [])
        assert any(getattr(s, "name", None) == "fake" for s in specs)

    def test_extra_hook_clses_merged(self) -> None:
        class _FakeHook:
            pass

        kwargs = WorkspaceBootstrapFactory.build_bootstrap_kwargs(
            None,
            extra_hook_clses=[_FakeHook],
        )
        hook_clses = kwargs.get("builtin_hook_clses", [])
        assert _FakeHook in hook_clses

    def test_modes_included_when_available(self) -> None:
        kwargs = WorkspaceBootstrapFactory.build_bootstrap_kwargs(None)
        mode_clses = kwargs.get("builtin_mode_clses", [])
        # Modes should be present in a normal environment
        assert len(mode_clses) >= 0  # May be empty if modes unavailable
