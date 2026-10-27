# -*- coding: utf-8 -*-
"""Integration tests for the observability module (Langfuse integration).

Tests the Langfuse trace context management and availability detection.
These are module-level integration tests that verify the observability
subsystem's public API contract.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_langfuse_trace_context_dataclass() -> None:
    """Test purpose:
    - Verify LangfuseTraceContext dataclass can be created with required
      fields. The trace context is set per agent turn for observability.

    Test flow:
    1. Import LangfuseTraceContext.
    2. Create instance with required fields.
    3. Verify fields are accessible.
    """
    from qwenpaw.observability.langfuse import LangfuseTraceContext

    ctx = LangfuseTraceContext(
        trace_id="test-trace-123",
        parent_observation_id=None,
        name="test-turn",
        metadata={"agent_id": "default"},
    )
    assert ctx.trace_id == "test-trace-123"
    assert ctx.parent_observation_id is None
    assert ctx.name == "test-turn"
    assert ctx.metadata == {"agent_id": "default"}


@pytest.mark.integration
@pytest.mark.p1
def test_langfuse_trace_context_frozen() -> None:
    """Test purpose:
    - Verify LangfuseTraceContext is frozen (immutable). Prevents
      accidental mutation of trace context mid-turn.

    Test flow:
    1. Create LangfuseTraceContext.
    2. Attempt to modify a field.
    3. Verify FrozenInstanceError is raised.
    """
    from dataclasses import FrozenInstanceError

    from qwenpaw.observability.langfuse import LangfuseTraceContext

    ctx = LangfuseTraceContext(
        trace_id="test",
        parent_observation_id=None,
        name="test",
        metadata={},
    )
    with pytest.raises(FrozenInstanceError):
        ctx.trace_id = "modified"  # type: ignore[misc]


@pytest.mark.integration
@pytest.mark.p1
def test_is_langfuse_enabled_no_env_vars() -> None:
    """Test purpose:
    - Verify is_langfuse_enabled returns False when LANGFUSE_SECRET_KEY
      is not set. Langfuse is optional and should be a no-op by default.

    Test flow:
    1. Ensure LANGFUSE_SECRET_KEY is not set.
    2. Call is_langfuse_enabled().
    3. Verify returns False.
    """
    from qwenpaw.observability.langfuse import is_langfuse_enabled

    # Save and clear env var
    original = os.environ.pop("LANGFUSE_SECRET_KEY", None)
    try:
        result = is_langfuse_enabled()
        assert result is False
    finally:
        if original is not None:
            os.environ["LANGFUSE_SECRET_KEY"] = original


@pytest.mark.integration
@pytest.mark.p1
def test_set_and_get_current_trace() -> None:
    """Test purpose:
    - Verify set_current_trace stores trace context that can be
      retrieved. The context is used to correlate observations within
      a turn.

    Test flow:
    1. Call set_current_trace with test data.
    2. Verify the context var is set (via _current_trace).
    """
    from qwenpaw.observability.langfuse import (
        _current_trace,
        set_current_trace,
    )

    set_current_trace(
        trace_id="test-trace-456",
        parent_observation_id="parent-obs-789",
        name="test-turn-2",
        metadata={"key": "value"},
    )

    ctx = _current_trace.get()
    assert ctx is not None
    assert ctx.trace_id == "test-trace-456"
    assert ctx.parent_observation_id == "parent-obs-789"
    assert ctx.name == "test-turn-2"
    assert ctx.metadata == {"key": "value"}

    # Clean up
    _current_trace.set(None)


@pytest.mark.integration
@pytest.mark.p1
def test_set_current_trace_default_metadata() -> None:
    """Test purpose:
    - Verify set_current_trace handles None metadata gracefully
      (converts to empty dict).

    Test flow:
    1. Call set_current_trace with metadata=None.
    2. Verify metadata is empty dict, not None.
    """
    from qwenpaw.observability.langfuse import (
        _current_trace,
        set_current_trace,
    )

    set_current_trace(
        trace_id="test-trace-789",
        parent_observation_id=None,
        name="test-turn-3",
        metadata=None,
    )

    ctx = _current_trace.get()
    assert ctx is not None
    assert ctx.metadata == {}

    # Clean up
    _current_trace.set(None)


@pytest.mark.integration
@pytest.mark.p1
def test_current_trace_default_none() -> None:
    """Test purpose:
    - Verify _current_trace ContextVar defaults to None when no trace
      has been set. This is the initial state.

    Test flow:
    1. Get _current_trace without setting it.
    2. Verify returns None.
    """
    from qwenpaw.observability.langfuse import _current_trace

    # Reset to default
    _current_trace.set(None)
    ctx = _current_trace.get()
    assert ctx is None


@pytest.mark.integration
@pytest.mark.p1
def test_langfuse_available_detection() -> None:
    """Test purpose:
    - Verify _langfuse_available correctly detects whether langfuse
      package is installed. This determines whether tracing is possible.

    Test flow:
    1. Call _langfuse_available().
    2. Verify returns bool (True if langfuse is installed, False otherwise).
    """
    from qwenpaw.observability.langfuse import _langfuse_available

    result = _langfuse_available()
    assert isinstance(result, bool)


@pytest.mark.integration
@pytest.mark.p1
def test_langfuse_client_returns_none_when_unavailable() -> None:
    """Test purpose:
    - Verify _langfuse_client returns None when langfuse is not
      installed. Graceful degradation.

    Test flow:
    1. Call _langfuse_client().
    2. If langfuse not installed, verify returns None.
    """
    from qwenpaw.observability.langfuse import (
        _langfuse_available,
        _langfuse_client,
    )

    if not _langfuse_available():
        client = _langfuse_client()
        assert client is None


@pytest.mark.integration
@pytest.mark.p1
def test_observability_init_exports() -> None:
    """Test purpose:
    - Verify qwenpaw.observability package can be imported and has
      expected structure.

    Test flow:
    1. Import qwenpaw.observability.
    2. Verify import succeeds (package exists).
    """
    import qwenpaw.observability

    assert qwenpaw.observability is not None
