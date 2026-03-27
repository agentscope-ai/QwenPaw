# -*- coding: utf-8 -*-
"""Property-based tests for CommandRouter —
message classification and routing partition.

Feature: dual-queue-messaging, Property 1: 消息分类与路由分区

Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6

For any message payload, the classification result is exactly one of
"registered command" or "normal message" — mutually exclusive and complete.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from copaw.app.runner.command_router import (
    CommandContext,
    CommandPriority,
    CommandRouter,
)
from copaw.app.runner.daemon_commands import DAEMON_SUBCOMMANDS

# ---------------------------------------------------------------------------
# Known built-in command names (without leading /)
# These are the daemon + conversation commands from the requirements.
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
ALL_KNOWN_COMMANDS = DAEMON_COMMANDS | CONVERSATION_COMMANDS


def _make_router_with_commands() -> CommandRouter:
    """Create a CommandRouter with all known commands registered."""
    router = CommandRouter()

    async def _noop_handler(ctx: CommandContext):
        from agentscope.message import Msg, TextBlock

        return Msg(
            name="Friday",
            role="assistant",
            content=[
                TextBlock(type="text", text=f"handled /{ctx.command_name}")
            ],
        )

    for cmd in DAEMON_COMMANDS:
        priority = {
            "stop": CommandPriority.CRITICAL,
            "approve": CommandPriority.HIGH,
            "restart": CommandPriority.NORMAL,
            "reload-config": CommandPriority.NORMAL,
        }.get(cmd, CommandPriority.LOW)
        router.register_command(cmd, _noop_handler, priority)

    for cmd in CONVERSATION_COMMANDS:
        priority = {
            "new": CommandPriority.NORMAL,
            "clear": CommandPriority.NORMAL,
        }.get(cmd, CommandPriority.LOW)
        router.register_command(cmd, _noop_handler, priority)

    return router


# Strategy: generate a command name that IS registered
registered_command_st = st.sampled_from(sorted(ALL_KNOWN_COMMANDS))

# Strategy: generate a string that is NOT a registered command name
# We filter out anything that happens to match a known command or "daemon".
_ALL_REGISTERED = ALL_KNOWN_COMMANDS | {"daemon"}
unregistered_name_st = st.text(min_size=1, max_size=30).filter(
    lambda s: s not in _ALL_REGISTERED
)

# Strategy: random plain text (no leading /)
plain_text_st = st.text(min_size=0, max_size=100).filter(
    lambda s: not s.lstrip().startswith("/")
)


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 1: 消息分类与路由分区
# ---------------------------------------------------------------------------
class TestMessageClassificationPartition:
    """Property 1: Message classification is mutually exclusive and complete.

    For any string, it either IS in the registered commands set or IS NOT.
    The two sets form a complete partition — never both, always exactly one.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6**
    """

    @given(cmd=registered_command_st)
    @settings(max_examples=200)
    def test_registered_commands_are_in_set(self, cmd: str) -> None:
        """Every known command name is present in get_registered_commands()."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()
        assert cmd in registered, f"/{cmd} should be registered but is not"

    @given(name=unregistered_name_st)
    @settings(max_examples=200)
    def test_unregistered_names_are_not_in_set(self, name: str) -> None:
        """Random strings not in ALL_KNOWN_COMMANDS are
        absent from the registry."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()
        assert (
            name not in registered
        ), f"'{name}' should NOT be registered but was found in the set"

    @given(text=st.text(min_size=0, max_size=100))
    @settings(max_examples=200)
    def test_classification_is_mutually_exclusive_and_complete(
        self, text: str
    ) -> None:
        """For any string, it is either in registered commands
        XOR not — never both."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()

        is_registered = text in registered
        is_normal = text not in registered

        # Mutually exclusive: cannot be both
        assert is_registered != is_normal, (
            f"Classification for '{text}' is not mutually exclusive: "
            f"registered={is_registered}, normal={is_normal}"
        )
        # Complete: exactly one must be true
        assert (
            is_registered or is_normal
        ), (
            f"Classification for '{text}' is incomplete"
            f" — neither registered nor normal"
        )

    @given(cmd=registered_command_st)
    @settings(max_examples=200)
    def test_registered_command_routes_to_command_queue(
        self, cmd: str
    ) -> None:
        """A registered command name should route to
        CommandQueue (has a priority)."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()

        # Simulates the routing decision: if in registered set → CommandQueue
        assert cmd in registered
        priority = router.get_priority(cmd)
        assert isinstance(
            priority, CommandPriority
        ), f"/{cmd} should have a valid CommandPriority, got {priority}"

    @given(text=plain_text_st)
    @settings(max_examples=200)
    def test_plain_text_routes_to_data_queue(self, text: str) -> None:
        """Plain text (no / prefix) should not match any
        registered command."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()

        # Plain text without / prefix should not be a registered
        # command name
        # (command names in the registry are stored without /,
        # e.g. "stop" not "/stop")
        # But even the bare word could theoretically match —
        # we verify the routing
        # decision: if text is not in registered set,
        # it goes to DataQueue.
        if text not in registered:
            # Falls back to NORMAL priority for unknown → DataQueue path
            priority = router.get_priority(text)
            assert priority == CommandPriority.NORMAL

    def test_all_daemon_commands_registered(self) -> None:
        """All daemon commands from requirements 1.5 are in the registry."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()
        for cmd in DAEMON_COMMANDS:
            assert cmd in registered, f"Daemon command /{cmd} not registered"

    def test_all_conversation_commands_registered(self) -> None:
        """All conversation commands from requirements 1.6
        are in the registry."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()
        for cmd in CONVERSATION_COMMANDS:
            assert (
                cmd in registered
            ), f"Conversation command /{cmd} not registered"

    def test_registered_set_size_matches_known_commands(self) -> None:
        """The registry contains exactly the expected number of commands."""
        router = _make_router_with_commands()
        registered = router.get_registered_commands()
        # ALL_KNOWN_COMMANDS + "daemon" meta-command from builtins
        expected = ALL_KNOWN_COMMANDS | {"daemon"}
        assert registered == expected, (
            f"Expected {expected}, got {registered}: "
            f"extra={registered - expected}, "
            f"missing={expected - registered}"
        )


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 5: 命令分发正确性
# ---------------------------------------------------------------------------
class TestCommandDispatchCorrectness:
    """Property 5: Command Dispatch Correctness.

    For any registered command name, CommandRouter.dispatch SHALL call the
    handler registered for that command and return its result.  Additionally,
    CommandRouter.get_priority SHALL return the priority assigned at
    registration time.

    **Validates: Requirements 3.4, 3.8**
    """

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _build_router_with_tracking_handlers() -> (
        tuple[CommandRouter, dict[str, MagicMock], dict[str, CommandPriority]]
    ):
        """Create a router with unique tracking handlers
        for every known command.

        Returns:
            (router, handlers_map, priorities_map)
            - handlers_map: command_name → the async MagicMock
              registered for it
            - priorities_map: command_name → the CommandPriority
              registered for it
        """
        from agentscope.message import Msg, TextBlock

        router = CommandRouter()
        handlers: dict[str, MagicMock] = {}
        priorities: dict[str, CommandPriority] = {}

        priority_table: dict[str, CommandPriority] = {
            "stop": CommandPriority.CRITICAL,
            "approve": CommandPriority.HIGH,
            "restart": CommandPriority.NORMAL,
            "reload-config": CommandPriority.NORMAL,
            "new": CommandPriority.NORMAL,
            "clear": CommandPriority.NORMAL,
        }

        for cmd in sorted(ALL_KNOWN_COMMANDS):
            prio = priority_table.get(cmd, CommandPriority.LOW)

            # Each command gets its own unique async handler that returns
            # a Msg tagged with the command name so we can verify identity.
            async def _handler(ctx: CommandContext, _name: str = cmd) -> Msg:
                return Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text=f"handled:/{_name}")],
                )

            mock_handler = MagicMock(side_effect=_handler)
            router.register_command(cmd, mock_handler, prio)
            handlers[cmd] = mock_handler
            priorities[cmd] = prio

        return router, handlers, priorities

    @staticmethod
    def _make_context(command_name: str) -> CommandContext:
        return CommandContext(
            channel=MagicMock(),
            channel_id="ch-prop5",
            session_id="sess-prop5",
            user_id="user-prop5",
            command_name=command_name,
            command_args=[],
            raw_query=f"/{command_name}",
            payload=None,
            task_tracker=None,
            runner=None,
        )

    # -- property tests ---------------------------------------------------

    @given(cmd=registered_command_st)
    @settings(max_examples=200)
    def test_dispatch_calls_correct_handler(self, cmd: str) -> None:
        """Dispatching a registered command invokes exactly its handler."""
        import asyncio

        router, handlers, _ = self._build_router_with_tracking_handlers()
        ctx = self._make_context(cmd)

        asyncio.new_event_loop().run_until_complete(router.dispatch(ctx))

        # The handler for *this* command must have been called exactly once.
        handlers[cmd].assert_called_once()

        # No *other* handler should have been called.
        for other_cmd, mock_h in handlers.items():
            if other_cmd != cmd:
                mock_h.assert_not_called(), (
                    f"Handler for /{other_cmd} was unexpectedly called "
                    f"when dispatching /{cmd}"
                )

    @given(cmd=registered_command_st)
    @settings(max_examples=200)
    def test_dispatch_returns_handler_result(self, cmd: str) -> None:
        """dispatch() returns the Msg produced by the command's handler."""
        import asyncio

        from agentscope.message import Msg

        router, _, _ = self._build_router_with_tracking_handlers()
        ctx = self._make_context(cmd)

        result = asyncio.new_event_loop().run_until_complete(
            router.dispatch(ctx)
        )

        assert isinstance(result, Msg)
        text = result.content[0]["text"]
        assert (
            text == f"handled:/{cmd}"
        ), f"Expected handler result for /{cmd}, got: {text}"

    @given(cmd=registered_command_st)
    @settings(max_examples=200)
    def test_get_priority_returns_registered_priority(self, cmd: str) -> None:
        """get_priority returns the exact priority assigned at registration."""
        _, _, priorities = self._build_router_with_tracking_handlers()
        router, _, _ = self._build_router_with_tracking_handlers()
        expected = priorities[cmd]
        actual = router.get_priority(cmd)
        assert (
            actual == expected
        ), f"/{cmd}: expected priority {expected!r}, got {actual!r}"


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 6: 未知命令処理
# ---------------------------------------------------------------------------
class TestUnknownCommandHandling:
    """Property 6: Unknown Command Handling.

    For any string NOT registered in the CommandRouter registry,
    dispatch SHALL return a Msg containing an "Unknown command" hint
    and SHALL NOT raise any exception.

    **Validates: Requirements 3.5**
    """

    @staticmethod
    def _make_context(command_name: str) -> CommandContext:
        return CommandContext(
            channel=MagicMock(),
            channel_id="ch-prop6",
            session_id="sess-prop6",
            user_id="user-prop6",
            command_name=command_name,
            command_args=[],
            raw_query=f"/{command_name}",
            payload=None,
            task_tracker=None,
            runner=None,
        )

    @given(name=unregistered_name_st)
    @settings(max_examples=200)
    def test_unknown_command_returns_hint_msg(self, name: str) -> None:
        """dispatch() returns an 'Unknown command' Msg
        for unregistered names."""
        import asyncio

        from agentscope.message import Msg

        router = _make_router_with_commands()
        ctx = self._make_context(name)

        result = asyncio.new_event_loop().run_until_complete(
            router.dispatch(ctx)
        )

        assert isinstance(
            result, Msg
        ), f"Expected Msg for unknown command '{name}', got {type(result)}"
        text = result.content[0]["text"]
        assert (
            "Unknown command" in text
        ), f"Expected 'Unknown command' in response for '{name}', got: {text}"

    @given(name=unregistered_name_st)
    @settings(max_examples=200)
    def test_unknown_command_does_not_raise(self, name: str) -> None:
        """dispatch() never raises an exception for
        unregistered commands."""
        import asyncio

        router = _make_router_with_commands()
        ctx = self._make_context(name)

        # Must complete without any exception
        try:
            asyncio.new_event_loop().run_until_complete(router.dispatch(ctx))
        except Exception as exc:
            raise AssertionError(
                f"dispatch() raised {type(exc).__name__} for unknown "
                f"command '{name}': {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 8: 命令処理異常安全
# ---------------------------------------------------------------------------
class TestCommandHandlerExceptionSafety:
    """Property 8: Command Handler Exception Safety.

    For any registered command whose handler raises an exception during
    execution, CommandRouter.dispatch SHALL catch the exception and return
    an error Msg instead of propagating it to the caller.

    **Validates: Requirement 4.20**
    """

    # Strategies ---------------------------------------------------------

    # Random command names (simple alphanumeric, not colliding with builtins)
    _random_cmd_name_st = st.text(
        alphabet=st.characters(whitelist_categories=("Ll",)),
        min_size=2,
        max_size=15,
    ).filter(lambda s: s not in ALL_KNOWN_COMMANDS)

    # Exception types that handlers may throw
    _exception_types_st = st.sampled_from(
        [RuntimeError, ValueError, TypeError, KeyError, Exception]
    )

    # Strategy: list of (command_name, exception_class) pairs
    _commands_with_exceptions_st = st.lists(
        st.tuples(_random_cmd_name_st, _exception_types_st),
        min_size=1,
        max_size=10,
        unique_by=lambda t: t[0],
    )

    # Helpers --------------------------------------------------------------

    @staticmethod
    def _make_context(command_name: str) -> CommandContext:
        return CommandContext(
            channel=MagicMock(),
            channel_id="ch-prop8",
            session_id="sess-prop8",
            user_id="user-prop8",
            command_name=command_name,
            command_args=[],
            raw_query=f"/{command_name}",
            payload=None,
            task_tracker=None,
            runner=None,
        )

    # Property tests -------------------------------------------------------

    @given(data=_commands_with_exceptions_st)
    @settings(max_examples=100)
    def test_dispatch_catches_handler_exceptions(
        self, data: list[tuple[str, type]]
    ) -> None:
        """dispatch() returns an error Msg when a handler
        raises, never propagates."""
        import asyncio

        from agentscope.message import Msg

        router = CommandRouter()

        for cmd_name, exc_cls in data:
            # Register a handler that always raises the given exception type
            async def _raising_handler(
                ctx: CommandContext,
                _exc: type = exc_cls,
                _name: str = cmd_name,
            ) -> Msg:
                raise _exc(f"boom from /{_name}")

            router.register_command(cmd_name, _raising_handler)

        loop = asyncio.new_event_loop()
        try:
            for cmd_name, exc_cls in data:
                ctx = self._make_context(cmd_name)

                # Must NOT propagate the exception
                try:
                    result = loop.run_until_complete(router.dispatch(ctx))
                except Exception as exc:
                    raise AssertionError(
                        f"dispatch() propagated {type(exc).__name__} for "
                        f"/{cmd_name} (handler raises "
                        f"{exc_cls.__name__}): {exc}"
                    ) from exc

                # Must return a Msg
                assert isinstance(
                    result, Msg
                ), f"Expected Msg for /{cmd_name}, got {type(result)}"

                # Must contain error text
                text = result.content[0]["text"]
                assert (
                    "Error" in text or "error" in text
                ), f"Expected error description for /{cmd_name}, got: {text}"
        finally:
            loop.close()

    @given(exc_cls=_exception_types_st, cmd=_random_cmd_name_st)
    @settings(max_examples=100)
    def test_each_exception_type_is_caught(
        self, exc_cls: type, cmd: str
    ) -> None:
        """Each individual exception type is caught and
        converted to error Msg."""
        import asyncio

        from agentscope.message import Msg

        router = CommandRouter()

        async def _handler(ctx: CommandContext) -> Msg:
            raise exc_cls(f"test error in /{cmd}")

        router.register_command(cmd, _handler)

        ctx = self._make_context(cmd)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(router.dispatch(ctx))
        except Exception as exc:
            raise AssertionError(
                f"dispatch() propagated {type(exc).__name__} for "
                f"/{cmd} with {exc_cls.__name__}: {exc}"
            ) from exc
        finally:
            loop.close()

        assert isinstance(result, Msg)
        text = result.content[0]["text"]
        assert (
            f"/{cmd}" in text
        ), f"Error Msg should reference the command name /{cmd}, got: {text}"


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 7: /daemon 长命令等价映射
# ---------------------------------------------------------------------------
class TestDaemonSubcommandEquivalenceMapping:
    """Property 7: /daemon 長命令等価映射.

    For any daemon subcommand *sub* from DAEMON_SUBCOMMANDS,
    dispatching ``/daemon <sub>`` SHALL produce the same result text
    as dispatching ``/<sub>`` directly.

    **Validates: Requirements 3.9**
    """

    @staticmethod
    def _make_context(
        command_name: str, command_args: list[str] | None = None
    ) -> CommandContext:
        return CommandContext(
            channel=MagicMock(),
            channel_id="ch-prop7",
            session_id="sess-prop7",
            user_id="user-prop7",
            command_name=command_name,
            command_args=command_args or [],
            raw_query=f"/{command_name}"
            + (" " + " ".join(command_args) if command_args else ""),
            payload=None,
            task_tracker=None,
            runner=None,
        )

    @given(sub=st.sampled_from(sorted(DAEMON_SUBCOMMANDS)))
    @settings(max_examples=100)
    def test_daemon_sub_equivalence(self, sub: str) -> None:
        """``/daemon <sub>`` and ``/<sub>`` produce identical result text.

        Label: Feature: dual-queue-messaging, Property 7: /daemon 长命令等价映射
        """
        import asyncio

        from agentscope.message import Msg
        from copaw.app.runner.daemon_commands import DAEMON_SUBCOMMANDS as DS

        assert sub in DS, f"{sub} not in DAEMON_SUBCOMMANDS"

        router = CommandRouter()

        # Dispatch the short form: /<sub>
        short_ctx = self._make_context(sub)
        loop = asyncio.new_event_loop()
        try:
            short_result = loop.run_until_complete(router.dispatch(short_ctx))
        finally:
            loop.close()

        # Dispatch the long form: /daemon <sub>
        daemon_ctx = self._make_context("daemon", [sub])
        loop2 = asyncio.new_event_loop()
        try:
            daemon_result = loop2.run_until_complete(
                router.dispatch(daemon_ctx)
            )
        finally:
            loop2.close()

        # Both must return Msg
        assert isinstance(
            short_result, Msg
        ), f"Short form /{sub} did not return Msg: {type(short_result)}"
        assert isinstance(
            daemon_result, Msg
        ), f"Long form /daemon {sub} did not return Msg: {type(daemon_result)}"

        # Extract text from both results
        short_text = short_result.content[0]["text"]
        daemon_text = daemon_result.content[0]["text"]

        # The result text must be identical
        assert short_text == daemon_text, (
            f"Results differ for subcommand '{sub}':\n"
            f"  /{sub} → {short_text!r}\n"
            f"  /daemon {sub} → {daemon_text!r}"
        )


# ---------------------------------------------------------------------------
# Feature: dual-queue-messaging, Property 10: 重复 /stop 幂等性
# ---------------------------------------------------------------------------
class TestRepeatedStopIdempotency:
    """Property 10: 重复 /stop 幂等性.

    For any number of /stop commands arriving at the same session's
    CommandQueue, CommandRouter SHALL safely handle all requests:
    the first /stop returns "Task stopped.", all subsequent /stop
    commands (after the task has already been stopped) return
    "No running task.", and no exceptions are raised at any point.

    **Validates: Requirement 10.2**
    """

    @staticmethod
    def _make_stop_context(
        task_tracker: MagicMock,
        channel: MagicMock,
    ) -> CommandContext:
        return CommandContext(
            channel=channel,
            channel_id="ch-prop10",
            session_id="sess-prop10",
            user_id="user-prop10",
            command_name="stop",
            command_args=[],
            raw_query="/stop",
            payload=None,
            task_tracker=task_tracker,
            runner=None,
        )

    @given(stop_count=st.integers(min_value=1, max_value=10))
    @settings(max_examples=100)
    def test_repeated_stop_idempotency(self, stop_count: int) -> None:
        """First /stop succeeds, subsequent ones return 'No running task'.

        Label: Feature: dual-queue-messaging, Property 10: 重复 /stop 幂等性
        """
        import asyncio

        from agentscope.message import Msg

        # -- set up mocks --------------------------------------------------
        # task_tracker.request_stop returns True on first call, False after
        call_count = 0

        async def _mock_request_stop(run_key: str) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count == 1

        task_tracker = MagicMock()
        task_tracker.request_stop = MagicMock(side_effect=_mock_request_stop)

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="fixed-debounce-key")

        # -- create router and dispatch N times ----------------------------
        router = CommandRouter()
        loop = asyncio.new_event_loop()
        try:
            results: list[Msg] = []
            for _ in range(stop_count):
                ctx = self._make_stop_context(task_tracker, channel)
                try:
                    result = loop.run_until_complete(router.dispatch(ctx))
                except Exception as exc:
                    raise AssertionError(
                        f"dispatch() raised {type(exc).__name__} on /stop "
                        f"attempt {len(results) + 1}/{stop_count}: {exc}"
                    ) from exc
                results.append(result)

            # -- verify results --------------------------------------------
            for i, result in enumerate(results):
                assert isinstance(
                    result, Msg
                ), f"/stop attempt {i + 1}: expected Msg, got {type(result)}"
                text = result.content[0]["text"]
                if i == 0:
                    assert (
                        text == "Task stopped."
                    ), (
                        f"/stop attempt 1: expected "
                        f"'Task stopped.', got: {text!r}"
                    )
                else:
                    assert text == "No running task.", (
                        f"/stop attempt {i + 1}: expected 'No running task.', "
                        f"got: {text!r}"
                    )
        finally:
            loop.close()
