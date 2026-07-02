# -*- coding: utf-8 -*-
"""Secret redaction helpers."""

from qwenpaw.security.redaction import redact_secrets, redact_text


def test_redact_text_masks_known_secret_patterns():
    text = (
        "openai=sk-abcdefghijklmnopqrstuvwxyz "
        "github=ghp_abcdefghijklmnopqrstuvwxyz123456"
    )

    redacted = redact_text(text)

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "sk-a****wxyz" in redacted
    assert "ghp_****3456" in redacted


def test_redact_secrets_recurses_json_like_values():
    value = {
        "nested": [
            {
                "token": (
                    "github_pat_"
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
                ),
            },
        ],
    }

    redacted = redact_secrets(value)

    assert "github_pat_abcdefghijklmnopqrstuvwxyz" not in str(redacted)
    assert "gith****3456" in redacted["nested"][0]["token"]
