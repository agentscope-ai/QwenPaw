# -*- coding: utf-8 -*-
"""Constants for built-in tool guard rule integrity."""
from __future__ import annotations

MANIFEST_NAME = "rules_manifest.json"
SIGNATURE_NAME = "rules_manifest.sig"
SIGNATURE_SCHEME = "ed25519-v1"
HASH_SCHEME = "sha256"
DANGEROUS_SHELL_RULES_NAME = "dangerous_shell_commands.yaml"
RECOVERY_COMMIT = "058c52847faeb98fc0dea6ef56ac6d4a80f5e907"
RECOVERY_SOURCE_URL = (
    "https://raw.githubusercontent.com/axjlpl2026-commits/QwenPaw/"
    f"{RECOVERY_COMMIT}/src/qwenpaw/security/tool_guard/rules/"
    f"{DANGEROUS_SHELL_RULES_NAME}"
)
RECOVERY_API_URL = (
    "https://api.github.com/repos/axjlpl2026-commits/QwenPaw/contents/"
    f"src/qwenpaw/security/tool_guard/rules/{DANGEROUS_SHELL_RULES_NAME}"
    f"?ref={RECOVERY_COMMIT}"
)
RECOVERY_USER_AGENT = "QwenPaw-rule-integrity-repair/1.0"
RECOVERY_ATTEMPTS_PER_SOURCE = 2
MAX_RECOVERY_FILE_BYTES = 1024 * 1024
MAX_CONSECUTIVE_TIMEOUT_RETRIES = 5
REPAIR_TIMEOUT_RETRY_DELAY_SECONDS = 1.0

# Public key for the official built-in tool-rule manifest signature.
_PUBLIC_KEY_HEX = (
    "db31cea4a9fc8fd92d1e34a095d33699848f52bc5695f0768d697963e3966a7e"
)
