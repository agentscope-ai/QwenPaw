# -*- coding: utf-8 -*-
"""Errors for skill secure import."""
from __future__ import annotations

from typing import Any


class SkillSignatureRejectedError(Exception):
    """Raised when detached signature verification fails."""

    def __init__(self, verification: dict[str, Any]) -> None:
        self.verification = verification
        super().__init__("Signature verification failed")
