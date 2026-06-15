# -*- coding: utf-8 -*-
"""Unit tests for skill package signature verification."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EXTENSION_DIR = Path(__file__).resolve().parents[2]
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from skill_sign.constants import DEFAULT_PUBLIC_KEY_PATH, EXAMPLES_DIR  # noqa: E402
from skill_sign.verifier import (  # noqa: E402
    decode_detached_signature,
    verify_skill_package_signature,
)


@pytest.fixture(scope="module")
def valid_fixture_paths() -> tuple[Path, Path]:
    zip_path = EXAMPLES_DIR / "valid" / "demo-skill.zip"
    sig_path = EXAMPLES_DIR / "valid" / "demo-skill.zip.sig"
    if not zip_path.is_file() or not sig_path.is_file():
        pytest.skip("Example fixtures missing; run sign_skill.py build-examples")
    return zip_path, sig_path


@pytest.fixture(scope="module")
def invalid_fixture_paths() -> tuple[Path, Path]:
    zip_path = EXAMPLES_DIR / "invalid" / "tampered-skill.zip"
    sig_path = EXAMPLES_DIR / "invalid" / "tampered-skill.zip.sig"
    if not zip_path.is_file() or not sig_path.is_file():
        pytest.skip("Example fixtures missing; run sign_skill.py build-examples")
    return zip_path, sig_path


def test_public_key_is_present() -> None:
    assert DEFAULT_PUBLIC_KEY_PATH.is_file(), (
        f"Missing pinned public key: {DEFAULT_PUBLIC_KEY_PATH}"
    )


def test_decode_detached_signature_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        decode_detached_signature("")


def test_valid_example_verifies(valid_fixture_paths: tuple[Path, Path]) -> None:
    zip_path, sig_path = valid_fixture_paths
    result = verify_skill_package_signature(
        zip_path.read_bytes(),
        sig_path.read_bytes(),
    )
    assert result.valid is True
    assert result.signer == "qwenpaw-skill-sign"
    assert len(result.package_sha256) == 64


def test_tampered_example_fails(invalid_fixture_paths: tuple[Path, Path]) -> None:
    zip_path, sig_path = invalid_fixture_paths
    result = verify_skill_package_signature(
        zip_path.read_bytes(),
        sig_path.read_bytes(),
    )
    assert result.valid is False
    assert result.error


def test_modified_bytes_fail_after_sign(valid_fixture_paths: tuple[Path, Path]) -> None:
    zip_path, sig_path = valid_fixture_paths
    data = bytearray(zip_path.read_bytes())
    data[0] ^= 0xFF
    result = verify_skill_package_signature(bytes(data), sig_path.read_bytes())
    assert result.valid is False
