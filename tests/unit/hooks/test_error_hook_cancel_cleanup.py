# -*- coding: utf-8 -*-
"""CancelCleanupHook cancellation traceability tests (GH-8252).

The ``cancel_cleanup`` log line is the primary evidence operators have
when a session dies by cancellation. It must carry the cancel reason
(user / timeout / agent / shutdown) so framework reclaim (e.g. the
chat_with_agent timeout stop-cascade) is distinguishable from a real
user stop without cross-referencing other sessions' logs.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from qwenpaw.hooks.error.error_hook import CancelCleanupHook
from qwenpaw.runtime.hooks import HookContext
from qwenpaw.tool_calls import CancelReason, cancellation_reason


class _Capture(logging.Handler):
    """Direct-attach capture; immune to propagate=False configurations."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _make_ctx(error: BaseException | None) -> HookContext:
    return HookContext(
        request=SimpleNamespace(user_id="u", channel="console"),
        session_id="session-a:to:session-b:123:abcd",
        agent_id="agent-b",
        root_session_id="session-root",
        root_agent_id="agent-a",
        workspace_dir=None,
        workspace=None,
        app_services=None,
        error=error,
    )


@pytest.fixture(name="capture")
def fixture_capture(monkeypatch):
    """Capture cancel_cleanup logs and stub the approval service."""
    handler = _Capture()
    logger = logging.getLogger("qwenpaw.hooks.error.error_hook")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    import qwenpaw.app.approvals as approvals_pkg

    async def _noop_cancel(*_a, **_k) -> int:
        return 0

    fake_svc = SimpleNamespace(
        cancel_all_pending_by_root_session=_noop_cancel,
    )
    monkeypatch.setattr(
        approvals_pkg,
        "get_approval_service",
        lambda: fake_svc,
    )
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


async def test_cancel_cleanup_logs_timeout_reason(capture) -> None:
    """Timeout-cascade cancels must be labeled reason=timeout."""
    hook = CancelCleanupHook()
    await hook.run(_make_ctx(asyncio.CancelledError("timeout")))
    assert any(
        "cancel_cleanup" in m
        and "reason=timeout" in m
        and "session-a:to:session-b:123:abcd" in m
        for m in capture.messages
    ), capture.messages


async def test_cancel_cleanup_logs_user_reason(capture) -> None:
    hook = CancelCleanupHook()
    await hook.run(_make_ctx(asyncio.CancelledError("user")))
    assert any("reason=user" in m for m in capture.messages)


async def test_cancel_cleanup_bare_cancel_is_unknown(capture) -> None:
    """A cancel without an attached reason must say unknown, never user."""
    hook = CancelCleanupHook()
    await hook.run(_make_ctx(asyncio.CancelledError()))
    assert any("reason=unknown" in m for m in capture.messages)
    assert not any("reason=user" in m for m in capture.messages)


async def test_cancel_cleanup_unrecognized_reason_is_unknown(
    capture,
) -> None:
    hook = CancelCleanupHook()
    await hook.run(_make_ctx(asyncio.CancelledError("not-a-reason")))
    assert any("reason=unknown" in m for m in capture.messages)


async def test_cancel_cleanup_keyboard_interrupt(capture) -> None:
    hook = CancelCleanupHook()
    await hook.run(_make_ctx(KeyboardInterrupt()))
    assert any(
        "cancel_cleanup" in m
        and "reason=unknown" in m
        and "KeyboardInterrupt" in m
        for m in capture.messages
    )


async def test_cancel_cleanup_ignores_regular_errors(capture) -> None:
    hook = CancelCleanupHook()
    await hook.run(_make_ctx(ValueError("boom")))
    assert not any("cancel_cleanup" in m for m in capture.messages)


class TestCancellationReasonHelper:
    """Shared parser used by runtime cancel-save and ON_ERROR hooks."""

    def test_known_string_reasons(self):
        for reason in CancelReason:
            err = asyncio.CancelledError(reason.value)
            assert cancellation_reason(err) == reason.value

    def test_enum_instance_reason(self):
        err = asyncio.CancelledError(CancelReason.SHUTDOWN)
        assert cancellation_reason(err) == "shutdown"

    def test_bare_cancel_returns_none(self):
        assert cancellation_reason(asyncio.CancelledError()) is None

    def test_unknown_reason_returns_none(self):
        err = asyncio.CancelledError("because-i-said-so")
        assert cancellation_reason(err) is None

    def test_non_cancel_error_returns_none(self):
        assert cancellation_reason(RuntimeError("timeout")) is None
        assert cancellation_reason(None) is None

    def test_non_string_arg_returns_none(self):
        assert cancellation_reason(asyncio.CancelledError(42)) is None
