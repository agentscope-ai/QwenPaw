# -*- coding: utf-8 -*-
"""Encrypt / decrypt data-source config secrets (same as provider api_key)."""
from __future__ import annotations

from typing import Dict

from qwenpaw.security.secret_store import (
    decrypt_dict_fields,
    encrypt_dict_fields,
    is_encrypted,
)

from .masking import SENSITIVE_CONFIG_KEYS

DATA_SOURCE_SECRET_FIELDS = SENSITIVE_CONFIG_KEYS


def config_has_plaintext_secrets(config: Dict[str, object]) -> bool:
    """Return True when *config* contains unencrypted secret values."""
    for field in DATA_SOURCE_SECRET_FIELDS:
        value = config.get(field)
        if isinstance(value, str) and value and not is_encrypted(value):
            return True
    return False


def _stringified_config(config: Dict[str, object]) -> Dict[str, str]:
    return {
        key: str(value)
        for key, value in config.items()
        if isinstance(value, str)
    }


def encrypt_config(config: Dict[str, object]) -> Dict[str, object]:
    """Return a copy of *config* with secret fields encrypted for disk."""
    encrypted = encrypt_dict_fields(
        _stringified_config(config),
        DATA_SOURCE_SECRET_FIELDS,
    )
    result = dict(config)
    for key in DATA_SOURCE_SECRET_FIELDS:
        if key in encrypted:
            result[key] = encrypted[key]
    return result


def decrypt_config(config: Dict[str, object]) -> Dict[str, object]:
    """Return a copy of *config* with secret fields decrypted in memory."""
    decrypted = decrypt_dict_fields(
        _stringified_config(config),
        DATA_SOURCE_SECRET_FIELDS,
    )
    result = dict[str, object](config)
    for key in DATA_SOURCE_SECRET_FIELDS:
        if key in decrypted:
            result[key] = decrypted[key]
    return result
