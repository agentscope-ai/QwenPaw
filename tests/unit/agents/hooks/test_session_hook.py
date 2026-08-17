# -*- coding: utf-8 -*-
"""Session hook persistence behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.hooks.session.session_hook import SessionLoadHook, SessionSaveHook
from qwenpaw.hooks.session.signals import SESSION_SAVE_SUCCEEDED_KEY

pytestmark = [pytest.mark.unit, pytest.mark.p1]


class _FakeSession:
    def __init__(self, *, save_error: Exception | None = None) -> None:
        self.loaded = False
        self.saved = False
        self.load_payload = {}
        self.saved_payload = {}
        self.state_dict = {"agent": {}}
        self.updated_key = None
        self.updated_value = None
        self.save_error = save_error

    async def load_session_state(self, *args, **kwargs) -> None:
        del args
        self.loaded = True
        kwargs["agent"].load_state_dict(self.load_payload)

    async def save_session_state(self, *args, **kwargs) -> None:
        del args
        if self.save_error is not None:
            raise self.save_error
        self.saved = True
        self.saved_payload = kwargs["agent"].state_dict()

    async def get_session_state_dict(self, *args, **kwargs) -> dict:
        del args, kwargs
        return self.state_dict

    async def update_session_state(self, *args, **kwargs) -> None:
        del args
        self.updated_key = kwargs["key"]
        self.updated_value = kwargs["value"]


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
        mode_state={},
        session_state=None,
        extras={},
    )


async def test_ephemeral_request_skips_session_load_and_save():
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=True)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is False
    assert session.saved is False
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is False


async def test_normal_request_loads_and_saves_session_state():
    session = _FakeSession()
    session.load_payload = {
        "mode_state": {"mission": {"active": True}},
    }
    ctx = _ctx(session, ephemeral=False)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is True
    assert session.saved is True
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is True
    assert ctx.mode_state == {"mission": {"active": True}}
    assert session.saved_payload["mode_state"] == ctx.mode_state


async def test_failed_session_save_does_not_mark_turn_as_persisted():
    session = _FakeSession(save_error=RuntimeError("save failed"))
    ctx = _ctx(session, ephemeral=False)

    await SessionSaveHook().run(ctx)

    assert session.saved is False
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is False


async def test_manifest_is_persisted_without_built_agent():
    session = _FakeSession()
    session.state_dict = {
        "agent": {
            "workspace_artifact_manifests": [
                {"version": 1, "turn_id": "turn-1"},
            ],
        },
    }
    ctx = _ctx(session, ephemeral=False)
    ctx.agent = None
    ctx.extras["workspace_artifact_manifest"] = {
        "version": 1,
        "turn_id": "turn-2",
    }

    await SessionSaveHook().run(ctx)

    assert session.saved is True
    assert session.saved_payload["workspace_artifact_manifests"] == [
        {"version": 1, "turn_id": "turn-1"},
        {"version": 1, "turn_id": "turn-2"},
    ]
    assert session.saved_payload["workspace_artifact_roots"] == {}
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is True
