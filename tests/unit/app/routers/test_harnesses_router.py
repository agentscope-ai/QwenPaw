# -*- coding: utf-8 -*-
"""Tests for third-party agent authentication routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from qwenpaw.app.routers import harnesses
from qwenpaw.harnesses.base import HarnessOperationNotSupportedError


@pytest.mark.asyncio
async def test_qoder_logout_returns_structured_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AsyncMock()
    adapter.logout.side_effect = HarnessOperationNotSupportedError(
        "Qoder CLI does not expose a non-interactive logout command.",
    )
    runtime = SimpleNamespace(adapter=AsyncMock(return_value=adapter))
    workspace = SimpleNamespace(harness_runtime=runtime)
    monkeypatch.setattr(
        harnesses,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )

    with pytest.raises(HTTPException) as exc_info:
        await harnesses.post_harness_logout(
            "qoder",
            harnesses.HarnessStatusRequest(),
            cast(Request, object()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "logout_not_supported",
        "message": (
            "Qoder CLI does not expose a non-interactive logout command."
        ),
    }
