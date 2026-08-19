# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for mount path resolution in ResourceGovernor.

Regression cover for issue #7005: the sandbox blocked ``uv run`` from
writing ``~/.cache/uv``, and the documented workaround -- adding
``Write(~/.cache/uv/**)`` to policy.yaml -- did not help because
``_resolve_mount_path`` never expanded ``~``. The pattern fell through to
the workspace-relative branch and produced ``<workspace>/~/.cache/uv``, a
path that never exists, so every backend's existence check dropped the
mount and the grant silently did nothing.
"""

from __future__ import annotations

import os

import pytest

from qwenpaw.governance.resource_governor import ResourceGovernor

_WS = os.path.join(os.sep, "srv", "agent", "workspace")


def _resolve(pattern: str, workspace: str = _WS) -> str:
    return ResourceGovernor._resolve_mount_path(pattern, workspace)


class TestHomeExpansion:
    """``~`` must resolve to the real home, not a literal directory."""

    def test_tilde_pattern_resolves_to_home(self):
        assert _resolve("~/.cache/uv/**") == os.path.join(
            os.path.expanduser("~"),
            ".cache",
            "uv",
        )

    def test_tilde_is_not_treated_as_workspace_relative(self):
        # The bug: ``<workspace>/~/.cache/uv``, which never exists.
        resolved = _resolve("~/.cache/uv/**")
        assert "~" not in resolved
        assert not resolved.startswith(_WS)

    def test_resolved_home_path_is_absolute(self):
        assert os.path.isabs(_resolve("~/.cache/uv/**"))

    def test_bare_tilde_resolves_to_home(self):
        assert _resolve("~/**") == os.path.expanduser("~")


class TestEnvVarExpansion:
    """``$VAR`` is the other way operators write machine-specific paths."""

    def test_env_var_is_expanded(self, monkeypatch):
        monkeypatch.setenv("QP_TEST_CACHE", os.path.join(os.sep, "opt", "c"))
        assert _resolve("$QP_TEST_CACHE/uv/**") == os.path.join(
            os.sep,
            "opt",
            "c",
            "uv",
        )

    def test_undefined_env_var_is_left_alone(self, monkeypatch):
        # posixpath.expandvars leaves an unknown name untouched, so the
        # pattern stays workspace-relative rather than silently becoming
        # the filesystem root.
        monkeypatch.delenv("QP_NOT_SET", raising=False)
        resolved = _resolve("$QP_NOT_SET/uv/**")
        assert resolved.startswith(_WS)


class TestUnchangedBehaviour:
    """The fix must not disturb the patterns that already worked."""

    def test_absolute_path_is_returned_as_is(self):
        expected = os.path.join(os.sep, "tmp", "foo")
        assert _resolve(f"{expected}/**") == expected

    def test_workspace_placeholder_resolves_to_workspace(self):
        assert _resolve("WORKSPACE_DIR/**") == _WS

    def test_relative_path_is_joined_to_workspace(self):
        assert _resolve("sub/dir/**") == os.path.join(_WS, "sub", "dir")

    @pytest.mark.parametrize("pattern", ["*", "**", "", ".", "./"])
    def test_patterns_without_a_concrete_path_are_skipped(self, pattern):
        assert _resolve(pattern) == ""

    def test_trailing_wildcards_and_slashes_are_stripped(self):
        expected = os.path.join(os.sep, "data", "cache")
        assert _resolve(f"{expected}/**") == expected
        assert _resolve(f"{expected}/*") == expected
        assert _resolve(f"{expected}/") == expected


class TestNormalisation:
    """The result must be a normalised path, not just a correct one.

    ``expanduser`` only rewrites the leading ``~``, so on Windows it hands
    back mixed separators (``C:\\Users\\x/.cache/uv``).
    ``compile_sandbox_config`` de-duplicates mounts by path string and uses
    that to let a ``Write`` rule override a ``Read`` rule for the same
    directory -- two spellings would defeat it and the write would never
    win.
    """

    def test_separators_are_native(self):
        resolved = _resolve("~/.cache/uv/**")
        # On POSIX there is nothing to convert; on Windows the forward
        # slashes expanduser left behind must be gone.
        assert resolved == os.path.normpath(resolved)
        if os.sep != "/":
            assert "/" not in resolved

    def test_two_spellings_of_one_directory_agree(self):
        # Pre-normalisation these differed on Windows, producing duplicate
        # MountSpecs for the same directory.
        home = os.path.expanduser("~")
        via_tilde = _resolve("~/.cache/uv/**")
        via_absolute = _resolve(os.path.join(home, ".cache", "uv") + "/**")
        assert via_tilde == via_absolute

    def test_redundant_segments_are_collapsed(self):
        base = os.path.join(os.sep, "data")
        assert _resolve(f"{base}/sub/../cache/**") == os.path.join(
            base,
            "cache",
        )

    def test_relative_result_is_also_normalised(self):
        resolved = _resolve("sub/./dir/**")
        assert resolved == os.path.join(_WS, "sub", "dir")
