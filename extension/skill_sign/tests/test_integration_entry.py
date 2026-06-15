# -*- coding: utf-8 -*-
"""Integration acceptance for skill secure import verification (ip-e2e-003 helper)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EXTENSION_DIR = Path(__file__).resolve().parents[2]
if str(_EXTENSION_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTENSION_DIR))

from skill_sign.constants import EXAMPLES_DIR  # noqa: E402
from skill_sign.host_bridge import verify_skill_package  # noqa: E402


@pytest.mark.integration
@pytest.mark.p0
def test_skill_secure_import_verification_entry() -> None:
    """Control: verify committed valid/invalid fixtures through host_bridge.

    Observation: valid example passes; tampered example fails closed.
    """
    valid_zip = EXAMPLES_DIR / "valid" / "demo-skill.zip"
    valid_sig = EXAMPLES_DIR / "valid" / "demo-skill.zip.sig"
    invalid_zip = EXAMPLES_DIR / "invalid" / "tampered-skill.zip"
    invalid_sig = EXAMPLES_DIR / "invalid" / "tampered-skill.zip.sig"

    for path in (valid_zip, valid_sig, invalid_zip, invalid_sig):
        assert path.is_file(), f"Missing fixture: {path}"

    valid = verify_skill_package(valid_zip.read_bytes(), valid_sig.read_bytes())
    assert valid["valid"] is True
    assert valid.get("signer") == "qwenpaw-skill-sign"

    invalid = verify_skill_package(invalid_zip.read_bytes(), invalid_sig.read_bytes())
    assert invalid["valid"] is False
    assert invalid.get("error")
