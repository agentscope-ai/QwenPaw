# -*- coding: utf-8 -*-
"""Unit tests for the reranker history service fingerprint."""

from qwenpaw.agents.memory.reranker_history import service_fingerprint
from qwenpaw.config.config import RerankerConfig


def _config(**overrides) -> RerankerConfig:
    values = {
        "enabled": True,
        "api_key": "secret-key",
        "base_url": "https://api.example.com/v1/",
        "model_name": "test-reranker",
        "timeout": 10.0,
    }
    values.update(overrides)
    return RerankerConfig(**values)


def test_fingerprint_is_an_opaque_digest() -> None:
    fingerprint = service_fingerprint(_config())

    assert fingerprint.startswith("sha256:")
    assert len(fingerprint) == len("sha256:") + 64
    # The credential and host must not be recoverable from the key.
    assert "secret-key" not in fingerprint
    assert "api.example.com" not in fingerprint


def test_fingerprint_normalizes_trailing_slash() -> None:
    assert service_fingerprint(_config()) == service_fingerprint(
        _config(base_url="https://api.example.com/v1")
    )


def test_fingerprint_changes_when_service_fields_change() -> None:
    baseline = service_fingerprint(_config())

    assert service_fingerprint(_config(api_key="other")) != baseline
    assert service_fingerprint(_config(model_name="other")) != baseline
    assert service_fingerprint(_config(timeout=5.0)) != baseline


def test_fingerprint_preserves_fractional_timeout() -> None:
    """A fractional timeout must produce the same digest whatever type each
    side uses, so history stays reachable after a refresh."""
    assert service_fingerprint(_config(timeout=1.5)) == service_fingerprint(
        _config(timeout=1.5)
    )
    assert service_fingerprint(_config(timeout=1.5)) != service_fingerprint(
        _config(timeout=1)
    )
    assert service_fingerprint(_config(timeout=1.5)) != service_fingerprint(
        _config(timeout=2)
    )
