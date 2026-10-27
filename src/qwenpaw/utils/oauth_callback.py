# -*- coding: utf-8 -*-
"""Resolve OAuth callbacks across standalone and managed runtimes."""

from __future__ import annotations

import html
import os

from fastapi import Request

HUB_OAUTH_CALLBACK_URL_HEADER = "X-QwenPaw-Hub-OAuth-Callback-Url"


def managed_oauth_callback_url(request: Request) -> str | None:
    """Return the callback URL injected by a trusted Hub control plane."""
    if not os.environ.get("QWENPAW_RUNTIME_INTERNAL_TOKEN", ""):
        return None
    value = request.headers.get(HUB_OAUTH_CALLBACK_URL_HEADER, "").strip()
    return value or None


def oauth_success_html(provider_id: str) -> str:
    """HTML that notifies opener and closes the popup."""
    return f"""<!DOCTYPE html>
<html><head><title>Authorization Successful</title></head>
<body style="font-family:system-ui;text-align:center;padding:60px">
<h2>Connected!</h2>
<p>You can close this window.</p>
<script>
if (window.opener) {{
  window.opener.postMessage(
    {{type: "oauth_complete", provider: "{provider_id}"}},
    window.location.origin
  );
}}
setTimeout(function() {{ window.close(); }}, 1500);
</script>
</body></html>"""


def oauth_error_html(message: str) -> str:
    """HTML for error display in popup."""
    safe_msg = html.escape(message)
    return f"""<!DOCTYPE html>
<html><head><title>Authorization Failed</title></head>
<body style="font-family:system-ui;text-align:center;padding:60px">
<h2>Authorization Failed</h2>
<p>{safe_msg}</p>
<p><a href="javascript:window.close()">Close this window</a></p>
</body></html>"""
