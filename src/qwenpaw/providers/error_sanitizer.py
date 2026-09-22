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

import re
from html.parser import HTMLParser

# Upper bound for a provider error message that is persisted with the
# provider config and shown in the Console.
MAX_CONNECTION_MESSAGE_LENGTH = 500

# Upper bound on the text that provider error handling will scan or
# normalize. The body is a remote response, so every pass over it has
# to be bounded or a large one blocks the event loop. The limit is far
# larger than any real provider error message (a full Cloudflare
# interstitial is 5-15 KB) and is shared with the status and keyword
# scans, so a classification marker is not cut off before it is read.
CONNECTION_MESSAGE_SCAN_LIMIT = 65_536

# Bound the text handed to the HTML summarizer. The body comes from a
# remote response and may be arbitrarily large, while only its opening
# is needed to build a short summary.
_HTML_SUMMARY_INPUT_LIMIT = 8_192

# Fragments emitted only by full HTML error pages. A gateway that
# rejects a request often answers with an interstitial instead of JSON.
_HTML_PAGE_MARKERS = (
    "<!doctype html",
    "<html",
    "</body>",
)

# Elements whose contents are not readable text.
_HTML_SKIPPED_BLOCK_TAGS = ("script", "style")

# Fragments emitted only by Cloudflare-style bot challenges. These are
# looked for in the raw provider text, and the canonical message below
# is deliberately a match too: the built-in provider probe path only
# has the already-cleaned text, so the marker has to survive cleanup
# for that path to still recognize a challenge.
_CHALLENGE_PAGE_MARKERS = (
    "cf-mitigated",
    "__cf_chl_tk",
    "_cf_chl_opt",
    "<title>just a moment",
    "blocked by cloudflare bot protection",
)
CHALLENGE_PAGE_MESSAGE = (
    "Blocked by Cloudflare bot protection: the endpoint returned a "
    "challenge page instead of an API response. The endpoint is "
    "reachable but rejects this client."
)

# A caller may prepend the HTTP status before the text reaches us
# (``Provider.connection_error_message`` does). Keep it when a body is
# replaced wholesale, otherwise cleanup silently drops the status.
_STATUS_PREFIX_RE = re.compile(
    r"^status(?:\s*code)?\s*[=:]\s*\d{3}\s*[:\-]?\s*",
    flags=re.IGNORECASE,
)


def is_challenge_page(message: str) -> bool:
    """Report whether error text is a Cloudflare-style bot challenge."""
    lowered = message[:CONNECTION_MESSAGE_SCAN_LIMIT].lower()
    return any(marker in lowered for marker in _CHALLENGE_PAGE_MARKERS)


def _is_html_page(message: str) -> bool:
    """Report whether error text is a full HTML page, not an API error."""
    lowered = message[:CONNECTION_MESSAGE_SCAN_LIMIT].lower()
    return any(marker in lowered for marker in _HTML_PAGE_MARKERS)


class _TextCollector(HTMLParser):
    """Collect readable text, dropping script and style contents.

    The standard parser is used rather than hand-rolled tag scanning:
    it already handles quoted ">" inside attributes, entity references
    and CDATA content, all of which a naive scan mis-reads.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._muted = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _HTML_SKIPPED_BLOCK_TAGS:
            self._muted += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_SKIPPED_BLOCK_TAGS and self._muted:
            self._muted -= 1

    def handle_data(self, data: str) -> None:
        if not self._muted:
            self.parts.append(data)


def _summarize_html_page(message: str) -> str:
    """Collapse an HTML error page into a single readable line.

    Reads a bounded prefix, so the work stays proportional to the limit
    rather than to a remote-controlled body.
    """
    collector = _TextCollector()
    try:
        collector.feed(message[:_HTML_SUMMARY_INPUT_LIMIT])
        collector.close()
    except Exception:  # pylint: disable=broad-exception-caught
        # Malformed markup must not turn into a reporting failure; the
        # text collected so far is still better than nothing.
        pass
    return " ".join(" ".join(collector.parts).split())


def sanitize_connection_message(message: str) -> str:
    """Clean provider error text for persistence and display.

    Credential-looking values are redacted, a bot-challenge page is
    replaced by a readable line that names the cause instead of blaming
    the credentials, and any other HTML error page is collapsed into a
    short summary.

    The result is deliberately *not* length-capped to the storage
    limit: callers feed it back into error classification, which
    matches keywords and status codes anywhere in the text. Truncating
    here would turn a non-retryable "model not found" into a retryable
    transient error. Cap only what is persisted or shown, with
    ``truncate_connection_message``.

    The scanning bound is a different concern and does apply: the text
    is remote-controlled, so it is truncated to
    ``CONNECTION_MESSAGE_SCAN_LIMIT`` before any pass over it.
    """
    if not message:
        return message
    message = message[:CONNECTION_MESSAGE_SCAN_LIMIT]
    prefix = _STATUS_PREFIX_RE.match(message)
    status = prefix.group(0) if prefix else ""
    if is_challenge_page(message):
        return f"{status}{CHALLENGE_PAGE_MESSAGE}"
    if _is_html_page(message):
        # The status is read from the text and is worth keeping in front
        # of the summary; only the page itself is replaced. The prefix is
        # cut first so it is not summarized as page text.
        body = message[prefix.end() :] if prefix else message
        message = f"{status}[non-JSON response] {_summarize_html_page(body)}"
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
