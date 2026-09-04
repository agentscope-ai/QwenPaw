# -*- coding: utf-8 -*-
"""Protected persistence for a self-hosted Relay node identity."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from ..security.secret_store import decrypt, encrypt
from ..utils.io_utils import read_json, write_json_atomic
from .identity import RelayKeyPair
from .platform_client import RegisteredNode


@dataclass(frozen=True, slots=True)
class RelayNodeState:
    """All local state needed to resume or operate one Relay binding."""

    platform_url: str
    qwenpaw_id: str
    name: str
    private_key: str
    registered_node: RegisteredNode | None = None

    @property
    def key_pair(self) -> RelayKeyPair:
        """Restore the Node signing key without exposing it over an API."""
        raw = base64.urlsafe_b64decode(decrypt(self.private_key))
        return RelayKeyPair.from_private_bytes(raw)


class RelayNodeStore:
    """Atomically store one encrypted Relay node identity."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RelayNodeState | None:
        """Read the current state, returning None when it does not exist."""
        if not self.path.exists():
            return None
        payload = read_json(self.path)
        if not isinstance(payload, Mapping):
            raise ValueError("Relay node state must be a JSON object")
        registered = payload.get("registered_node")
        return RelayNodeState(
            platform_url=_string(payload, "platform_url"),
            qwenpaw_id=_string(payload, "qwenpaw_id"),
            name=_string(payload, "name"),
            private_key=_string(payload, "private_key"),
            registered_node=(
                RegisteredNode(
                    node_id=_string(registered, "node_id"),
                    credential=decrypt(_string(registered, "credential")),
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
        if state.registered_node is not None:
            registered = asdict(state.registered_node)
            registered["credential"] = encrypt(
                state.registered_node.credential,
            )
        write_json_atomic(
            self.path,
            {
                "version": 1,
                "platform_url": state.platform_url,
                "qwenpaw_id": state.qwenpaw_id,
                "name": state.name,
                "private_key": state.private_key,
                "registered_node": registered,
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
        encoded = base64.urlsafe_b64encode(
            key_pair.private_bytes(),
        ).decode("ascii")
        return RelayNodeState(
            platform_url=platform_url,
            qwenpaw_id=qwenpaw_id,
            name=name,
            private_key=encrypt(encoded),
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
