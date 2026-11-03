# -*- coding: utf-8 -*-
"""Lifetime-scoped token counters independent of transport usage buffers."""

from dataclasses import dataclass
from weakref import WeakValueDictionary


@dataclass
class TokenCounter:
    """Accumulate model usage for as long as its owner retains the counter."""

    tokens: int = 0


_counters: WeakValueDictionary[str, TokenCounter] = WeakValueDictionary()


def track_session_tokens(session_id: str) -> TokenCounter:
    """Start a fresh counter without retaining completed goal objects."""
    counter = TokenCounter()
    _counters[session_id] = counter
    return counter


def record_session_tokens(session_id: str, tokens: int) -> None:
    """Record one model response before any transport consumes its usage."""
    counter = _counters.get(session_id)
    if counter is not None:
        counter.tokens += tokens
