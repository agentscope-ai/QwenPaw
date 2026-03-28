# -*- coding: utf-8 -*-
"""Property-based tests for CommandClassifier —
Dynamic Registration Immediate Effect.

Feature: dual-queue-messaging, Property 9: 动态注册即时生效

Validates: Requirement 9.2

For any newly registered command via
``register_command(name, handler, priority)``,
the CommandClassifier SHALL immediately recognize messages matching
that command
and route them to the CommandQueue, without restart or
re-initialization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentscope.message import Msg, TextBlock
from hypothesis import given, settings
from hypothesis import strategies as st

from copaw.app.channels.manager import ChannelManager
from copaw.app.runner.command_router import CommandPriority, CommandRouter


# ---------------------------------------------------------------------------
# Known built-in command names (to exclude from generated names)
# ---------------------------------------------------------------------------
DAEMON_COMMANDS = frozenset(
    [
        "stop",
        "status",
        "restart",
        "reload-config",
        "version",
        "logs",
        "approve",
    ]
)
CONVERSATION_COMMANDS = frozenset(
    [
        "compact",
        "new",
        "clear",
        "history",
        "compact_str",
        "await_summary",
        "message",
        "dump_history",
        "load_history",
    ]
)
ALL_KNOWN_COMMANDS = DAEMON_COMMANDS | CONVERSATION_COMMANDS | {"daemon"}


# ---------------------------------------------------------------------------
# Minimal stubs (same _FakeChannel pattern from test_classify_command.py)
# ---------------------------------------------------------------------------


@dataclass
class _FakeContent:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeInput:
    content: list[Any] | None = None


@dataclass
class _FakeRequest:
    input: list[Any] | None = None


class _FakeChannel:
    """Minimal BaseChannel stub for classify_command tests."""

    channel = "test"

    def _payload_to_request(self, payload: Any) -> _FakeRequest:
        if isinstance(payload, str):
            return _FakeRequest(
                input=[
                    _FakeInput(
                        content=[_FakeContent(type="text", text=payload)]
                    )
                ],
            )
        raise ValueError("bad payload")

    def get_debounce_key(self, payload: Any) -> str:
        return "key"


def _make_manager_with_router() -> (
    tuple[ChannelManager, _FakeChannel, CommandRouter]
):
    """Create a ChannelManager with a CommandRouter attached."""
    ch = _FakeChannel()
    mgr = ChannelManager(channels=[])
    router = CommandRouter(task_tracker=None, runner=None)
    mgr.set_command_router(router)
    return mgr, ch, router


# ---------------------------------------------------------------------------
# Strategy: generate lowercase alpha command names (2-15 chars)
# that are NOT in the existing built-in command set.
# ---------------------------------------------------------------------------
_new_command_name_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll",), whitelist_characters=""
    ),
    min_size=2,
    max_size=15,
).filter(lambda s: s.isalpha() and s not in ALL_KNOWN_COMMANDS)


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 9: 动态注册即时生效
# ---------------------------------------------------------------------------
class TestDynamicRegistrationImmediateEffect:
    """Property 9: Dynamic Registration Immediate Effect.

    For any newly registered command, the CommandClassifier immediately
    recognizes matching messages and routes them to the CommandQueue,
    without restart or re-initialization.

    **Validates: Requirement 9.2**
    """

    @given(cmd_name=_new_command_name_st)
    @settings(max_examples=100)
    def test_dynamic_registration_immediate_effect(
        self, cmd_name: str
    ) -> None:
        """Newly registered commands are immediately recognized
        by _classify_command.

        Label: Feature: dual-queue-messaging, Property 9: 动态注册即时生效
        """
        mgr, ch, router = _make_manager_with_router()

        # 1. Before registration: classifier should NOT recognize the command
        before = mgr._classify_command(ch, f"/{cmd_name}")
        assert before is None, (
            f"/{cmd_name} should NOT be recognized before registration, "
            f"got: {before}"
        )

        # 2. Register the command dynamically
        async def _noop_handler(ctx: Any) -> Msg:
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=f"handled /{cmd_name}")],
            )

        router.register_command(
            cmd_name, _noop_handler, CommandPriority.NORMAL
        )

        # 3. After registration: classifier should immediately recognize it
        after = mgr._classify_command(ch, f"/{cmd_name}")
        assert (
            after is not None
        ), f"/{cmd_name} should be recognized immediately after registration"
        assert after == (
            cmd_name,
            [],
        ), f"Expected ('{cmd_name}', []) after registration, got: {after}"
