# -*- coding: utf-8 -*-
"""Runtime slash-command dispatch must use the user's own text.

Channels prepend quoted (replied-to) message context as a
``[quoted ...]`` block before the user's own text. The runtime dispatches
slash commands against the last user message's text, so a quoted reply
carrying ``/stop`` must resolve the command instead of reaching the
agent as plain chat (issue #8342).
"""

from __future__ import annotations

from types import SimpleNamespace

from agentscope.message import Msg, TextBlock

from qwenpaw.runtime.hooks import HookAction, HookResult
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import (
    AgentRequest,
    ContentType,
    Message,
    Role,
    TextContent,
)


def _request_with_text(text: str) -> AgentRequest:
    return AgentRequest(
        session_id="session-1",
        user_id="user-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(type=ContentType.TEXT, text=text)],
            ),
        ],
    )


def _ack_msg(text: str) -> Msg:
    return Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


def _runtime_with_recording_dispatch(
    recorded: list[str],
) -> Runtime:
    """Runtime with a dispatch fake mirroring the registry contract:
    resolve command text to a reply, leave non-commands to the hooks.
    """

    class RecordingSlashRegistry:
        async def dispatch(
            self,
            text: str,
            _ctx: object,
        ) -> Msg | None:
            recorded.append(text)
            if text.startswith("/"):
                return _ack_msg("stopped")
            return None

    class DispatchAwareHooks:
        async def run(
            self,
            phase: object,
            _ctx: object,
        ) -> HookResult:
            if getattr(phase, "name", "") == "POST_DISPATCH":
                return HookResult(
                    action=HookAction.SHORT_CIRCUIT,
                    payload=_ack_msg("ok"),
                )
            return HookResult(action=HookAction.CONTINUE)

    workspace = SimpleNamespace(
        workspace_dir=None,
        agent_id="default",
        plugins=SimpleNamespace(
            hook_registry=DispatchAwareHooks(),
            slash_command_registry=RecordingSlashRegistry(),
        ),
    )
    return Runtime(workspace=workspace, app_services=None)


async def test_quoted_reply_dispatches_user_command() -> None:
    recorded: list[str] = []
    runtime = _runtime_with_recording_dispatch(recorded)
    request = _request_with_text(
        "[quoted message: Alice: quarterly report]\n/stop",
    )

    events = [event async for event in runtime.run(request)]

    # The dispatch text is the user's own command, not the quoted context.
    assert recorded == ["/stop"]
    assert any(getattr(event, "text", "") == "stopped" for event in events)


async def test_plain_command_dispatch_unchanged() -> None:
    recorded: list[str] = []
    runtime = _runtime_with_recording_dispatch(recorded)
    request = _request_with_text("/stop")

    _ = [event async for event in runtime.run(request)]

    assert recorded == ["/stop"]


async def test_normal_quoted_chat_does_not_dispatch() -> None:
    recorded: list[str] = []
    runtime = _runtime_with_recording_dispatch(recorded)
    request = _request_with_text(
        "[quoted message: Alice: hi]\nare you there?",
    )

    events = [event async for event in runtime.run(request)]

    # Only the quoted text contained a command; the user's own text is
    # normal chat, so dispatch resolved nothing and the run fell through.
    assert recorded == ["are you there?"]
    assert not any(getattr(event, "text", "") == "stopped" for event in events)
