# -*- coding: utf-8 -*-
"""Trusted-side approval mechanism for browser worker requests."""

from __future__ import annotations

from typing import Any

from .approval import Decision, Verdict
from .token import TokenBroker


class Adjudicator:
    """No-op trusted approver that exercises the token lifecycle.

    Real policy decisions, human approval, and asymmetric signing are
    intentionally reserved for the later browser policy work.
    """

    def __init__(self) -> None:
        self._tokens = TokenBroker()

    def adjudicate(
        self,
        *,
        origin: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Verdict:
        """Allow the request after issuing and consuming its trusted token."""
        key_params = dict(params or {})
        token = self._tokens.issue(
            origin=origin,
            action=method,
            key_params=key_params,
        )
        self._tokens.verify_and_consume(
            nonce=token.nonce,
            origin=origin,
            action=method,
            key_params=key_params,
        )
        return Verdict(Decision.ALLOW, "no-op adjudicator (mechanism only)")
