# -*- coding: utf-8 -*-
"""Route-level tests for the per-chat approval level endpoints.

Calls the route functions directly (same style as
``test_api_project_dirs_and_crud.py``): every dependency-injection
seam, error status code, and the persisted-value projection asserted
on its own.
"""

# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from qwenpaw.app.chats import api as chats_api
from qwenpaw.app.chats.api import ApprovalLevelUpdate
from qwenpaw.app.chats.models import ChatSpec


def _spec(
    chat_id: str = "c1",
    *,
    meta: dict | None = None,
) -> ChatSpec:
    return ChatSpec(
        id=chat_id,
        session_id="console:u",
        user_id="u",
        channel="console",
        meta=meta if meta is not None else {},
    )


def _mgr(**overrides) -> SimpleNamespace:
    """ChatManager stand-in exposing only what these routes await."""
    base: dict = {
        "get_chat": AsyncMock(return_value=_spec()),
        "set_session_approval_level": AsyncMock(return_value=_spec()),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _persisted_meta(level: str | None) -> dict:
    if level is None:
        return {}
    return {"runtime_context": {"approval_level": level}}


# ---------------------------------------------------------------------------
# PUT /chats/{chat_id}/approval-level
# ---------------------------------------------------------------------------


class TestSetChatApprovalLevel:
    @pytest.mark.asyncio
    async def test_valid_level_canonicalized(self):
        mgr = _mgr()
        result = await chats_api.set_chat_approval_level(
            "c1",
            ApprovalLevelUpdate(level="strict"),
            mgr,
        )
        mgr.set_session_approval_level.assert_awaited_once_with(
            "c1",
            "STRICT",
        )
        assert result["chat_id"] == "c1"
        assert result["approval_level"] in (None, "STRICT")

    @pytest.mark.asyncio
    async def test_mixed_case_accepted(self):
        mgr = _mgr()
        await chats_api.set_chat_approval_level(
            "c1",
            ApprovalLevelUpdate(level="SmArT"),
            mgr,
        )
        mgr.set_session_approval_level.assert_awaited_once_with(
            "c1",
            "SMART",
        )

    @pytest.mark.asyncio
    async def test_null_clears_override(self):
        mgr = _mgr()
        await chats_api.set_chat_approval_level(
            "c1",
            ApprovalLevelUpdate(level=None),
            mgr,
        )
        mgr.set_session_approval_level.assert_awaited_once_with("c1", None)

    @pytest.mark.asyncio
    async def test_invalid_level_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await chats_api.set_chat_approval_level(
                "c1",
                ApprovalLevelUpdate(level="bogus"),
                _mgr(),
            )
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_chat_404(self):
        mgr = _mgr(get_chat=AsyncMock(return_value=None))
        with pytest.raises(HTTPException) as exc:
            await chats_api.set_chat_approval_level(
                "ghost",
                ApprovalLevelUpdate(level="STRICT"),
                mgr,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_chat_vanished_during_write_404(self):
        mgr = _mgr(set_session_approval_level=AsyncMock(return_value=None))
        with pytest.raises(HTTPException) as exc:
            await chats_api.set_chat_approval_level(
                "c1",
                ApprovalLevelUpdate(level="STRICT"),
                mgr,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_response_reflects_persisted_value(self):
        mgr = _mgr(
            set_session_approval_level=AsyncMock(
                return_value=_spec(meta=_persisted_meta("OFF")),
            ),
        )
        result = await chats_api.set_chat_approval_level(
            "c1",
            ApprovalLevelUpdate(level="off"),
            mgr,
        )
        assert result["approval_level"] == "OFF"


# ---------------------------------------------------------------------------
# GET /chats/{chat_id}/approval-level
# ---------------------------------------------------------------------------


class TestGetChatApprovalLevel:
    @pytest.mark.asyncio
    async def test_returns_persisted_level(self):
        mgr = _mgr(
            get_chat=AsyncMock(
                return_value=_spec(meta=_persisted_meta("STRICT")),
            ),
        )
        result = await chats_api.get_chat_approval_level("c1", mgr)
        assert result == {"chat_id": "c1", "approval_level": "STRICT"}

    @pytest.mark.asyncio
    async def test_no_override_returns_null(self):
        result = await chats_api.get_chat_approval_level("c1", _mgr())
        assert result == {"chat_id": "c1", "approval_level": None}

    @pytest.mark.asyncio
    async def test_malformed_stored_value_returns_null(self):
        mgr = _mgr(
            get_chat=AsyncMock(
                return_value=_spec(
                    meta={"runtime_context": {"approval_level": "nope"}},
                ),
            ),
        )
        result = await chats_api.get_chat_approval_level("c1", mgr)
        assert result["approval_level"] is None

    @pytest.mark.asyncio
    async def test_unknown_chat_404(self):
        mgr = _mgr(get_chat=AsyncMock(return_value=None))
        with pytest.raises(HTTPException) as exc:
            await chats_api.get_chat_approval_level("ghost", mgr)
        assert exc.value.status_code == 404
