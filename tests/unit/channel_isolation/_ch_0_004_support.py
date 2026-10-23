# -*- coding: utf-8 -*-
"""Shared identities for current Channel DTO and endpoint registry tests."""

from __future__ import annotations

from qwenpaw.channel_protocol import EndpointParams, HelloParams


def _identity(generation: int = 7) -> dict[str, object]:
    """Return a valid control identity fixture."""
    return {
        "channel_key": "voice",
        "instance_id": "instance-1",
        "generation": generation,
    }


def _hello() -> HelloParams:
    """Return a valid handshake fixture."""
    return HelloParams.from_mapping(
        {
            "protocol_version": 1,
            **_hello_expectation(),
            "channel_key": "voice",
            "instance_id": "instance-1",
            "environment_spec_id": "ches1_" + "1" * 64,
            "environment_id": "ches1_" + "1" * 64 + ".install1_" + "2" * 32,
            "capabilities": [
                "approval_card",
                "host_state",
                "ingress_endpoint",
                "media",
                "reaction",
                "response_lifecycle",
                "streaming",
            ],
        },
    )


def _hello_expectation() -> dict[str, str]:
    """Return the Core-owned expected Runner identity fields."""
    return {
        "qwenpaw_version": "0.1",
        "source_revision": "4" * 64,
        "lock_sha256": "0" * 64,
        "python_abi": "cp313-cp313",
        "platform_tag": "macosx_11_0_arm64",
    }


def _endpoint() -> EndpointParams:
    """Return one loopback Runner-owned endpoint fixture."""
    return EndpointParams.from_mapping(
        {
            **_identity(),
            "protocol": "http",
            "host": "127.0.0.1",
            "port": 8080,
            "path": "/voice",
            "public_base_url": None,
            "readiness": "ready",
            "bound_externally": False,
            "auth_required": False,
            "quiescing": False,
        },
    )
