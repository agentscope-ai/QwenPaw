# -*- coding: utf-8 -*-
"""Tests for provider discovery error classification and cleanup.

Covers the Cloudflare-challenge failure mode reported for custom
OpenAI-compatible providers: an HTML interstitial answered a 403 that
used to be reported as "provider unavailable".
"""

from __future__ import annotations

import httpx
from openai import AsyncOpenAI
import pytest

from qwenpaw.providers.error_sanitizer import (
    CHALLENGE_PAGE_MESSAGE,
    MAX_CONNECTION_MESSAGE_LENGTH,
    _CONNECTION_MESSAGE_SCAN_LIMIT,
    _HTML_SUMMARY_INPUT_LIMIT,
    _summarize_html_page,
)
from qwenpaw.providers.error_utils import extract_status_code
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import Provider
from qwenpaw.providers.provider_discovery import classify_discovery_error
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.providers.provider_model_availability import classify_model_check

CF_CHALLENGE_BODY = (
    '<!DOCTYPE html><html lang="en-US"><head>'
    "<title>Just a moment...</title><script>"
    'window._cf_chl_opt={cZone:"api.wusrouter.com",'
    'cUPMDTk:"/v1/models?__cf_chl_tk=abcDEF123"};'
    "</script></head><body>"
    "<h2>Verifying you are human.</h2></body></html>"
)

PLAIN_HTML_BODY = (
    "<!DOCTYPE html><html><body>" + "<h1>502 Bad Gateway</h1></body></html>"
)


async def _sdk_models_error(
    status: int,
    body: str,
    content_type: str,
) -> Exception:
    """Reproduce the exception the OpenAI SDK raises for a response."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            text=body,
            headers={"content-type": content_type},
        )

    client = AsyncOpenAI(
        base_url="https://api.wusrouter.com/v1",
        api_key="sk-test",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ),
    )
    try:
        await client.models.list()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return exc
    finally:
        await client.close()
    raise AssertionError("expected the SDK to raise")


# --- classification ---------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # The OpenAI SDK renders a JSON error body as
        # "Error code: NNN - <body>".
        ('Error code: 401 - {"error": "x"}', "authentication"),
        ('Error code: 403 - {"error": "x"}', "authorization"),
        ('Error code: 404 - {"error": "x"}', "unsupported"),
        ('Error code: 405 - {"error": "x"}', "unsupported"),
        ('Error code: 500 - {"error": "x"}', "provider_unavailable"),
        ('Error code: 503 - {"error": "x"}', "provider_unavailable"),
        # connection_error_message() format, used by built-in providers.
        ("status=401: unauthorized", "authentication"),
        ("status=403: forbidden", "authorization"),
        ("status=404: not found", "unsupported"),
    ],
)
def test_classify_reads_sdk_and_status_formats(
    message: str,
    expected: str,
) -> None:
    """Both message formats in use must yield the same categories."""
    exc = RuntimeError(message)

    assert classify_discovery_error(exc, message) == expected


def test_classify_reads_error_code_status_ignoring_case() -> None:
    """Status extraction must not depend on the SDK's casing."""
    message = "ERROR CODE: 403 - forbidden"

    assert classify_discovery_error(RuntimeError(message), message) == (
        "authorization"
    )


def test_classify_returns_timeout_for_timeout_error() -> None:
    exc = TimeoutError("timed out")

    assert classify_discovery_error(exc, str(exc)) == "timeout"


def test_classify_returns_unsupported_for_unsupported_endpoint() -> None:
    message = "unsupported endpoint"

    assert classify_discovery_error(RuntimeError(message), message) == (
        "unsupported"
    )


def test_classify_returns_invalid_response_for_value_error() -> None:
    message = "Provider returned no models"

    assert classify_discovery_error(ValueError(message), message) == (
        "invalid_response"
    )


def test_classify_returns_network_for_connection_error() -> None:
    message = "connection reset"

    assert classify_discovery_error(ConnectionError(message), message) == (
        "network"
    )


def test_classify_returns_unavailable_for_opaque_message() -> None:
    message = "something went wrong"

    assert classify_discovery_error(RuntimeError(message), message) == (
        "provider_unavailable"
    )


# --- challenge detection ---------------------------------------------


def test_challenge_page_is_blocked_not_authorization() -> None:
    """A challenge must not be reported as a bad API key."""
    exc = RuntimeError(CF_CHALLENGE_BODY)

    assert classify_discovery_error(exc, CF_CHALLENGE_BODY) == "blocked"


def test_challenge_detection_reads_the_raw_message() -> None:
    """Cleanup must not be what keeps a challenge detectable.

    The canonical replacement text is deliberately not a challenge
    marker itself: if it were, cleanup would rewrite any message that
    merely contained it and drop the surrounding context, such as an
    HTTP status prefix.
    """
    cleaned = Provider.sanitize_connection_message(CF_CHALLENGE_BODY)

    assert cleaned == CHALLENGE_PAGE_MESSAGE
    assert (
        classify_discovery_error(
            RuntimeError(CF_CHALLENGE_BODY),
            CF_CHALLENGE_BODY,
        )
        == "blocked"
    )
    # The cleaned text alone is no longer a challenge, which is why
    # classification has to run on the raw body.
    assert classify_discovery_error(RuntimeError(cleaned), cleaned) == (
        "provider_unavailable"
    )


def test_cleanup_keeps_a_status_prefix_on_a_challenge() -> None:
    """Re-cleaning must not discard the status prefix.

    The canonical message used to be its own challenge marker, so
    cleaning ``status=403: <canonical>`` replaced the whole string and
    lost the status.
    """
    message = f"status=403: {CHALLENGE_PAGE_MESSAGE}"

    assert "status=403" in Provider.sanitize_connection_message(message)


def test_model_check_reads_the_status_before_cleanup() -> None:
    """A denied model check must not become retryable.

    Cleanup replaces a challenge body wholesale, so the status has to
    be read from the raw text first. Otherwise the result is
    ``transient_error`` with ``retryable=True`` and no status.
    """
    result = classify_model_check(False, f"status=403: {CF_CHALLENGE_BODY}")

    assert result.http_status == 403
    assert result.status == "permission_denied"
    assert result.retryable is False


async def test_challenge_on_a_model_check_is_not_retryable() -> None:
    """The reported downgrade, through the real SDK message format."""
    exc = await _sdk_models_error(403, CF_CHALLENGE_BODY, "text/html")
    detail = Provider.connection_error_message(exc)

    assert "status=403" in detail

    result = classify_model_check(False, detail)

    assert result.http_status == 403
    assert result.status == "permission_denied"
    assert result.retryable is False


def test_challenge_outranks_an_embedded_403() -> None:
    """Challenge detection runs before the status mapping."""
    message = f"Error code: 403 - {CF_CHALLENGE_BODY}"

    assert classify_discovery_error(RuntimeError(message), message) == (
        "blocked"
    )


def test_plain_html_page_is_not_a_challenge() -> None:
    assert (
        classify_discovery_error(
            RuntimeError(PLAIN_HTML_BODY),
            PLAIN_HTML_BODY,
        )
        == "provider_unavailable"
    )


# --- message cleanup --------------------------------------------------


def test_sanitize_replaces_challenge_page() -> None:
    result = Provider.sanitize_connection_message(CF_CHALLENGE_BODY)

    assert result == CHALLENGE_PAGE_MESSAGE
    assert "<script" not in result
    assert "__cf_chl_tk" not in result


def test_sanitize_collapses_plain_html_page() -> None:
    result = Provider.sanitize_connection_message(PLAIN_HTML_BODY)

    assert result.startswith("[non-JSON response]")
    assert "<" not in result
    assert "502 Bad Gateway" in result


def test_truncate_caps_long_message() -> None:
    result = Provider.truncate_connection_message("x" * 4_000)

    assert len(result) <= MAX_CONNECTION_MESSAGE_LENGTH
    assert result.endswith("\u2026")


def test_truncate_keeps_short_message() -> None:
    assert Provider.truncate_connection_message("boom") == "boom"


def test_sanitize_does_not_truncate() -> None:
    """Classification reads the whole message, so cleanup must not cut it.

    Truncating here used to hide "model not found" past the cut and
    downgrade a non-retryable state to a retryable one.
    """
    message = "x" * 4_000

    result = Provider.sanitize_connection_message(message)

    assert len(result) == 4_000


def test_sanitize_redacts_before_output() -> None:
    """A secret must be redacted even late in a long message."""
    message = "x" * 400 + " api_key=sk-secret-value " + "y" * 400

    result = Provider.sanitize_connection_message(message)

    assert "sk-secret-value" not in result
    assert "[redacted]" in result


def test_sanitize_keeps_redacting_api_key() -> None:
    result = Provider.sanitize_connection_message("api_key=sk-abc")

    assert "sk-abc" not in result
    assert "[redacted]" in result


def test_sanitize_keeps_redacting_bearer_token() -> None:
    result = Provider.sanitize_connection_message(
        "Authorization: Bearer sk-abc",
    )

    assert "sk-abc" not in result
    assert "[redacted]" in result


def test_sanitize_strips_control_characters() -> None:
    result = Provider.sanitize_connection_message("boom\x00\x07")

    assert result == "boom"


def test_sanitize_keeps_empty_message() -> None:
    assert Provider.sanitize_connection_message("") == ""


def test_sanitize_keeps_short_message_unchanged() -> None:
    assert Provider.sanitize_connection_message("boom") == "boom"


# --- real SDK message formats ----------------------------------------


async def test_sdk_html_403_reaches_us_unbranded() -> None:
    """Guard the assumption that an HTML body carries no status code.

    The challenge detection relies on the body itself: the SDK only
    prefixes "Error code: NNN" for JSON bodies, so an HTML body reaches
    us bare and classification runs on that raw text.
    """
    exc = await _sdk_models_error(403, CF_CHALLENGE_BODY, "text/html")

    assert "Error code" not in str(exc)

    assert classify_discovery_error(exc, str(exc)) == "blocked"
    assert "<script" not in Provider.sanitize_connection_message(str(exc))


async def test_sdk_json_403_is_authorization() -> None:
    exc = await _sdk_models_error(
        403,
        '{"error": {"message": "invalid key"}}',
        "application/json",
    )
    message = Provider.sanitize_connection_message(str(exc))

    assert classify_discovery_error(exc, message) == "authorization"


async def test_sdk_json_401_is_authentication() -> None:
    exc = await _sdk_models_error(
        401,
        '{"error": {"message": "no auth"}}',
        "application/json",
    )
    message = Provider.sanitize_connection_message(str(exc))

    assert classify_discovery_error(exc, message) == "authentication"


async def test_sdk_html_body_is_capped_for_persistence() -> None:
    """The persisted message is capped at the storage boundary."""
    exc = await _sdk_models_error(403, CF_CHALLENGE_BODY * 200, "text/html")

    message = Provider.truncate_connection_message(
        Provider.sanitize_connection_message(str(exc)),
    )

    assert len(message) <= MAX_CONNECTION_MESSAGE_LENGTH


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "authentication"),
        (403, "authorization"),
        (404, "unsupported"),
    ],
)
async def test_non_json_status_comes_from_the_exception(
    status: int,
    expected: str,
) -> None:
    """A non-JSON body carries no status text, so read it off the error.

    The SDK only prefixes "Error code: NNN" for JSON bodies; an HTML
    body reaches us bare, which used to leave these as unavailable.
    """
    body = (
        "<!DOCTYPE html><html><body>"
        f"<h1>{status}</h1><p>edge policy</p></body></html>"
    )
    exc = await _sdk_models_error(status, body, "text/html")

    assert getattr(exc, "status_code", None) == status
    assert "Error code" not in str(exc)

    message = Provider.sanitize_connection_message(str(exc))

    assert classify_discovery_error(exc, message) == expected


# --- stress guards ----------------------------------------------------


def test_html_summary_reads_only_a_bounded_prefix() -> None:
    """A hostile body must not be read in full.

    The text is remote-controlled, and the previous regex read all of
    it while degrading to quadratic on markup full of unterminated "<"
    (about 17s for 100 KB). This asserts the bound by its effect rather
    than by wall-clock time, which can flake on a loaded CI runner: a
    tail far beyond the limit must not change the result.
    """
    prefix = "<" * (100 * 1024)
    tail = "y" * (1024 * 1024)

    assert _summarize_html_page(prefix + tail) == _summarize_html_page(
        prefix,
    )
    assert len(_summarize_html_page(prefix)) <= _HTML_SUMMARY_INPUT_LIMIT


def test_html_summary_keeps_text_after_a_tagless_less_than() -> None:
    """A "<" with no following ">" must not swallow the rest."""
    page = "<html><body>502 Bad Gateway <"

    assert _summarize_html_page(page) == "502 Bad Gateway <"


def test_html_summary_keeps_sibling_text_separated() -> None:
    """Removing a tag must not join the text on either side of it."""
    page = (
        "<html><body><h1>403 Forbidden</h1>"
        "<p>Access denied by edge policy.</p></body></html>"
    )

    assert _summarize_html_page(page) == (
        "403 Forbidden Access denied by edge policy."
    )


def test_html_summary_drops_script_and_style_contents() -> None:
    page = (
        "<html><head><script>var a = 1; </script>"
        "<style>body { color: red }</style></head>"
        "<body>Visible</body></html>"
    )

    result = _summarize_html_page(page)

    assert result == "Visible"


@pytest.mark.parametrize(
    "block",
    [
        "<script>var a = 1;</script>",
        "<SCRIPT>var a = 1;</SCRIPT>",
        "<Script>var a = 1;</sCrIpT>",
        '<SCRIPT type="text/javascript">var a = 1;</SCRIPT>',
        "<style>body { color: red }</style>",
        "<STYLE>body { color: red }</STYLE>",
    ],
)
def test_html_summary_skips_blocks_case_insensitively(block: str) -> None:
    """Tag names are case-insensitive; details after them must survive.

    A case-sensitive closing-tag search used to miss ``</SCRIPT>`` and
    drop everything that followed it.
    """
    page = f"<html><body>before{block}<h1>502 Bad Gateway</h1></body></html>"

    result = _summarize_html_page(page)

    assert "502 Bad Gateway" in result


def test_html_summary_drops_an_unclosed_block_remainder() -> None:
    """An unclosed block makes the rest of the document its content."""
    page = "<html><body>before<script>var a = 1; </body></html>"

    assert _summarize_html_page(page) == "before"


@pytest.mark.parametrize(
    "content",
    [
        "if (a < b) { run(); }",
        "for (var i = 0; i < n; i++) {}",
        'var s = "a>b";',
        "// a < b comment",
        "if (x) { y(); } /* < > */",
    ],
)
def test_html_summary_keeps_text_after_script_markup(
    content: str,
) -> None:
    """A "<" inside a script must not be mistaken for a tag.

    Scanning for the next generic tag used to treat ``b) {...}</script``
    as one tag, lose the real closing tag, and drop every detail that
    followed.
    """
    page = f"<script>{content}</script><body>502 Bad Gateway</body>"

    assert "502 Bad Gateway" in _summarize_html_page(page)


def test_html_summary_keeps_text_after_style_markup() -> None:
    page = (
        '<style>a > b { content: "<" }</style>'
        + "<body>502 Bad Gateway</body>"
    )

    assert "502 Bad Gateway" in _summarize_html_page(page)


# --- bounded status extraction ---------------------------------------


def test_streaming_status_is_still_detected() -> None:
    exc = Exception("Streaming response failed: [503] upstream error")

    assert extract_status_code(exc) == 503


def test_streaming_status_scan_is_bounded() -> None:
    """The fallback must not scan a whole remote-controlled message.

    Scanning the full text blocked the event loop for about 0.4s on a
    32 MB message. This asserts the bound directly rather than by
    timing, because the unbounded scan is too fast to catch that way.
    """
    padding = "y" * 32_768
    exc = Exception(f"{padding} Streaming response failed: [503]")

    assert extract_status_code(exc) is None


def test_status_extraction_reuses_the_supplied_text() -> None:
    """A caller holding the message must not make the SDK render it again.

    The body may only be built inside ``__str__``, so rendering it a
    second time can be expensive for a large error.
    """
    renders: list[int] = []

    class CountingError(Exception):
        def __str__(self) -> str:
            renders.append(1)
            return "no marker here"

    exc = CountingError()

    assert (
        extract_status_code(
            exc,
            "Streaming response failed: [503]",
        )
        == 503
    )
    assert not renders

    # Without a supplied text the exception is rendered exactly once.
    assert extract_status_code(exc) is None
    assert len(renders) == 1


def test_sanitize_reads_only_a_bounded_prefix() -> None:
    """Remote text must never be read without a bound.

    Synchronous cleanup runs on the event loop, so an unbounded pass
    over a large body stalls every other task (about 3.2s for 32 MB
    before the bound). This asserts the bound by its effect rather than
    by wall-clock time, which can flake on a loaded CI runner: a tail
    far beyond the limit must not change the result.
    """
    prefix = "z" * _CONNECTION_MESSAGE_SCAN_LIMIT
    tail = "y" * (1024 * 1024)

    result = Provider.sanitize_connection_message(prefix + tail)

    assert result == Provider.sanitize_connection_message(prefix)
    assert len(result) <= _CONNECTION_MESSAGE_SCAN_LIMIT


def test_long_message_keeps_its_classification() -> None:
    """Markers past the persistence cap must still classify correctly."""
    long_prefix = "x" * (MAX_CONNECTION_MESSAGE_LENGTH + 10)

    not_found = classify_model_check(False, f"{long_prefix} model_not_found")
    unsupported = classify_model_check(
        False,
        f"{long_prefix} unsupported endpoint",
    )

    assert not_found.status == "model_not_found"
    assert not_found.retryable is False
    assert unsupported.status == "incompatible_api"
    assert unsupported.retryable is False


# --- full discovery path ---------------------------------------------


def _register_challenged_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProviderManager, OpenAIProvider]:
    """Register a custom provider whose upstream answers a challenge."""
    provider = OpenAIProvider(
        id="custom-wusrouter",
        name="WUSRouter",
        base_url="https://api.wusrouter.com/v1",
        api_key="sk-test",
        is_custom=True,
        chat_model="OpenAIChatModel",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text=CF_CHALLENGE_BODY,
            headers={"content-type": "text/html"},
        )

    def factory(timeout: float = 5) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=provider.base_url,
            api_key=provider.api_key,
            timeout=timeout,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
            ),
        )

    monkeypatch.setattr(provider, "_client", factory)
    manager = ProviderManager()
    manager.custom_providers[provider.id] = provider
    return manager, provider


async def test_discovery_reports_a_challenge_as_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce the reported failure against the real code path."""
    manager, provider = _register_challenged_provider(monkeypatch)

    result = await manager.discover_provider_models(
        provider.id,
        save=False,
    )

    assert result.success is False
    assert result.error_kind == "blocked"
    assert result.error == CHALLENGE_PAGE_MESSAGE
    assert "<script" not in (result.error or "")
    assert len(result.error or "") <= MAX_CONNECTION_MESSAGE_LENGTH


async def test_discovery_persists_a_readable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The saved provider config must not hold a raw response body."""
    manager, provider = _register_challenged_provider(monkeypatch)

    await manager.discover_provider_models(provider.id, save=True)

    stored = manager.get_provider(provider.id)

    assert stored is not None
    assert stored.models_last_sync_error == CHALLENGE_PAGE_MESSAGE
    assert "<script" not in (stored.models_last_sync_error or "")
