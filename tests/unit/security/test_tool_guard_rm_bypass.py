# -*- coding: utf-8 -*-
"""rm protection bypass regression tests.

Regression for #5090: rm protection must block root/home/absolute targets.

The guard in ``qwenpaw.security.tool_guard.guardians.rule_guardian`` extracts
rm targets, expands ``~``/``$HOME``/``${VAR}``, resolves them to absolute
paths, and flags any target that falls outside the workspace. Issue #5090
reported bypasses via ``~``, ``$HOME``, absolute paths and globs that expand
toward root.

These tests pin the contract that those targets are all flagged as outside
the workspace, while legitimate in-workspace rm commands remain allowed.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.security.tool_guard.guardians.rule_guardian import (
    _check_rm_targets_outside_workspace,
)

# These cases assert Unix ``rm`` semantics - absolute ``/``-rooted targets
# and the ``\\rm`` / ``$(which rm)`` / ``command rm`` escape family. On
# Windows the guard's ``/foo`` token is ambiguous with ``del /F`` flags, so
# ``_extract_rm_targets`` skips it (see rule_guardian._extract_rm_targets).
# That quirk is unrelated to the #5090 bypass; the Unix rm family only ever
# runs on POSIX, so skip on win32.
_unix_rm_only = pytest.mark.skipif(
    "sys.platform == 'win32'",
    reason="Unix rm semantics (/abs targets, \\rm, $(which rm)) not "
    "exercised on Windows; guard treats /foo as a del flag there "
    "(rule_guardian._extract_rm_targets). See #5090.",
)


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    """A tmp workspace; rm below this root is legitimate."""
    ws = tmp_path / "ws"
    ws.mkdir()
    home = tmp_path / "fake-home"
    home.mkdir()
    with (
        patch(
            "qwenpaw.config.context.get_current_workspace_dir",
            return_value=ws,
        ),
        patch(
            "qwenpaw.security.tool_guard.guardians."
            "rule_guardian._get_workspace_root",
            return_value=ws,
        ),
        patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}),
    ):
        yield ws


# ---------------------------------------------------------------------------
# Blocked: root, home, absolute, glob-to-root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf /etc",
        "rm -rf /etc/passwd",
        "rm -rf /tmp/foo",
        "rm -rf /usr",
        "rm -rf /var/log",
    ],
)
@_unix_rm_only
def test_absolute_and_root_targets_blocked(
    workspace: Path,
    command: str,
) -> None:
    """Regression for #5090: absolute-path rm targets outside the workspace
    (including root, /* glob, /etc, /tmp) must be flagged."""
    has_outside, paths = _check_rm_targets_outside_workspace(command)
    assert has_outside is True, f"expected outside for: {command}"
    assert paths, f"expected non-empty outside list for: {command}"


def test_tilde_expansion_blocked(workspace: Path) -> None:
    """Regression for #5090: ``rm -rf ~`` must expand to $HOME and be flagged
    as outside the workspace."""
    has_outside, paths = _check_rm_targets_outside_workspace("rm -rf ~")
    assert has_outside is True
    assert any("~" in p for p in paths)


def test_home_env_var_blocked(workspace: Path) -> None:
    """Regression for #5090: ``rm -rf $HOME`` must expand via ``expandvars``
    and be flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("rm -rf $HOME")
    assert has_outside is True


def test_home_brace_env_var_blocked(workspace: Path) -> None:
    """Regression for #5090: ``rm -rf ${HOME}`` must be flagged.

    The detection/extraction split fix lands in the paired fix(security) PR
    (#5866). Once that PR merges, this test passes for real; the former
    xfail(strict=True) is removed here. CI will be red on this branch alone
    until #5866 also lands — that pairing is intentional."""
    has_outside, _ = _check_rm_targets_outside_workspace("rm -rf ${HOME}")
    assert has_outside is True


def test_relative_path_escaping_workspace_blocked(workspace: Path) -> None:
    """Regression for #5090: ``rm -rf ../outside`` resolves outside the
    workspace and must be flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("rm -rf ../outside")
    assert has_outside is True


@_unix_rm_only
def test_compound_command_with_outside_rm_blocked(workspace: Path) -> None:
    """Regression for #5090: a rm after a ``;`` / ``&&`` / ``|`` separator
    must still be analysed."""
    has_outside, _ = _check_rm_targets_outside_workspace(
        "echo hi; rm -rf /etc/passwd",
    )
    assert has_outside is True


@_unix_rm_only
def test_escaped_rm_bin_path_blocked(workspace: Path) -> None:
    """Regression for #5090: ``/bin/rm -rf /`` must be normalised so the rm
    token is recognised and the target flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("/bin/rm -rf /")
    assert has_outside is True


@_unix_rm_only
def test_backslash_rm_blocked(workspace: Path) -> None:
    """Regression for #5090: ``\\rm -rf /`` must be normalised and flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("\\rm -rf /")
    assert has_outside is True


@_unix_rm_only
def test_command_substitution_rm_blocked(workspace: Path) -> None:
    """Regression for #5090: ``$(which rm) -rf /`` must be normalised and
    flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("$(which rm) -rf /")
    assert has_outside is True


@_unix_rm_only
def test_backtick_rm_blocked(workspace: Path) -> None:
    """Regression for #5090: `` `which rm` -rf / `` must be normalised and
    flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("`which rm` -rf /")
    assert has_outside is True


@_unix_rm_only
def test_command_prefix_rm_blocked(workspace: Path) -> None:
    """Regression for #5090: ``command rm -rf /`` must be normalised and
    flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("command rm -rf /")
    assert has_outside is True


@_unix_rm_only
def test_env_prefix_rm_blocked(workspace: Path) -> None:
    """Regression for #5090: ``env rm -rf /`` must be normalised."""
    has_outside, _ = _check_rm_targets_outside_workspace("env rm -rf /")
    assert has_outside is True


# ---------------------------------------------------------------------------
# Allowed: legitimate in-workspace rm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm somefile.txt",
        "rm -rf ./build/",
        "rm -rf sub/dir",
        "rm -rf ./node_modules",
        "rm -r ./dist",
        "rm -f scratch.txt",
    ],
)
def test_in_workspace_rm_allowed(
    workspace: Path,
    command: str,
) -> None:
    """Regression for #5090: legitimate rm of relative paths inside the
    workspace must NOT be flagged as outside."""
    has_outside, paths = _check_rm_targets_outside_workspace(command)
    assert has_outside is False, f"unexpected outside flag for: {command}"
    assert paths == []


def test_workspace_absolute_path_allowed(workspace: Path) -> None:
    """Regression for #5090: an absolute path that resolves inside the
    workspace (e.g. ``rm <workspace>/scratch``) must be allowed."""
    target = workspace / "scratch"
    has_outside, _ = _check_rm_targets_outside_workspace(f"rm -rf {target}")
    assert has_outside is False


# ---------------------------------------------------------------------------
# Comments / no-target rm
# ---------------------------------------------------------------------------


def test_comment_is_ignored(workspace: Path) -> None:
    """Regression for #5090: a commented-out rm must not be flagged."""
    has_outside, _ = _check_rm_targets_outside_workspace("# rm -rf /")
    assert has_outside is False


def test_rm_with_no_targets(workspace: Path) -> None:
    """Regression for #5090: ``rm -rf`` with no path argument returns no
    targets — nothing to flag."""
    has_outside, paths = _check_rm_targets_outside_workspace("rm -rf")
    assert has_outside is False
    assert paths == []
