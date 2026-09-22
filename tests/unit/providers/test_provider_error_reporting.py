# -*- coding: utf-8 -*-
"""Provider error reporting: challenge pages and bounded error text."""

from __future__ import annotations

import pytest

from qwenpaw.providers.error_sanitizer import (
    CHALLENGE_PAGE_MESSAGE,
    CONNECTION_MESSAGE_SCAN_LIMIT,
    MAX_CONNECTION_MESSAGE_LENGTH,
    is_challenge_page,
    sanitize_connection_message,
    truncate_connection_message,
)
from qwenpaw.providers.provider import Provider
from qwenpaw.providers.provider_discovery import classify_discovery_error
from qwenpaw.providers.provider_model_availability import classify_model_check

CHALLENGE_PAGE = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    "<body><div id='challenge-running'>Verifying you are human.</div>"
    "<script>window._cf_chl_opt={cvId:'3'};</script></body></html>"
)
CHALLENGE_MARKERS = (
    "cf-mitigated: challenge",
    "__cf_chl_tk=abc",
    "_cf_chl_opt={}",
    "<title>Just a moment...</title>",
    "Blocked by Cloudflare bot protection",
)
JSON_403 = "Error code: 403 - {'error': {'message': 'Invalid API key'}}"


class ApiStatusError(Exception):
    """Exception carrying what an OpenAI SDK status error holds."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        self.message = None
        super().__init__(f"Error code: {status_code} - '{body}'")


@pytest.mark.parametrize("marker", CHALLENGE_MARKERS)
def test_challenge_markers_are_detected(marker: str) -> None:
    assert is_challenge_page(f"prefix {marker} suffix") is True


@pytest.mark.parametrize("marker", CHALLENGE_MARKERS)
def test_challenge_markers_are_case_insensitive(marker: str) -> None:
    assert is_challenge_page(marker.upper()) is True


def test_plain_html_page_is_not_a_challenge() -> None:
    page = "<!DOCTYPE html><html><body>502 Bad Gateway</body></html>"

    assert is_challenge_page(page) is False


def test_marker_beyond_the_scan_bound_is_not_read() -> None:
    message = "x" * CONNECTION_MESSAGE_SCAN_LIMIT + "cf-mitigated"

    assert is_challenge_page(message) is False


def test_cleaned_challenge_is_still_recognized() -> None:
    cleaned = sanitize_connection_message(CHALLENGE_PAGE)

    assert cleaned == CHALLENGE_PAGE_MESSAGE
    assert is_challenge_page(cleaned) is True


def test_status_prefix_survives_body_replacement() -> None:
    cleaned = sanitize_connection_message(f"status=403: {CHALLENGE_PAGE}")

    assert cleaned == f"status=403: {CHALLENGE_PAGE_MESSAGE}"


def test_credentials_are_still_redacted() -> None:
    message = "authorization=Bearer secret-token api_key=secret-key"

    cleaned = sanitize_connection_message(message)

    assert "secret-token" not in cleaned
    assert "secret-key" not in cleaned
    assert "[redacted]" in cleaned


def test_control_characters_are_stripped() -> None:
    cleaned = sanitize_connection_message("status=500:\x07 bad\x00 gateway")

    assert cleaned == "status=500: bad gateway"


def test_provider_sanitizer_delegates_to_the_shared_module() -> None:
    assert Provider.sanitize_connection_message(CHALLENGE_PAGE) == (
        CHALLENGE_PAGE_MESSAGE
    )
    assert "[redacted]" in Provider.sanitize_connection_message("token=secret")


def test_truncate_keeps_short_text_untouched() -> None:
    message = "status=503: upstream unavailable"

    assert truncate_connection_message(message) == message


def test_truncate_caps_long_text_and_marks_it() -> None:
    message = "a" * (MAX_CONNECTION_MESSAGE_LENGTH + 100)

    capped = truncate_connection_message(message)

    assert len(capped) == MAX_CONNECTION_MESSAGE_LENGTH
    assert capped.endswith("\u2026")
    assert truncate_connection_message(capped) == capped


def test_discovery_reports_a_challenge_page_as_blocked() -> None:
    exc = ApiStatusError(403, CHALLENGE_PAGE)

    assert classify_discovery_error(exc, str(exc)) == "blocked"


def test_discovery_reports_a_challenge_before_mapping_the_status() -> None:
    message = f"status=403: {CHALLENGE_PAGE}"

    assert classify_discovery_error(Exception(message), message) == "blocked"


def test_discovery_keeps_a_plain_403_as_authorization() -> None:
    exc = ApiStatusError(403, JSON_403)

    assert classify_discovery_error(exc, str(exc)) == "authorization"


@pytest.mark.parametrize(
    ("exc", "message", "expected"),
    [
        (TimeoutError("timed out"), "timed out", "timeout"),
        (ConnectionError("refused"), "refused", "network"),
        (Exception("status=404: no such route"), "status=404", "unsupported"),
        (Exception("status=503: down"), "status=503", "provider_unavailable"),
    ],
)
def test_discovery_categories_are_unchanged(exc, message, expected) -> None:
    assert classify_discovery_error(exc, message) == expected


def test_availability_reports_a_challenge_page_as_blocked() -> None:
    result = classify_model_check(
        False,
        f"status=403: {CHALLENGE_PAGE}",
        http_status=403,
    )

    assert result.status == "blocked"
    assert result.retryable is False
    assert result.message == f"status=403: {CHALLENGE_PAGE_MESSAGE}"


def test_availability_prefers_the_challenge_over_a_provider_kind() -> None:
    result = classify_model_check(
        False,
        f"status=403: {CHALLENGE_PAGE}",
        http_status=403,
        error_kind="permission_denied",
    )

    assert result.status == "blocked"


def test_availability_caps_a_giant_challenge_body() -> None:
    body = CHALLENGE_PAGE * 50
    result = classify_model_check(
        False,
        f"status=403: {body}",
        http_status=403,
    )

    assert result.status == "blocked"
    assert len(result.message) <= MAX_CONNECTION_MESSAGE_LENGTH
    assert "<html" not in result.message


def test_availability_classifies_before_it_caps() -> None:
    message = "x" * 1_000 + " model not found"

    result = classify_model_check(False, message)

    assert result.status == "model_not_found"
    assert len(result.message) <= MAX_CONNECTION_MESSAGE_LENGTH


def test_availability_keeps_a_plain_403_as_permission_denied() -> None:
    result = classify_model_check(
        False,
        JSON_403,
        http_status=403,
        error_kind="permission_denied",
    )

    assert result.status == "permission_denied"
    assert result.retryable is False
