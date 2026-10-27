# -*- coding: utf-8 -*-
"""Integration tests for Observability + backup utils internals.

Covers src/qwenpaw/observability/langfuse.py (66 uncovered) and
src/qwenpaw/backup/_utils/safe_swap.py (97 uncovered).
"""

from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# observability langfuse
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_langfuse_available_bool() -> None:
    """_langfuse_available returns a bool."""
    from qwenpaw.observability.langfuse import _langfuse_available

    assert isinstance(_langfuse_available(), bool)


@pytest.mark.integration
@pytest.mark.p1
def test_is_langfuse_enabled_bool() -> None:
    """is_langfuse_enabled returns a bool."""
    from qwenpaw.observability.langfuse import is_langfuse_enabled

    assert isinstance(is_langfuse_enabled(), bool)


@pytest.mark.integration
@pytest.mark.p1
def test_trace_context_roundtrip() -> None:
    """set_current_trace + get_current_trace round-trip."""
    from qwenpaw.observability.langfuse import (
        clear_current_trace,
        get_current_trace,
        set_current_trace,
    )

    set_current_trace(
        trace_id="integ-trace-id",
        parent_observation_id=None,
        name="integ",
    )
    ctx = get_current_trace()
    assert ctx is not None
    clear_current_trace()
    assert get_current_trace() is None


@pytest.mark.integration
@pytest.mark.p1
def test_current_generation_kwargs() -> None:
    """current_generation_kwargs returns a dict."""
    from qwenpaw.observability.langfuse import (
        current_generation_kwargs,
    )

    assert isinstance(current_generation_kwargs(), dict)


# ------------------------------------------------------------------ #
# backup safe_swap
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_restore_lock_timeout_seconds() -> None:
    """_restore_lock_timeout_seconds returns a positive float."""
    from qwenpaw.backup._utils.safe_swap import (
        _restore_lock_timeout_seconds,
    )

    assert _restore_lock_timeout_seconds() > 0


@pytest.mark.integration
@pytest.mark.p1
def test_cleanup_stale_restore_artifacts(tmp_path) -> None:
    """cleanup_stale_restore_artifacts runs on an empty dir."""
    from qwenpaw.backup._utils.safe_swap import (
        cleanup_stale_restore_artifacts,
    )

    cleanup_stale_restore_artifacts(tmp_path)


@pytest.mark.integration
@pytest.mark.p1
def test_lock_for_same_path(tmp_path) -> None:
    """_lock_for returns the same lock for the same destination."""
    from qwenpaw.backup._utils.safe_swap import _lock_for

    dst = tmp_path / "x"
    assert _lock_for(dst) is _lock_for(dst)
