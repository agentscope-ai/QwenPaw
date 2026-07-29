# -*- coding: utf-8 -*-
"""The method vocabulary has to mean the same thing on both sides of the wire.

The adapter and the native helper are written in different languages and share
no build step, so their agreement rests on two lists of strings staying in
step.
Nothing catches a drift: a method only one side knows fails at run time as an
unsupported operation, on whichever machine happens to try it.

This reads the helper's dispatch and compares it against the adapter's declared
vocabulary, so a name added or renamed on one side alone fails here instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from computer_use_tool.protocol import (
    NATIVE_METHODS,
    ComputerUseProtocolError,
    NativeRequest,
)

_DISPATCH = (
    Path(__file__).resolve().parents[4]
    / "console"
    / "src-tauri"
    / "src"
    / "computer_use_server"
    / "dispatch.rs"
)

# A method the helper answers but the adapter never sends. Listed rather than
# ignored, so unused protocol surface stays visible instead of accumulating.
_HELPER_ONLY = frozenset({"perform_secondary_action"})


def _methods_the_helper_handles() -> set[str]:
    """Extract the method names the helper's dispatch acts on."""
    source = _DISPATCH.read_text(encoding="utf-8")
    handled = set(re.findall(r'^\s*"([a-z_]+)"\s*(?:=>|\|)', source, re.M))
    handled |= set(re.findall(r'method == "([a-z_]+)"', source))
    return handled


def test_the_helper_handles_every_method_the_adapter_sends() -> None:
    handled = _methods_the_helper_handles()
    # ``hello`` is answered during the handshake, before dispatch sees
    # anything.
    sent = NATIVE_METHODS - {"hello"}
    missing = sorted(sent - handled)
    assert not missing, (
        f"the adapter sends {missing}, which the helper's dispatch does not "
        "handle; they would fail as unsupported operations"
    )


def test_the_helper_answers_nothing_the_adapter_has_forgotten() -> None:
    """The other direction: surface the helper answers but nobody asks for.

    Not a failure in itself, but it has to be deliberate. Anything unexpected
    here is either a method the adapter stopped sending -- dead protocol -- or
    one it should be sending and does not.
    """
    handled = _methods_the_helper_handles()
    # The lock-screen predicate repeats action names; they are all sent.
    unused = sorted(handled - NATIVE_METHODS - _HELPER_ONLY)
    assert not unused, (
        f"the helper handles {unused}, which nothing sends; either wire it up "
        "or remove it"
    )


def test_the_guarded_set_is_a_subset_of_the_vocabulary() -> None:
    """Every guarded method must be a method that actually exists."""
    source = _DISPATCH.read_text(encoding="utf-8")
    after = source.split("fn changes_window_state")[1]
    # Stop at the function's closing brace, or the file's own tests below would
    # be read as part of the predicate.
    body = after.split("\n}")[0]
    guarded = set(re.findall(r'"([a-z_]+)"', body))
    assert guarded, "the predicate should list the guarded methods"
    assert guarded <= NATIVE_METHODS, sorted(guarded - NATIVE_METHODS)


def test_a_method_outside_the_vocabulary_never_reaches_the_wire() -> None:
    """The vocabulary is enforced where requests are serialized.

    Otherwise the constant would be documentation, and a typo would travel to
    the helper and come back as an unsupported operation.
    """
    request = NativeRequest(
        method="press_keys",
        params={},
        session_id="session",
        turn_id="turn",
        deadline_ms=1000,
    )
    with pytest.raises(ComputerUseProtocolError) as refusal:
        request.to_message()
    assert refusal.value.code == "invalid_request"


def test_every_declared_method_serializes() -> None:
    # The handshake is written directly by the transports rather than built as
    # a NativeRequest, but it is part of the same vocabulary.
    for method in sorted(NATIVE_METHODS):
        message = NativeRequest(
            method=method,
            params={},
            session_id="session",
            turn_id="turn",
            deadline_ms=1000,
        ).to_message()
        assert message["method"] == method
