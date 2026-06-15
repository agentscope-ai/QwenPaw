# -*- coding: utf-8 -*-
"""Tests for secure pool import orchestration."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EXTENSION_DIR = Path(__file__).resolve().parents[2]
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from skill_sign.constants import EXAMPLES_DIR  # noqa: E402
from skill_sign.errors import SkillSignatureRejectedError  # noqa: E402
from skill_sign.pool_import import secure_import_pool_zip  # noqa: E402


@pytest.fixture(scope="module")
def valid_fixture_paths() -> tuple[Path, Path]:
    zip_path = EXAMPLES_DIR / "valid" / "demo-skill.zip"
    sig_path = EXAMPLES_DIR / "valid" / "demo-skill.zip.sig"
    if not zip_path.is_file() or not sig_path.is_file():
        pytest.skip("Example fixtures missing; run sign_skill.py build-examples")
    return zip_path, sig_path


def test_secure_import_rejects_tampered_package(
    valid_fixture_paths: tuple[Path, Path],
) -> None:
    zip_path, sig_path = valid_fixture_paths
    invalid_zip = EXAMPLES_DIR / "invalid" / "tampered-skill.zip"
    if not invalid_zip.is_file():
        pytest.skip("Tampered fixture missing")

    with pytest.raises(SkillSignatureRejectedError):
        secure_import_pool_zip(
            zip_data=invalid_zip.read_bytes(),
            signature_data=sig_path.read_bytes(),
        )


def test_secure_import_requires_signature(valid_fixture_paths: tuple[Path, Path]) -> None:
    zip_path, _ = valid_fixture_paths
    with pytest.raises(ValueError, match="signature_required"):
        secure_import_pool_zip(
            zip_data=zip_path.read_bytes(),
            signature_data=b"   ",
        )
