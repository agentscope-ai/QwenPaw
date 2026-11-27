# -*- coding: utf-8 -*-
"""Protected persistence for a self-hosted Relay node identity."""

from __future__ import annotations

import base64
import asyncio
from dataclasses import asdict, dataclass, field
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from ..security.secret_store import decrypt, encrypt
from ..utils.io_utils import read_json, write_json_atomic
from .identity import RelayKeyPair
from .platform_client import PlatformSession, RegisteredNode


@dataclass(frozen=True, slots=True)
class RelayNodeState:
    """All local state needed to resume or operate one Relay binding."""

    platform_url: str
    qwenpaw_id: str
    name: str
    private_key: bytes = field(repr=False)
    registered_node: RegisteredNode | None = None
    account_id: str | None = None
    account_name: str | None = None
    session: PlatformSession | None = None
    runtime_id: str | None = None

    @property
    def key_pair(self) -> RelayKeyPair:
        """Restore the Node signing key without exposing it over an API."""
        return RelayKeyPair.from_private_bytes(self.private_key)


class RelayNodeStore:
    """Atomically store one encrypted Relay node identity."""

    def __init__(
        self,
        path: Path,
        *,
        protect: Callable[[str], str] = encrypt,
        unprotect: Callable[[str], str] = decrypt,
    ) -> None:
        self.path = path
        self._protect = protect
        self._unprotect = unprotect
        self.mutation_lock = asyncio.Lock()

    def load(self) -> RelayNodeState | None:
        """Read the current state, returning None when it does not exist."""
        if not self.path.exists():
            return None
        payload = read_json(self.path)
        if not isinstance(payload, Mapping):
            raise ValueError("Relay node state must be a JSON object")
        registered = payload.get("registered_node")
        session = payload.get("session")
        return RelayNodeState(
            platform_url=_string(payload, "platform_url"),
            qwenpaw_id=_string(payload, "qwenpaw_id"),
            name=_string(payload, "name"),
            private_key=base64.urlsafe_b64decode(
                self._unprotect(_string(payload, "private_key")),
            ),
            account_id=payload.get("account_id"),
            account_name=payload.get("account_name"),
            runtime_id=payload.get("runtime_id"),
            session=(
                PlatformSession(
                    user_id=_string(session, "user_id"),
                    display_name=_string(session, "display_name"),
                    access_token=self._unprotect(
                        _string(session, "access_token"),
                    ),
                    refresh_token=self._unprotect(
                        _string(session, "refresh_token"),
                    ),
                    expires_at=float(session["expires_at"]),
                )
                if isinstance(session, Mapping)
                else None
            ),
            registered_node=(
                RegisteredNode(
                    node_id=_string(registered, "node_id"),
                    credential=self._unprotect(
                        _string(registered, "credential"),
                    ),
                    dpop_nonce=_string(registered, "dpop_nonce"),
                    credential_generation=_integer(
                        registered,
                        "credential_generation",
                    ),
                )
                if isinstance(registered, Mapping)
                else None
            ),
        )

    def save(self, state: RelayNodeState) -> None:
        """Encrypt credentials and atomically replace the state file."""
        registered = None
        session = None
        if state.session is not None:
            session = asdict(state.session)
            session["access_token"] = self._protect(state.session.access_token)
            session["refresh_token"] = self._protect(
                state.session.refresh_token,
            )
        if state.registered_node is not None:
            registered = asdict(state.registered_node)
            registered["credential"] = self._protect(
                state.registered_node.credential,
            )
        write_json_atomic(
            self.path,
            {
                "version": 1,
                "platform_url": state.platform_url,
                "qwenpaw_id": state.qwenpaw_id,
                "name": state.name,
                "private_key": self._protect(
                    base64.urlsafe_b64encode(state.private_key).decode(
                        "ascii",
                    ),
                ),
                "registered_node": registered,
                "account_id": state.account_id,
                "account_name": state.account_name,
                "session": session,
                "runtime_id": state.runtime_id,
            },
            indent=2,
            sort_keys=True,
            new_file_mode=0o600,
        )

    @staticmethod
    def create(
        *,
        platform_url: str,
        qwenpaw_id: str,
        name: str,
    ) -> RelayNodeState:
        """Create a new encrypted signing identity in memory."""
        key_pair = RelayKeyPair.generate()
        return RelayNodeState(
            platform_url=platform_url,
            qwenpaw_id=qwenpaw_id,
            name=name,
            private_key=key_pair.private_bytes(),
        )


def _string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Relay node state is missing {name}")
    return value


def _integer(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Relay node state is missing {name}")
    return value
