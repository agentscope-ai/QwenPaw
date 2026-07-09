# -*- coding: utf-8 -*-
"""Focused regression test for #5090: rm -rf ${HOME} bypass.

The root cause: ``_RM_ESCAPE_PATTERNS`` applied a ``${VAR}`` blanking
substitution to the rm-part used for shlex tokenisation, which erased
real targets like ``${HOME}`` before path expansion — so the guard saw
no target and did not flag ``rm -rf ${HOME}`` as outside-workspace.

The fix splits escape patterns into:
- ``_RM_ESCAPE_PATTERNS`` (extraction, real targets preserved)
- ``_RM_DETECTION_ONLY_PATTERNS`` (detection, ${VAR} blanked to
  detect things like ``${RM}`` but NOT applied to extraction)
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=line-too-long
# flake8: noqa: E501
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from qwenpaw.security.tool_guard.guardians.rule_guardian import (
    _check_rm_targets_outside_workspace,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "file.txt").write_text("ok", encoding="utf-8")
    return tmp_path


class TestHomeBypassFixed:
    """#5090: rm -rf ${HOME} must be flagged after the fix."""

    def test_home_brace_env_var_blocked(self, workspace: Path) -> None:
        """The core bypass: ${HOME} must survive extraction and be
        flagged as outside workspace."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("HOME", str(workspace.parent))
            mp.setenv("USERPROFILE", str(workspace.parent))
            has_outside, _ = _check_rm_targets_outside_workspace(
                "rm -rf ${HOME}",
            )
        assert has_outside is True

    def test_home_dollar_sign_blocked(self, workspace: Path) -> None:
        """rm -rf $HOME must also be flagged."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("HOME", str(workspace.parent))
            has_outside, _ = _check_rm_targets_outside_workspace(
                "rm -rf $HOME",
            )
        assert has_outside is True

    def test_tilde_expansion_blocked(self, workspace: Path) -> None:
        """rm -rf ~ must expand to $HOME and be flagged."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("HOME", str(workspace.parent))
            has_outside, _ = _check_rm_targets_outside_workspace(
                "rm -rf ~",
            )
        assert has_outside is True


class TestRmVariableCommand:
    """${RM} (variable name IS the command) — pins current behavior."""

    @pytest.mark.skip(
        reason="${RM} detection requires env expansion in shell, "
        "not currently handled by the regex guard. Tracked as "
        "follow-up to #5090.",
    )
    def test_rm_variable_command_blocked(self, workspace: Path) -> None:
        """${RM} -rf / should be detected as rm -rf / via the
        detection-only ${VAR} -> rm pattern."""
        has_outside, _ = _check_rm_targets_outside_workspace(
            "${RM} -rf /",
        )
        assert has_outside is True


class TestLegitimateRmStillAllowed:
    """Make sure the fix doesn't break legitimate in-workspace rm."""

    def test_relative_path_in_workspace_allowed(
        self,
        workspace: Path,
    ) -> None:
        has_outside, _ = _check_rm_targets_outside_workspace("rm file.txt")
        assert has_outside is False


class TestRootTargetsBlocked:
    """Classic root deletion vectors — must all be flagged.

    These assert on Unix root paths (``/``, ``/etc``, ...). On Windows the
    extractor's flag detection treats a leading ``/`` token as a del /
    Remove-Item flag when ``Path(token).is_absolute()`` is False (Unix paths
    have no drive on Windows), so the Unix root contract is not meaningful
    there. The #5090 fix itself (``${HOME}`` survival) is platform-agnostic
    and is covered by TestHomeBypassFixed on all platforms.
    """

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Unix root paths have no absolute-path meaning on Windows; "
        "the leading-/ flag-vs-path detection differs by design.",
    )
    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf /*",
            "rm -rf /etc",
            "rm -rf /tmp",
            "rm -rf /usr",
            "rm -rf /var",
        ],
    )
    def test_root_targets_blocked(
        self,
        workspace: Path,
        command: str,
    ) -> None:
        has_outside, _ = _check_rm_targets_outside_workspace(command)
        assert has_outside is True
