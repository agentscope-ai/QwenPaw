# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ACP permission adapter trusted flag and auto-approve logic."""
from __future__ import annotations

from qwenpaw.agents.acp.permissions import ACPPermissionAdapter


class TestACPPermissionAdapterTrusted:
    """Verify trusted flag is stored and does not affect is_hard_blocked."""

    def test_trusted_flag_stored(self) -> None:
        adapter = ACPPermissionAdapter(cwd="/tmp", trusted=True)
        assert adapter._trusted is True  # noqa: W0212

    def test_trusted_false_by_default(self) -> None:
        adapter = ACPPermissionAdapter(cwd="/tmp")
        assert adapter._trusted is False  # noqa: W0212

    def test_is_hard_blocked_ignores_trusted_for_destructive_command(
        self,
    ) -> None:
        """is_hard_blocked always blocks destructive commands."""
        adapter_trusted = ACPPermissionAdapter(
            cwd="/tmp",
            trusted=True,
        )
        adapter_untrusted = ACPPermissionAdapter(
            cwd="/tmp",
            trusted=False,
        )

        tool_call = {
            "title": "Execute",
            "kind": "execute",
            "rawInput": {"command": "rm -rf /"},
        }

        assert adapter_trusted.is_hard_blocked(tool_call) is True
        assert adapter_untrusted.is_hard_blocked(tool_call) is True

    def test_is_hard_blocked_allows_safe_command_regardless_of_trusted(
        self,
    ) -> None:
        adapter_trusted = ACPPermissionAdapter(
            cwd="/tmp",
            trusted=True,
        )
        adapter_untrusted = ACPPermissionAdapter(
            cwd="/tmp",
            trusted=False,
        )

        tool_call = {
            "title": "Execute",
            "kind": "execute",
            "rawInput": {"command": "ls -la"},
        }

        assert adapter_trusted.is_hard_blocked(tool_call) is False
        assert adapter_untrusted.is_hard_blocked(tool_call) is False

    def test_is_hard_blocked_blocks_path_outside_boundary(
        self,
        tmp_path,
    ) -> None:
        cwd = str(tmp_path)
        adapter_trusted = ACPPermissionAdapter(
            cwd=cwd,
            trusted=True,
        )
        adapter_untrusted = ACPPermissionAdapter(
            cwd=cwd,
            trusted=False,
        )

        tool_call = {
            "title": "Write file",
            "kind": "write",
            "locations": [{"path": "/etc/passwd"}],
        }

        assert adapter_trusted.is_hard_blocked(tool_call) is True
        assert adapter_untrusted.is_hard_blocked(tool_call) is True


class TestACPPermissionAdapterDelegatesToSafetyChecks:
    """Verify permissions.py delegates to shared safety_checks module."""

    def test_destructive_command_detected_via_shared_function(self) -> None:
        adapter = ACPPermissionAdapter(cwd="/tmp")
        tool_call = {
            "title": "Execute",
            "kind": "execute",
            "rawInput": {"command": "shutdown now"},
        }
        assert adapter.is_hard_blocked(tool_call) is True

    def test_safe_command_passes_via_shared_function(self) -> None:
        adapter = ACPPermissionAdapter(cwd="/tmp")
        tool_call = {
            "title": "Execute",
            "kind": "execute",
            "rawInput": {"command": "echo hello"},
        }
        assert adapter.is_hard_blocked(tool_call) is False
