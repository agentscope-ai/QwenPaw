# -*- coding: utf-8 -*-
"""Shared ACP metadata keys.

This module is intentionally lightweight so CLI code can import constants
without importing the ACP server implementation.
"""

ACP_PROJECT_DIR_META_KEY = "qwenpaw.project_dir"
ACP_EPHEMERAL_META_KEY = "qwenpaw.ephemeral"
ACP_APPROVAL_EXPIRES_AT_META_KEY = "qwenpaw.approval_expires_at"

__all__ = [
    "ACP_APPROVAL_EXPIRES_AT_META_KEY",
    "ACP_EPHEMERAL_META_KEY",
    "ACP_PROJECT_DIR_META_KEY",
]
