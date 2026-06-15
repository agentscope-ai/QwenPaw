# -*- coding: utf-8 -*-
"""Constants for skill package Ed25519 signature verification."""
from __future__ import annotations

from pathlib import Path

SIGNATURE_SCHEME = "ed25519-detached-v1"
DEFAULT_PUBLIC_KEY_NAME = "qwenpaw-skill-signing-public.pem"
DEFAULT_PRIVATE_KEY_NAME = "qwenpaw-skill-signing-private.pem"

_MODULE_DIR = Path(__file__).resolve().parent
TRUST_DIR = _MODULE_DIR / "trust"
SIGN_TOOL_DIR = _MODULE_DIR / "sign_tool"
KEYS_DIR = SIGN_TOOL_DIR / "keys"
EXAMPLES_DIR = SIGN_TOOL_DIR / "examples"

DEFAULT_PUBLIC_KEY_PATH = TRUST_DIR / DEFAULT_PUBLIC_KEY_NAME
DEFAULT_PRIVATE_KEY_PATH = KEYS_DIR / DEFAULT_PRIVATE_KEY_NAME
