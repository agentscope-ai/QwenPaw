# -*- coding: utf-8 -*-
"""Unit tests for the reranker history service fingerprint."""

import json
import secrets
from pathlib import Path

import pytest

from qwenpaw.agents.memory import reranker_history as module
from qwenpaw.agents.memory.reranker_history import service_fingerprint
from qwenpaw.config.config import RerankerConfig

# Generated per run: the fingerprint tests only need a value that must never
# appear in the digest or on disk, so nothing credential-like is committed.
_TEST_API_KEY = f"probe-{secrets.token_hex(12)}"


def _config(**overrides) -> RerankerConfig:
    values = {
        "enabled": True,
        "api_key": _TEST_API_KEY,
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
    assert _TEST_API_KEY not in fingerprint
    assert "api.example.com" not in fingerprint


def test_fingerprint_normalizes_trailing_slash() -> None:
    assert service_fingerprint(_config()) == service_fingerprint(
        _config(base_url="https://api.example.com/v1"),
    )


def test_fingerprint_changes_when_service_fields_change() -> None:
    baseline = service_fingerprint(_config())

    assert service_fingerprint(_config(api_key="other")) != baseline
    assert service_fingerprint(_config(model_name="other")) != baseline
    assert service_fingerprint(_config(timeout=5.0)) != baseline


def test_fingerprint_preserves_fractional_timeout() -> None:
    """A fractional timeout must not be truncated, so history stays reachable
    after a refresh and different timeouts stay different services."""
    assert service_fingerprint(_config(timeout=1.5)) != service_fingerprint(
        _config(timeout=1),
    )
    assert service_fingerprint(_config(timeout=1.5)) != service_fingerprint(
        _config(timeout=2),
    )
    assert service_fingerprint(_config(timeout=1.50)) == service_fingerprint(
        _config(timeout=1.5),
    )


# Cross-language contract pin: console rerankerUtils.test.ts asserts the same
# digest for the canonical config ["https://fixture.example/v1", "",
# "fixture-model", "10"], so a normalization drift on either side fails CI.
GOLDEN_DIGEST = (
    "sha256:141b3dd720b233ef5706bf153260cca3ba2c82084715fd868518b9882c05a7cf"
)


def test_fingerprint_matches_console_golden_digest() -> None:
    assert (
        service_fingerprint(
            RerankerConfig(
                enabled=True,
                base_url="https://fixture.example/v1",
                api_key="",
                model_name="fixture-model",
                timeout=10.0,
            ),
        )
        == GOLDEN_DIGEST
    )


def test_fingerprint_ignores_form_only_fields() -> None:
    baseline = service_fingerprint(_config())

    assert service_fingerprint(_config(candidate_multiplier=5)) == baseline


def test_canonical_timeout_contract() -> None:
    assert module._canonical_timeout(10) == "10"
    assert module._canonical_timeout(10.0) == "10"
    assert module._canonical_timeout(1.5) == "1.5"
    assert module._canonical_timeout("1.5") == "1.5"
    assert module._canonical_timeout(None) == "0"
    assert module._canonical_timeout(float("nan")) == "0"


def _point_history_at(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "reranker_history.json"
    monkeypatch.setattr(module, "_history_path", lambda: path)
    return path


def test_load_drops_legacy_plaintext_keys(tmp_path, monkeypatch) -> None:
    """Legacy keys embedded the API key; reading must purge them so the
    credential does not survive on disk."""
    path = _point_history_at(tmp_path, monkeypatch)
    legacy_key = json.dumps(
        ["https://api.example.com/v1", _TEST_API_KEY, "m", 10],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    current_key = service_fingerprint(_config())
    path.write_text(
        json.dumps(
            {
                legacy_key: [{"ts": 1, "latency_ms": 1, "precision": 1.0}],
                current_key: [{"ts": 2, "latency_ms": 2, "precision": 0.5}],
            },
        ),
        encoding="utf-8",
    )

    history = module.get_history(current_key)

    assert [record["ts"] for record in history] == [2]
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert list(persisted) == [current_key]
    assert _TEST_API_KEY not in path.read_text(encoding="utf-8")


def test_load_drops_malformed_series(tmp_path, monkeypatch) -> None:
    path = _point_history_at(tmp_path, monkeypatch)
    current_key = service_fingerprint(_config())
    path.write_text(
        json.dumps(
            {
                current_key: "not-a-list",
                "sha256:" + "b" * 64: [{"ts": 1}],
            },
        ),
        encoding="utf-8",
    )

    assert module.get_history(current_key) == []
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert list(persisted) == ["sha256:" + "b" * 64]


def test_append_and_history_roundtrip(tmp_path, monkeypatch) -> None:
    _point_history_at(tmp_path, monkeypatch)
    fingerprint = service_fingerprint(_config())

    module.append_record(
        fingerprint,
        module.make_record(
            latency_ms=12,
            precision=1.0,
            correct_count=5,
            total=5,
        ),
    )

    history = module.get_history(fingerprint)
    assert len(history) == 1
    assert history[0]["precision"] == 1.0
    assert history[0]["correct_count"] == 5
    assert history[0]["total"] == 5
    assert history[0]["ts"] > 0


def test_history_is_capped(tmp_path, monkeypatch) -> None:
    _point_history_at(tmp_path, monkeypatch)
    fingerprint = service_fingerprint(_config())

    for _ in range(module._MAX_ENTRIES + 5):
        module.append_record(fingerprint, {"ts": 1})

    assert (
        len(module.get_history(fingerprint, limit=10_000))
        == module._MAX_ENTRIES
    )


@pytest.mark.parametrize(
    "key",
    ["not-a-digest", "sha256:short", "sha256:" + "z" * 64],
)
def test_is_current_key_rejects_other_shapes(key) -> None:
    assert module._is_current_key(key) is False
