# -*- coding: utf-8 -*-
"""Tests for protected Relay node persistence."""
from __future__ import annotations

import json
import stat
from dataclasses import replace

from qwenpaw.remote_access import RegisteredNode, RelayNodeStore


def test_store_encrypts_node_key_and_credential(tmp_path, monkeypatch) -> None:
    from qwenpaw.security import secret_store

    monkeypatch.setattr(secret_store, "_cached_master_key", b"k" * 32)
    monkeypatch.setattr(secret_store, "_cached_fernet", None)
    path = tmp_path / "relay-node.json"
    store = RelayNodeStore(path)
    state = store.create(
        platform_url="https://platform.test",
        qwenpaw_id="paw-1",
        name="Office Paw",
    )
    state = replace(
        state,
        registered_node=RegisteredNode(
            node_id="node-1",
            credential="qprn_v1.node.secret",
            dpop_nonce="nonce",
            credential_generation=1,
        ),
    )

    store.save(state)
    raw = path.read_text(encoding="utf-8")
    loaded = store.load()

    assert "qprn_v1.node.secret" not in raw
    assert loaded is not None
    assert loaded.registered_node is not None
    assert loaded.registered_node.credential == "qprn_v1.node.secret"
    assert loaded.key_pair.thumbprint() == state.key_pair.thumbprint()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(raw)["private_key"].startswith("ENC:")
