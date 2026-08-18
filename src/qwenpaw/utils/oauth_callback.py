# -*- coding: utf-8 -*-
"""Resolve OAuth callbacks across standalone and managed runtimes."""

from __future__ import annotations

import os

from fastapi import Request

PRO_OAUTH_CALLBACK_URL_HEADER = "X-QwenPaw-Pro-OAuth-Callback-Url"


def managed_oauth_callback_url(request: Request) -> str | None:
    """Return the callback URL injected by a trusted Pro control plane."""
    if not os.environ.get("QWENPAW_PRO_INTERNAL_TOKEN", ""):
        return None
    value = request.headers.get(PRO_OAUTH_CALLBACK_URL_HEADER, "").strip()
    return value or None
