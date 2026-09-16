# -*- coding: utf-8 -*-
"""The method vocabulary has to mean the same thing on both sides of the wire.

The adapter and the native helper are written in different languages and share
no build step, so their agreement rests on two lists of strings staying in
step.
Nothing catches a drift: a method only one side knows fails at run time as an
unsupported operation, on whichever machine happens to try it.

Both sides state their vocabulary as a single declaration that the code
enforces rather than describes, and this compares the two. Reading a
declaration matters: an earlier version of this file parsed the helper's
dispatch, and reported a method as unhandled the first time two match arms were
grouped -- the code was right and the test was wrong, which is how a suite
teaches people to ignore it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from computer_use.protocol import (
    NATIVE_METHODS,
    PROTOCOL_VERSION,
    ComputerUseProtocolError,
    NativeRequest,
)
from qwenpaw.app.computer_use import COMPUTER_USE_PROTOCOL_VERSION

_SERVER = (
    Path(__file__).resolve().parents[4]
    / "console"
    / "src-tauri"
    / "src"
    / "computer_use_server"
)
_DISPATCH = _SERVER / "dispatch.rs"
_PROTOCOL = _SERVER.parent / "computer_use_protocol.rs"
_PLUGIN_PROTOCOL = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "bundle"
    / "computer-use"
    / "computer_use"
    / "protocol.py"
)

# A method the helper answers but the adapter never sends. Listed rather than
# ignored, so unused protocol surface stays visible instead of accumulating.
_HELPER_ONLY: frozenset[str] = frozenset()


def _rust_string_array(name: str) -> set[str]:
    """Read a `const NAME: &[&str] = [...]` declaration from the helper.

    Bounded to the literal's own brackets, so nothing after it is picked up.
    """
    source = _DISPATCH.read_text(encoding="utf-8")
    match = re.search(
        rf"const {name}: &\[&str\] = &\[(.*?)\];",
        source,
        re.S,
    )
    assert match, f"{name} should be declared in dispatch.rs"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def _methods_the_helper_serves() -> set[str]:
    """The helper's declared vocabulary, which its dispatch admits against."""
    served = _rust_string_array("SERVED_METHODS")
    assert served, "the helper should declare the methods it serves"
    return served


def test_the_helper_serves_every_method_the_adapter_sends() -> None:
    served = _methods_the_helper_serves()
    missing = sorted(NATIVE_METHODS - served)
    assert not missing, (
        f"the adapter sends {missing}, which the helper does not serve; they "
        "would fail as unsupported operations"
    )


def test_the_helper_serves_nothing_the_adapter_has_forgotten() -> None:
    """The other direction: surface the helper answers but nobody asks for.

    Not a failure in itself, but it has to be deliberate. Anything unexpected
    here is either a method the adapter stopped sending -- dead protocol -- or
    one it should be sending and does not.
    """
    unused = sorted(
        _methods_the_helper_serves() - NATIVE_METHODS - _HELPER_ONLY,
    )
    assert not unused, (
        f"the helper serves {unused}, which nothing sends; either wire it up "
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


def test_all_components_speak_the_same_protocol_version() -> None:
    """The independently installed components must reject contract drift.

    A mismatch is caught at run time as a refused handshake, so it cannot go
    unnoticed -- but it would be noticed by whoever is holding the machine,
    after a build and an install. Cheaper to notice here.
    """
    source = _PROTOCOL.read_text(encoding="utf-8")
    match = re.search(r"const VERSION: u64 = (\d+);", source)
    assert match, "the helper should declare its protocol version"
    plugin_source = _PLUGIN_PROTOCOL.read_text(encoding="utf-8")
    plugin_match = re.search(
        r"^PROTOCOL_VERSION = (\d+)$",
        plugin_source,
        re.M,
    )
    assert plugin_match, "the plugin should own its expected protocol version"
    assert {
        int(match.group(1)),
        int(plugin_match.group(1)),
        COMPUTER_USE_PROTOCOL_VERSION,
    } == {PROTOCOL_VERSION}


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
