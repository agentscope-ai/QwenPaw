# -*- coding: utf-8 -*-
"""Session hook persistence behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.hooks.session.session_hook import (
    SessionLoadHook,
    SessionSaveHook,
)

pytestmark = [pytest.mark.unit, pytest.mark.p1]


class _FakeSession:
    def __init__(self) -> None:
        self.loaded = False
        self.saved = False

    async def load_session_state(self, *args, **kwargs) -> None:
        del args, kwargs
        self.loaded = True

    async def save_session_state(self, *args, **kwargs) -> None:
        del args, kwargs
        self.saved = True


def _ctx(session: _FakeSession, *, ephemeral: bool):
    return SimpleNamespace(
        request=SimpleNamespace(
            request_context={ACP_EPHEMERAL_META_KEY: ephemeral},
            user_id="acp_warmup",
            channel="",
        ),
        workspace=SimpleNamespace(session=session),
        agent=SimpleNamespace(state_dict=lambda: {"context": []}),
        session_id="warmup-session",
    )


async def test_ephemeral_request_skips_session_load_and_save():
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=True)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is False
    assert session.saved is False


async def test_normal_request_loads_and_saves_session_state():
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=False)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is True
    assert session.saved is True
