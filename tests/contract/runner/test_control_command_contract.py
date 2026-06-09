# -*- coding: utf-8 -*-
"""Contract tests for :class:`BaseControlCommandHandler` subclasses.

These tests pin down the contract that anything registered into the
control-command dispatch table must satisfy.  When a future handler is
added (or the base interface drifts) these tests fail before integration
tests get a chance to surface a more confusing symptom.

Specifically:

- every subclass has a non-empty ``command_name`` starting with ``/``;
- every subclass implements an *async* ``handle`` returning ``str``;
- the global registry includes all six default handlers;
- the registry rejects empty ``command_name`` registrations.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import inspect
from typing import get_type_hints

import pytest

from qwenpaw.app.runner import control_commands
from qwenpaw.app.runner.control_commands.base import (
    BaseControlCommandHandler,
)


_EXPECTED_DEFAULTS = {
    "/approval",
    "/approve",
    "/deny",
    "/model",
    "/skills",
    "/stop",
}


def _all_subclasses(cls: type) -> set[type]:
    """Return *cls* and all transitively-defined subclasses."""
    direct = set(cls.__subclasses__())
    nested: set[type] = set()
    for sub in direct:
        nested.update(_all_subclasses(sub))
    return direct | nested


# ---------------------------------------------------------------------------
# Discoverable subclasses
# ---------------------------------------------------------------------------


def _concrete_handlers() -> list[type[BaseControlCommandHandler]]:
    """Return all non-abstract subclasses of BaseControlCommandHandler."""
    subs = _all_subclasses(BaseControlCommandHandler)
    return [cls for cls in subs if not inspect.isabstract(cls)]


def test_at_least_six_concrete_handlers_are_discoverable():
    # Sanity guard: if a refactor accidentally drops a default handler,
    # this assertion catches it before the runtime dispatch does.
    handlers = _concrete_handlers()

    assert len(handlers) >= 6, (
        "Expected at least 6 default control command handlers; "
        f"found {len(handlers)}: "
        f"{sorted(c.__name__ for c in handlers)}"
    )


@pytest.mark.parametrize(
    "handler_cls",
    _concrete_handlers(),
    ids=lambda c: c.__name__,
)
def test_handler_has_non_empty_slash_command_name(handler_cls):
    name = handler_cls.command_name

    assert isinstance(name, str), (
        f"{handler_cls.__name__}.command_name must be str, "
        f"got {type(name).__name__}"
    )
    assert name, f"{handler_cls.__name__}.command_name is empty"
    assert name.startswith("/"), (
        f"{handler_cls.__name__}.command_name must start with '/', "
        f"got {name!r}"
    )
    # No whitespace inside the command token.
    assert " " not in name.strip(
        "/",
    ), f"{handler_cls.__name__}.command_name has whitespace: {name!r}"


@pytest.mark.parametrize(
    "handler_cls",
    _concrete_handlers(),
    ids=lambda c: c.__name__,
)
def test_handler_handle_is_async_and_takes_context(handler_cls):
    handle = getattr(handler_cls, "handle", None)
    assert handle is not None, f"{handler_cls.__name__} missing handle()"
    assert asyncio.iscoroutinefunction(
        handle,
    ), f"{handler_cls.__name__}.handle must be async"

    sig = inspect.signature(handle)
    params = list(sig.parameters.values())
    # (self, context) -> str
    assert len(params) == 2, (
        f"{handler_cls.__name__}.handle expected 2 params (self, context), "
        f"got {[p.name for p in params]}"
    )

    # Return annotation should be ``str`` when present.
    try:
        hints = get_type_hints(handle)
    except (NameError, TypeError):
        hints = {}
    if "return" in hints:
        assert hints["return"] is str, (
            f"{handler_cls.__name__}.handle should return str, "
            f"annotated {hints['return']}"
        )


# ---------------------------------------------------------------------------
# Registry expectations
# ---------------------------------------------------------------------------


def test_registry_contains_all_six_default_commands():
    registered = set(control_commands._COMMAND_REGISTRY.keys())

    missing = _EXPECTED_DEFAULTS - registered
    assert not missing, f"Missing default control commands: {missing}"


@pytest.mark.parametrize("command", sorted(_EXPECTED_DEFAULTS))
def test_is_control_command_recognises_each_default(command):
    assert control_commands.is_control_command(command) is True
    # With trailing args, recognition still holds.
    assert control_commands.is_control_command(f"{command} extra args") is True


def test_is_control_command_rejects_empty_and_non_command_input():
    assert control_commands.is_control_command(None) is False
    assert control_commands.is_control_command("") is False
    assert control_commands.is_control_command("hello") is False
    assert control_commands.is_control_command("/totally-bogus") is False
    # Non-string defensively rejected.
    bogus_input: object = 123
    assert control_commands.is_control_command(bogus_input) is False


# ---------------------------------------------------------------------------
# register_command guard rails
# ---------------------------------------------------------------------------


def test_register_command_rejects_empty_command_name():
    class _Bad(BaseControlCommandHandler):
        command_name = ""  # invalid

        async def handle(self, context):  # noqa: D401
            return "noop"

    with pytest.raises(ValueError):
        control_commands.register_command(_Bad())


def test_unregister_unknown_command_returns_false():
    assert control_commands.unregister_command("/never-registered") is False
