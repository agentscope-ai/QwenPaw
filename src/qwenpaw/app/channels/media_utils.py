# -*- coding: utf-8 -*-
"""Shared media URL utilities for channels.

Channels call :func:`resolve_media_url` to turn a local media path into
whatever string the formatter / agent should see. Today that's just the
local path — the signed-URL branch is a placeholder for a future media
server (tracked downstream; not wired into upstream QwenPaw yet).

Keeping this as a single-purpose indirection so a future PR can add the
signed-URL logic in one place without touching every channel's media
handling code.
"""

import logging
import os

logger = logging.getLogger(__name__)


async def resolve_media_url(local_path: str) -> str:
    """Return the media URL the agent should see for ``local_path``.

    Current behaviour: returns the local path verbatim. The channel's
    formatter downstream decides whether to base64-encode, hand out the
    file handle, or upload to a vision endpoint.

    Future behaviour (not wired): if a media server + public tunnel are
    configured, return a signed HTTPS URL that external vision models can
    reach. When that lands, add the check here and short-circuit with the
    signed URL.
    """
    # Sanity check: if the caller passed a non-existent path, log once so
    # it's visible in troubleshooting but still return the path (the caller
    # may intend to upload it somewhere else, e.g. tests).
    if local_path and not os.path.exists(local_path):
        logger.debug("resolve_media_url: path does not exist: %s", local_path)
    return str(local_path)
