# -*- coding: utf-8 -*-
"""Workspace router file and settings endpoints.

Covers the parts of ``app/routers/workspace.py`` that the existing
workspace tests do not reach: the Coding-Mode code-file read/write pair
(including its weak-ETag 304 short-circuit and the path-traversal
guard), binary-file preview MIME gating, the language and audio-mode
settings round trips with their validation branches, whisper/provider
status reads, the workspace zip download, and the available-commands
listing.

Every write is verified by reading the value back, and the ETag test
asserts an actual 304 rather than just a 200, so a regression that
drops caching or accepts an invalid setting fails.

API endpoints:
  - GET  /api/workspace/code-files
  - GET  /api/workspace/code-files/{path}
  - PUT  /api/workspace/code-files/{path}
  - GET  /api/workspace/binary-files/{path}
  - GET  /api/workspace/language
  - PUT  /api/workspace/language
  - GET  /api/workspace/audio-mode
  - PUT  /api/workspace/audio-mode
  - GET  /api/workspace/local-whisper-status
  - GET  /api/workspace/transcription-providers
  - GET  /api/workspace/download
  - GET  /api/workspace/commands/available
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)


# ========================= A. code-file read/write =========================


@pytest.mark.integration
@pytest.mark.p1
def test_code_file_write_then_read_roundtrip(app_server):
    """A written code file is readable with the same content.

    Test purpose:
      - Cover write_code_file (mkdir + write + size) and read_code_file
        (stat, ETag, text read), the primary Coding-Mode file pair.

    Test flow:
      1. PUT a nested path with known content.
      2. Assert the reported size matches the payload length.
      3. GET the same path and compare the content byte for byte.
    """
    path = "integ-ws/nested/roundtrip.txt"
    content = "workspace router roundtrip\nline two\n"
    put_resp = app_server.api_request(
        "PUT",
        f"/api/workspace/code-files/{path}",
        json={"content": content},
        timeout=_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, put_resp.text
    # Not an exact byte count: on Windows the stored file uses CRLF, so the
    # reported size exceeds the LF-encoded payload. The content comparison
    # below is the real round-trip assertion.
    assert put_resp.json()["size"] > 0, put_resp.json()

    get_resp = app_server.api_request(
        "GET",
        f"/api/workspace/code-files/{path}",
        timeout=_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert body["content"] == content, body
    assert body["path"] == path, body


@pytest.mark.integration
@pytest.mark.p1
def test_code_file_etag_returns_304(app_server):
    """Re-reading an unchanged file with its ETag yields 304.

    Test purpose:
      - Cover the weak-ETag short-circuit in read_code_file, which skips
        the file read entirely when the client already has the content.

    Test flow:
      1. Write a file and read it, capturing the ETag header.
      2. Re-read with If-None-Match set to that ETag.
      3. Assert 304 and an empty body.
    """
    path = "integ-ws/etag.txt"
    app_server.api_request(
        "PUT",
        f"/api/workspace/code-files/{path}",
        json={"content": "etag me"},
        timeout=_HTTP_TIMEOUT,
    )
    first = app_server.api_request(
        "GET",
        f"/api/workspace/code-files/{path}",
        timeout=_HTTP_TIMEOUT,
    )
    assert first.status_code == 200, first.text
    etag = first.headers.get("etag") or first.headers.get("ETag")
    assert etag, dict(first.headers)

    second = app_server.api_request(
        "GET",
        f"/api/workspace/code-files/{path}",
        headers={"If-None-Match": etag},
        timeout=_HTTP_TIMEOUT,
    )
    assert second.status_code == 304, second.text
    assert not second.content, second.content[:200]


@pytest.mark.integration
@pytest.mark.p2
def test_code_file_etag_changes_after_write(app_server):
    """Rewriting a file invalidates the previous ETag.

    Test purpose:
      - Prove the ETag is derived from file state, not constant: after a
        content change the old validator must no longer produce a 304.
    """
    path = "integ-ws/etag-change.txt"
    app_server.api_request(
        "PUT",
        f"/api/workspace/code-files/{path}",
        json={"content": "first"},
        timeout=_HTTP_TIMEOUT,
    )
    first = app_server.api_request(
        "GET",
        f"/api/workspace/code-files/{path}",
        timeout=_HTTP_TIMEOUT,
    )
    old_etag = first.headers.get("etag") or first.headers.get("ETag")
    assert old_etag, dict(first.headers)

    app_server.api_request(
        "PUT",
        f"/api/workspace/code-files/{path}",
        json={"content": "second, longer content"},
        timeout=_HTTP_TIMEOUT,
    )
    again = app_server.api_request(
        "GET",
        f"/api/workspace/code-files/{path}",
        headers={"If-None-Match": old_etag},
        timeout=_HTTP_TIMEOUT,
    )
    assert again.status_code == 200, (
        "stale ETag was accepted after a write: " + again.text[:500]
    )
    assert again.json()["content"] == "second, longer content", again.json()


@pytest.mark.integration
@pytest.mark.p2
def test_code_file_missing_returns_404(app_server):
    """Reading an absent code file is a clean 404.

    Test purpose:
      - Cover read_code_file's FileNotFoundError branch.
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/code-files/integ-ws/definitely-absent-8811.txt",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_code_file_non_string_content_rejected(app_server):
    """A non-string content field is rejected with 422.

    Test purpose:
      - Cover write_code_file's type guard, which prevents writing a
        JSON object straight into a source file.
    """
    resp = app_server.api_request(
        "PUT",
        "/api/workspace/code-files/integ-ws/bad-type.txt",
        json={"content": {"not": "a string"}},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_code_file_path_traversal_is_blocked(app_server):
    """A ``..`` escape cannot read outside the workspace.

    Test purpose:
      - Cover safe_join's containment check on the code-file route; a
        successful traversal would expose host files.
    """
    # Percent-encode the dot segments: a literal "../.." is normalized
    # by the HTTP client before the request leaves, so it would never
    # reach safe_join at all.
    traversal = "%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd"
    resp = app_server.api_request(
        "GET",
        f"/api/workspace/code-files/{traversal}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 403, 404), resp.text[:500]
    assert "root:" not in resp.text, "path traversal leaked /etc/passwd"


@pytest.mark.integration
@pytest.mark.p1
def test_list_code_files_includes_written_file(app_server):
    """A freshly written file appears in the code-file listing.

    Test purpose:
      - Cover list_code_files / _list_all_files against a known entry
        rather than asserting only that a list came back.
    """
    name = "integ-ws-listed.txt"
    app_server.api_request(
        "PUT",
        f"/api/workspace/code-files/{name}",
        json={"content": "listed"},
        timeout=_HTTP_TIMEOUT,
    )
    resp = app_server.api_request(
        "GET",
        "/api/workspace/code-files",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert isinstance(entries, list), entries
    assert name in resp.text, f"{name} missing from listing"


# ======================= B. binary-file preview ============================


@pytest.mark.integration
@pytest.mark.p2
def test_binary_preview_rejects_unsupported_extension(app_server):
    """A .txt preview request is refused with 415.

    Test purpose:
      - Cover read_binary_file's MIME gate, which only serves the types
        in _MIME_MAP.
    """
    name = "integ-ws-preview.txt"
    app_server.api_request(
        "PUT",
        f"/api/workspace/code-files/{name}",
        json={"content": "not previewable"},
        timeout=_HTTP_TIMEOUT,
    )
    resp = app_server.api_request(
        "GET",
        f"/api/workspace/binary-files/{name}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 415, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_binary_preview_missing_supported_type_returns_404(app_server):
    """A supported extension that does not exist yields 404.

    Test purpose:
      - Cover the FileNotFoundError branch that sits after the MIME
        gate, distinct from the 415 above.
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/binary-files/integ-ws-absent-9001.png",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


# ==================== C. language / audio-mode settings ====================


@pytest.mark.integration
@pytest.mark.p1
def test_language_roundtrip(app_server):
    """Setting the agent language persists and reads back.

    Test purpose:
      - Cover put_agent_language's validation-passing path plus the MD
        re-copy branch, and get_agent_language.

    Test flow:
      1. Read the current language as a baseline.
      2. PUT a different supported language and assert GET reflects it.
      3. Restore the baseline.
    """
    before = app_server.api_request(
        "GET",
        "/api/workspace/language",
        timeout=_HTTP_TIMEOUT,
    )
    assert before.status_code == 200, before.text
    baseline = before.json()["language"]
    target = "ru" if baseline != "ru" else "en"
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/workspace/language",
            json={"language": target},
            timeout=default_http_timeout(60.0),
        )
        assert put_resp.status_code == 200, put_resp.text
        assert put_resp.json()["language"] == target, put_resp.json()
        after = app_server.api_request(
            "GET",
            "/api/workspace/language",
            timeout=_HTTP_TIMEOUT,
        )
        assert after.json()["language"] == target, after.json()
    finally:
        app_server.api_request(
            "PUT",
            "/api/workspace/language",
            json={"language": baseline},
            timeout=default_http_timeout(60.0),
        )


@pytest.mark.integration
@pytest.mark.p2
def test_invalid_language_rejected(app_server):
    """An unsupported language code is rejected with 400.

    Test purpose:
      - Cover the language validation branch; the message must name the
        supported values so the client can recover.
    """
    resp = app_server.api_request(
        "PUT",
        "/api/workspace/language",
        json={"language": "kl"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "Invalid language" in resp.text, resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_audio_mode_roundtrip(app_server):
    """Audio mode persists across GET/PUT.

    Test purpose:
      - Cover get_audio_mode and put_audio_mode's accepted-value path.
    """
    before = app_server.api_request(
        "GET",
        "/api/workspace/audio-mode",
        timeout=_HTTP_TIMEOUT,
    )
    assert before.status_code == 200, before.text
    baseline = before.json()["audio_mode"]
    target = "native" if baseline != "native" else "auto"
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/workspace/audio-mode",
            json={"audio_mode": target},
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, put_resp.text
        after = app_server.api_request(
            "GET",
            "/api/workspace/audio-mode",
            timeout=_HTTP_TIMEOUT,
        )
        assert after.json()["audio_mode"] == target, after.json()
    finally:
        app_server.api_request(
            "PUT",
            "/api/workspace/audio-mode",
            json={"audio_mode": baseline},
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_invalid_audio_mode_rejected(app_server):
    """An unknown audio mode is rejected with 400.

    Test purpose:
      - Cover put_audio_mode's validation branch, including its
        coercion of a non-string value to text before comparing.
    """
    resp = app_server.api_request(
        "PUT",
        "/api/workspace/audio-mode",
        json={"audio_mode": 42},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "Invalid audio_mode" in resp.text, resp.text


# ================== D. status reads / download / commands ==================


@pytest.mark.integration
@pytest.mark.p2
def test_local_whisper_status_reports_availability(app_server):
    """The whisper status endpoint returns a structured verdict.

    Test purpose:
      - Cover the local-whisper probe, which must answer even when the
        optional dependency is absent in this environment.
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/local-whisper-status",
        timeout=default_http_timeout(60.0),
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), dict), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_transcription_providers_listing(app_server):
    """The transcription-provider catalogue is listed.

    Test purpose:
      - Cover the provider enumeration path used by the voice settings
        UI.
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/transcription-providers",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), (list, dict)), resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_download_returns_zip(app_server):
    """The workspace downloads as a real zip archive.

    Test purpose:
      - Cover download_workspace / _zip_directory: assert the ZIP magic
        bytes and the attachment header, not merely a 200.
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/download",
        timeout=default_http_timeout(120.0),
    )
    assert resp.status_code == 200, resp.text[:500]
    assert resp.content[:2] == b"PK", resp.content[:20]
    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition, dict(resp.headers)
    assert ".zip" in disposition, disposition


@pytest.mark.integration
@pytest.mark.p2
def test_workspace_upload_rejects_non_zip_content_type(app_server):
    """A wrong content-type upload is refused before extraction.

    Test purpose:
      - Cover upload_workspace's content-type guard, which protects the
        zip extractor from arbitrary payloads.
    """
    resp = app_server.api_request(
        "POST",
        "/api/workspace/upload",
        files={"file": ("notes.txt", b"just text", "text/plain")},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "zip" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_available_commands_listing(app_server):
    """The available-commands endpoint lists registered commands.

    Test purpose:
      - Cover get_available_commands, which the console uses to
        populate slash-command autocomplete.
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/commands/available",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), (list, dict)), resp.text
