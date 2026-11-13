# -*- coding: utf-8 -*-
"""Fingerprint-anchored, single-use approval tokens."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from ..errors import BrowserError, ErrorCategory


def fingerprint(
    *,
    origin: str,
    action: str,
    key_params: dict[str, Any],
) -> str:
    """Hash system-extracted operation facts deterministically."""
    material = json.dumps(
        {"origin": origin, "action": action, "params": key_params},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Token:
    nonce: str
    fp: str
    expires_at: float


def _rejected(reason: str) -> BrowserError:
    return BrowserError(
        category=ErrorCategory.ASK_HUMAN,
        suggested_action="re-request approval",
        reason=reason,
    )


class TokenBroker:
    def __init__(self, ttl: float = 60.0) -> None:
        self._ttl = ttl
        self._issued: dict[str, Token] = {}
        self._consumed: set[str] = set()

    def issue(
        self,
        *,
        origin: str,
        action: str,
        key_params: dict[str, Any],
    ) -> Token:
        token = Token(
            nonce=secrets.token_hex(16),
            fp=fingerprint(
                origin=origin,
                action=action,
                key_params=key_params,
            ),
            expires_at=time.monotonic() + self._ttl,
        )
        self._issued[token.nonce] = token
        return token

    def verify_and_consume(
        self,
        *,
        nonce: str,
        origin: str,
        action: str,
        key_params: dict[str, Any],
    ) -> None:
        token = self._issued.get(nonce)
        if token is None or nonce in self._consumed:
            raise _rejected("token missing or already consumed")
        if time.monotonic() >= token.expires_at:
            raise _rejected("token expired")
        actual = fingerprint(
            origin=origin,
            action=action,
            key_params=key_params,
        )
        if not secrets.compare_digest(actual, token.fp):
            raise _rejected("fingerprint mismatch (presentation spoof guard)")
        self._consumed.add(nonce)
