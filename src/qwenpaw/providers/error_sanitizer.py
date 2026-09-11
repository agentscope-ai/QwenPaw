# -*- coding: utf-8 -*-
"""Turn raw provider error text into something safe to store and show.

Provider error bodies are remote-controlled and frequently not JSON: a
gateway may answer with an HTML interstitial or a bot challenge instead
of an API error. This module owns that protocol-specific handling so
provider classes carry only provider behaviour, and so support for
another non-JSON gateway (Akamai, WAF, ...) lands here rather than in
the shared ``Provider`` base class.
"""

from __future__ import annotations

import html
import re

# Upper bound for a provider error message that is persisted with the
# provider config and shown in the Console.
MAX_CONNECTION_MESSAGE_LENGTH = 500

# Fragments emitted only by full HTML error pages. A gateway that
# rejects a request often answers with an interstitial instead of JSON.
_HTML_PAGE_MARKERS = (
    "<!doctype html",
    "<html",
    "</body>",
)

# Upper bound on the text that provider error handling will scan or
# normalize. The body is a remote response, so every pass over it has
# to be bounded or a large one blocks the event loop. The limit is far
# larger than any real provider error message (a full Cloudflare
# interstitial is 5-15 KB), so it does not change classification in
# practice: the HTTP status is read off the exception anyway.
_CONNECTION_MESSAGE_SCAN_LIMIT = 65_536

# Bound the text handed to the HTML summarizer. The body comes from a
# remote response and may be arbitrarily large, while only its opening
# is needed to build a short summary.
_HTML_SUMMARY_INPUT_LIMIT = 8_192

# Elements whose contents are not readable text.
_HTML_SKIPPED_BLOCK_TAGS = ("script", "style")

# Closing tags for those elements. Matched case-insensitively, because
# HTML tag names are. Searching for the next generic tag instead would
# stop at a "<" inside the element, such as a comparison "a < b".
_HTML_SKIPPED_BLOCK_CLOSE = {
    name: re.compile(rf"</{name}", re.IGNORECASE)
    for name in _HTML_SKIPPED_BLOCK_TAGS
}

# Fragments emitted only by Cloudflare-style bot challenges. These are
# looked for in the raw provider text, before any cleanup rewrites it,
# so the canonical message below is deliberately not a match.
_CHALLENGE_PAGE_MARKERS = (
    "cf-mitigated",
    "__cf_chl_tk",
    "_cf_chl_opt",
    "<title>just a moment",
)
CHALLENGE_PAGE_MESSAGE = (
    "Blocked by Cloudflare bot protection: the endpoint returned a "
    "challenge page instead of an API response. The endpoint is "
    "reachable but rejects this client."
)


def is_challenge_page(message: str) -> bool:
    """Report whether error text is a Cloudflare-style bot challenge."""
    lowered = message[:_CONNECTION_MESSAGE_SCAN_LIMIT].lower()
    return any(marker in lowered for marker in _CHALLENGE_PAGE_MARKERS)


def _is_html_page(message: str) -> bool:
    """Report whether error text is a full HTML page, not an API error."""
    lowered = message[:_CONNECTION_MESSAGE_SCAN_LIMIT].lower()
    return any(marker in lowered for marker in _HTML_PAGE_MARKERS)


def _summarize_html_page(message: str) -> str:
    """Collapse an HTML error page into a single readable line.

    Scans a bounded prefix once, advancing monotonically, and skips a
    script or style element by jumping straight to its closing tag. A
    regex is not used for the tags themselves: the text is an untrusted
    remote body, and ``<[^>]*>`` degrades to quadratic on markup full
    of unterminated ``<`` (measured at about 17s for 100 KB), which
    would stall the event loop for every other task.
    """
    text = message[:_HTML_SUMMARY_INPUT_LIMIT]
    parts: list[str] = []
    position = 0
    while position < len(text):
        start = text.find("<", position)
        if start < 0:
            parts.append(text[position:])
            break
        parts.append(text[position:start])
        # Keep a separator where the tag was removed, so adjacent text
        # from sibling elements does not run together.
        parts.append(" ")
        end = text.find(">", start)
        if end < 0:
            # No further markup, so the remainder is plain text.
            parts.append(text[start:])
            break
        raw = text[start + 1 : end].strip()
        closing = raw.startswith("/")
        name = raw.lstrip("/").split(None, 1)
        tag = name[0].lower() if name else ""
        position = end + 1
        if closing or tag not in _HTML_SKIPPED_BLOCK_TAGS:
            continue
        # Skip the element contents by jumping to its closing tag. A
        # generic tag scan would instead stop at a "<" inside the
        # element and throw away everything that follows.
        close = _HTML_SKIPPED_BLOCK_CLOSE[tag].search(text, position)
        if close is None:
            # Unclosed element: the remainder is its content.
            break
        close_end = text.find(">", close.start())
        if close_end < 0:
            break
        position = close_end + 1
    return " ".join(html.unescape("".join(parts)).split())


def sanitize_connection_message(message: str) -> str:
    """Clean provider error text for persistence and display.

    Credential-looking values are redacted and HTML error pages (such
    as Cloudflare challenge interstitials) are collapsed into a
    readable summary.

    The result is deliberately *not* length-capped to the storage
    limit: callers feed it back into error classification, which
    matches keywords and status codes anywhere in the text. Truncating
    here would turn a non-retryable "model not found" into a retryable
    transient error. Cap only what is persisted or shown, with
    ``truncate_connection_message``.

    The scanning bound is a different concern and does apply: the text
    is remote-controlled, so it is truncated to
    ``_CONNECTION_MESSAGE_SCAN_LIMIT`` before any pass over it.
    """
    if not message:
        return message
    message = message[:_CONNECTION_MESSAGE_SCAN_LIMIT]
    if is_challenge_page(message):
        return CHALLENGE_PAGE_MESSAGE
    if _is_html_page(message):
        message = f"[non-JSON response] {_summarize_html_page(message)}"
    message = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", message)
    credential_patterns = (
        r"(?i)(api[_ -]?key|x-api-key|access[_ -]?token|token)"
        r"(\s*[=:]\s*)[^,;\s]+",
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^,;\s]+",
    )
    message = re.sub(
        credential_patterns[0],
        r"\1\2[redacted]",
        message,
    )
    message = re.sub(
        credential_patterns[1],
        r"\1[redacted]",
        message,
    )
    return message


def truncate_connection_message(message: str) -> str:
    """Cap error text that is persisted or rendered for the user.

    Apply this after ``sanitize_connection_message``, never before
    classification.
    """
    if len(message) <= MAX_CONNECTION_MESSAGE_LENGTH:
        return message
    return message[: MAX_CONNECTION_MESSAGE_LENGTH - 1].rstrip() + "\u2026"
