# -*- coding: utf-8 -*-
"""Tests for Relay proof-of-possession primitives."""
from __future__ import annotations

import pytest

from qwenpaw.remote_access.identity import (
    RelayKeyPair,
    RelayProofError,
    verify_proof,
)


def test_proof_binds_token_method_target_nonce_and_key() -> None:
    key_pair = RelayKeyPair.generate()
    proof = key_pair.create_proof(
        "GET",
        "wss://relay.example.test/relay/v1/node?ignored=true",
        "ticket-value",
        "nonce-1",
        issued_at=100,
        proof_id="proof-1",
    )

    thumbprint = verify_proof(
        proof,
        "GET",
        "wss://relay.example.test/relay/v1/node",
        "ticket-value",
        "nonce-1",
        expected_thumbprint=key_pair.thumbprint(),
        now=100,
    )

    assert thumbprint == key_pair.thumbprint()


@pytest.mark.parametrize(
    ("method", "target", "token", "nonce"),
    [
        ("POST", "wss://relay.example.test/relay/v1/node", "ticket", "n"),
        ("GET", "wss://relay.example.test/relay/v1/mobile", "ticket", "n"),
        ("GET", "wss://relay.example.test/relay/v1/node", "other", "n"),
        ("GET", "wss://relay.example.test/relay/v1/node", "ticket", "other"),
    ],
)
def test_proof_rejects_context_changes(
    method: str,
    target: str,
    token: str,
    nonce: str,
) -> None:
    key_pair = RelayKeyPair.generate()
    proof = key_pair.create_proof(
        "GET",
        "wss://relay.example.test/relay/v1/node",
        "ticket",
        "n",
        issued_at=100,
    )

    with pytest.raises(RelayProofError):
        verify_proof(
            proof,
            method,
            target,
            token,
            nonce,
            now=100,
        )


def test_proof_rejects_a_different_bound_key() -> None:
    signer = RelayKeyPair.generate()
    credential_owner = RelayKeyPair.generate()
    proof = signer.create_proof(
        "GET",
        "wss://relay.example.test/relay/v1/node",
        "ticket",
        "nonce",
        issued_at=100,
    )

    with pytest.raises(RelayProofError, match="does not match"):
        verify_proof(
            proof,
            "GET",
            "wss://relay.example.test/relay/v1/node",
            "ticket",
            "nonce",
            expected_thumbprint=credential_owner.thumbprint(),
            now=100,
        )


def test_proof_rejects_an_expired_signature() -> None:
    key_pair = RelayKeyPair.generate()
    proof = key_pair.create_proof(
        "GET",
        "wss://relay.example.test/relay/v1/node",
        "ticket",
        "nonce",
        issued_at=100,
    )

    with pytest.raises(RelayProofError, match="time window"):
        verify_proof(
            proof,
            "GET",
            "wss://relay.example.test/relay/v1/node",
            "ticket",
            "nonce",
            now=131,
        )
