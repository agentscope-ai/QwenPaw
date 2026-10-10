# -*- coding: utf-8 -*-
"""Integration tests for ToolGuard destructive-command safety checks.

Covers src/qwenpaw/security/tool_guard/safety_checks.py (337 uncovered
lines): catastrophic wipe / mkfs / dd / fork-bomb classification,
system-power commands, path-boundary checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_is_command_catastrophic_rm_root() -> None:
    """rm -rf / is catastrophic."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_catastrophic,
    )

    assert is_command_catastrophic("rm -rf /") is True


@pytest.mark.integration
@pytest.mark.p1
def test_is_command_catastrophic_wildcard_wipe() -> None:
    """Broad wildcard deletes are catastrophic."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_catastrophic,
    )

    assert is_command_catastrophic("rm -rf /*") is True


@pytest.mark.integration
@pytest.mark.p1
def test_is_command_catastrophic_mkfs() -> None:
    """Formatting a filesystem is catastrophic."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_catastrophic,
    )

    assert is_command_catastrophic("mkfs.ext4 /dev/sda1") is True


@pytest.mark.integration
@pytest.mark.p1
def test_is_command_catastrophic_fork_bomb() -> None:
    """Classic fork bombs are catastrophic."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_catastrophic,
    )

    assert is_command_catastrophic(":(){ :|:& };:") is True


@pytest.mark.integration
@pytest.mark.p1
def test_is_command_catastrophic_benign_rm() -> None:
    """Removing a regular file under a workspace is not catastrophic."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_catastrophic,
    )

    assert is_command_catastrophic("rm -f notes.txt") is False


@pytest.mark.integration
@pytest.mark.p1
def test_is_command_destructive_shutdown() -> None:
    """shutdown in command position is destructive (system_power)."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_destructive,
    )

    assert is_command_destructive("shutdown -h now") is True


@pytest.mark.integration
@pytest.mark.p1
def test_is_command_destructive_benign() -> None:
    """Harmless commands are not destructive."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_destructive,
    )

    assert is_command_destructive("ls -la") is False
    assert is_command_destructive("echo hello") is False


@pytest.mark.integration
@pytest.mark.p1
def test_classify_destructive_command_kinds() -> None:
    """Classification distinguishes catastrophic, power, and none."""
    from qwenpaw.security.tool_guard.safety_checks import (
        classify_destructive_command,
    )

    assert classify_destructive_command("rm -rf /") == "catastrophic"
    assert classify_destructive_command("ls") is None


@pytest.mark.integration
@pytest.mark.p1
def test_is_path_outside_boundary_outside(tmp_path: Path) -> None:
    """Path outside the workspace boundary reports True."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_path_outside_boundary,
    )

    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir()
    outside.touch()

    assert is_path_outside_boundary(outside, ws) is True


@pytest.mark.integration
@pytest.mark.p1
def test_is_path_outside_boundary_inside(tmp_path: Path) -> None:
    """Path inside the workspace boundary reports False."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_path_outside_boundary,
    )

    ws = tmp_path / "workspace"
    ws.mkdir()
    inside = ws / "data" / "a.txt"
    inside.parent.mkdir()
    inside.touch()

    assert is_path_outside_boundary(inside, ws) is False


@pytest.mark.integration
@pytest.mark.p1
def test_is_path_outside_boundary_sibling_prefix(tmp_path: Path) -> None:
    """Sibling directory sharing a name prefix are outside boundary.

    Guards against string-prefix bypass (/foo/bar_evil vs /foo/bar).
    """
    from qwenpaw.security.tool_guard.safety_checks import (
        is_path_outside_boundary,
    )

    ws = tmp_path / "bar"
    ws.mkdir()
    sibling = tmp_path / "bar_evil" / "x.txt"
    sibling.parent.mkdir()
    sibling.touch()

    assert is_path_outside_boundary(sibling, ws) is True


@pytest.mark.integration
@pytest.mark.p1
def test_posix_root_treated_catastrophically() -> None:
    """POSIX absolute root wipe token is catastrophic on any host."""
    from qwenpaw.security.tool_guard.safety_checks import (
        is_command_catastrophic,
    )

    assert is_command_catastrophic("sudo rm -rf /etc") is True


@pytest.mark.integration
@pytest.mark.p1
def test_safe_temp_tree_not_catastrophic() -> None:
    """Wiping a temp-tree target is not classified catastrophic."""
    from qwenpaw.security.tool_guard.safety_checks import (
        classify_destructive_command,
    )

    # Removing under a tmp scratch dir should not auto-deny.
    result = classify_destructive_command("rm -rf /tmp/qwenpaw-scratch")
    assert result != "catastrophic" or result is None
