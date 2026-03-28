# -*- coding: utf-8 -*-
"""Preference file sanitization — redacts sensitive fields before export."""
from __future__ import annotations

REDACTED = "***REDACTED***"

SENSITIVE_FIELDS: set[str] = {
    "bot_token",
    "client_secret",
    "api_key",
    "auth_token",
    "access_token",
    "app_secret",
    "encrypt_key",
    "sk",
    "ak",
    "password",
    "tls_keyfile",
    "tls_certfile",
}


def sanitize_preferences(config_data: dict) -> dict:
    """Recursively redact sensitive fields in a configuration dictionary.

    Rules:
    - Keys in *SENSITIVE_FIELDS* whose values are
      **non-empty strings** are replaced with
      ``"***REDACTED***"``.
    - Non-string values and empty-string values are left untouched even when
      the key is sensitive.
    - Nested dicts are recursively sanitized.
    - Lists are traversed; dict elements inside lists
      are recursively sanitized.
    """
    sanitized: dict = {}
    for key, value in config_data.items():
        if key in SENSITIVE_FIELDS and isinstance(value, str) and value:
            sanitized[key] = REDACTED
        elif isinstance(value, dict):
            sanitized[key] = sanitize_preferences(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_preferences(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized
