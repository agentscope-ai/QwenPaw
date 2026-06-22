# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
# -*- coding: utf-8 -*-
"""Cross-cutting defense integration tests — Sprint 3.4.

Covers (13 of 18 cases; auth=true cases are in test_auth_real.py):
- B. Concurrency (4)
- C. File size limits (2 — others duplicated in test_console_header.py)
- D. Unicode / shell metachar / long string (4)
- E. Service resilience (3)
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from helpers import (
    delete_agent_quietly,
    scoped,
)

_HTTP_TIMEOUT = 15.0


# ------------------------------------------------------------------ #
# B. Concurrency
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_concurrent_chat_creation_no_500(app_server) -> None:
    """Test purpose:
    - Verify firing N concurrent POST /api/chats requests does not
      produce 5xx errors. Each request must succeed (200) or be
      rejected with a clear 4xx, not 500.

    API endpoints:
    - POST /api/chats
    - DELETE /api/chats/{chat_id}
    """
    sess_id = "integ-concurrent-sess-01"
    bodies = [
        {
            "name": f"concurrent-{i}",
            "session_id": sess_id,
            "user_id": "integ-concurrent-user",
        }
        for i in range(5)
    ]

    def _post(body):
        return app_server.api_request(
            "POST",
            "/api/chats",
            json=body,
            timeout=_HTTP_TIMEOUT,
        )

    chat_ids: list[str] = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(_post, bodies))

    try:
        for resp in results:
            assert (
                resp.status_code < 500
            ), f"server error: {resp.status_code} {resp.text}"
            if resp.status_code == 200:
                cid = (resp.json() or {}).get("id")
                if cid:
                    chat_ids.append(cid)
    finally:
        for cid in chat_ids:
            try:
                app_server.api_request(
                    "DELETE",
                    f"/api/chats/{cid}",
                    timeout=_HTTP_TIMEOUT,
                )
            except Exception:
                pass


@pytest.mark.integration
@pytest.mark.p1
def test_concurrent_config_read_write_no_corruption(app_server) -> None:
    """Test purpose:
    - Verify N concurrent GET+PUT against /api/config/heartbeat
      do not corrupt config or return 5xx.

    API endpoints:
    - GET /api/config/heartbeat
    - PUT /api/config/heartbeat
    """
    # Read baseline once to use as PUT body.
    base_resp = app_server.api_request(
        "GET",
        "/api/config/heartbeat",
        timeout=_HTTP_TIMEOUT,
    )
    assert base_resp.status_code == 200, app_server.logs_tail()
    baseline = base_resp.json()

    def _do(i):
        if i % 2 == 0:
            return app_server.api_request(
                "GET",
                "/api/config/heartbeat",
                timeout=_HTTP_TIMEOUT,
            )
        return app_server.api_request(
            "PUT",
            "/api/config/heartbeat",
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(_do, range(10)))

    for resp in results:
        assert (
            resp.status_code < 500
        ), f"5xx during concurrent R/W: {resp.status_code} {resp.text}"

    # Final GET — config still valid.
    final = app_server.api_request(
        "GET",
        "/api/config/heartbeat",
        timeout=_HTTP_TIMEOUT,
    )
    assert final.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_concurrent_workspace_file_writes(app_server) -> None:
    """Test purpose:
    - Verify N concurrent PUTs to the SAME workspace file end up with a
      consistent state (no 5xx, last writer wins, file readable).

    API endpoints:
    - PUT /api/agents/{agentId}/workspace/files/{md_name}
    - GET /api/agents/{agentId}/workspace/files/{md_name}
    """
    md = "integ-concurrent-write.md"

    def _put(i):
        return app_server.api_request(
            "PUT",
            scoped("default", f"/workspace/files/{md}"),
            json={"content": f"contents-{i}"},
            timeout=_HTTP_TIMEOUT,
        )

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(_put, range(5)))

    for resp in results:
        assert (
            resp.status_code < 500
        ), f"5xx on workspace file PUT: {resp.status_code}"

    # File must be readable.
    get_resp = app_server.api_request(
        "GET",
        scoped("default", f"/workspace/files/{md}"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 200, app_server.logs_tail()
    body = get_resp.json()
    content = body if isinstance(body, str) else body.get("content")
    assert content and content.startswith(
        "contents-",
    ), f"unexpected content: {content!r}"


@pytest.mark.integration
@pytest.mark.p2
def test_concurrent_inbox_list_does_not_crash(app_server) -> None:
    """Test purpose:
    - Verify N concurrent GET /api/console/inbox/events do not return
      5xx — the inbox store's asyncio.Lock must serialize cleanly.

    API endpoints:
    - GET /api/console/inbox/events
    """

    def _get(_):
        return app_server.api_request(
            "GET",
            "/api/console/inbox/events",
            timeout=_HTTP_TIMEOUT,
        )

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_get, range(20)))

    for resp in results:
        assert (
            resp.status_code == 200
        ), f"inbox list crashed: {resp.status_code} {resp.text[:200]}"


# ------------------------------------------------------------------ #
# C. File size limits
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_upload_limit_endpoint_returns_configured_value(app_server) -> None:
    """Test purpose:
    - Verify GET /api/settings/upload-limit returns the configured
      QWENPAW_UPLOAD_MAX_SIZE_MB value (10 in conftest).

    API endpoints:
    - GET /api/settings/upload-limit
    """
    resp = app_server.api_request(
        "GET",
        "/api/settings/upload-limit",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    limit = body.get("upload_max_size_mb") or body.get("max_size_mb")
    assert limit == 10, f"expected 10, got {limit}; body: {body}"


@pytest.mark.integration
@pytest.mark.p2
def test_skill_upload_rejects_oversized_zip(app_server) -> None:
    """Test purpose:
    - Verify POST /api/skills/upload also enforces the 10MB upload limit
      (same check_upload_size path).

    API endpoints:
    - POST /api/skills/upload
    """
    big_payload = b"z" * (11 * 1024 * 1024)
    resp = app_server.api_request(
        "POST",
        "/api/skills/upload",
        files={"file": ("big.zip", big_payload, "application/zip")},
        timeout=30.0,
    )
    assert resp.status_code in {
        400,
        413,
    }, f"expected 400/413, got {resp.status_code}: {resp.text[:200]}"


# ------------------------------------------------------------------ #
# D. Unicode / shell metachar / long string
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_agent_with_cjk_emoji_name_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify creating an agent with a CJK + emoji name persists and
      GET roundtrips the name correctly.

    API endpoints:
    - POST /api/agents
    - GET  /api/agents
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_cjk_emoji"
    fancy_name = "测试代理 🚀✨"
    delete_agent_quietly(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "POST",
            "/api/agents",
            json={
                "id": agent_id,
                "name": fancy_name,
                "description": "中文描述 with emoji 🎉",
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 201, app_server.logs_tail()

        get_resp = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        body = get_resp.json()
        agents = body if isinstance(body, list) else body.get("agents", [])
        match = next(
            (a for a in agents if a.get("id") == agent_id),
            None,
        )
        assert match is not None, f"agent missing: {agents}"
        assert match.get("name") == fancy_name, match
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_chat_name_with_shell_metacharacters_safe(app_server) -> None:
    """Test purpose:
    - Verify a chat name containing shell metacharacters
      (``; rm -rf / && echo pwned``) is stored verbatim and does not
      cause command injection. Verify GET roundtrip.

    API endpoints:
    - POST /api/chats
    - GET  /api/chats/{chat_id}
    - DELETE /api/chats/{chat_id}
    """
    evil_name = "; rm -rf / && echo pwned $(whoami) `id`"
    resp = app_server.api_request(
        "POST",
        "/api/chats",
        json={
            "name": evil_name,
            "session_id": "integ-evil-sess",
            "user_id": "integ-evil-user",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    chat_id = resp.json()["id"]
    try:
        list_resp = app_server.api_request(
            "GET",
            "/api/chats",
            timeout=_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        body = list_resp.json()
        chats = body if isinstance(body, list) else body.get("chats", [])
        match = next(
            (c for c in chats if c.get("id") == chat_id),
            None,
        )
        assert match is not None, f"chat missing: {chats}"
        assert match.get("name") == evil_name, match
    finally:
        try:
            app_server.api_request(
                "DELETE",
                f"/api/chats/{chat_id}",
                timeout=_HTTP_TIMEOUT,
            )
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_file_unicode_content_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify writing a workspace markdown file with CJK + emoji content
      preserves bytes exactly on roundtrip.

    API endpoints:
    - PUT /api/agents/{agentId}/workspace/files/{md_name}
    - GET /api/agents/{agentId}/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}/workspace/files/{md_name}
    """
    md = "integ-unicode.md"
    content = "# 标题 🌏\n\n中文段落 with emoji 🎨🔥\n\nДобрый день\n"
    put_resp = app_server.api_request(
        "PUT",
        scoped("default", f"/workspace/files/{md}"),
        json={"content": content},
        timeout=_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()

    get_resp = app_server.api_request(
        "GET",
        scoped("default", f"/workspace/files/{md}"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 200, app_server.logs_tail()
    body = get_resp.json()
    got = body if isinstance(body, str) else body.get("content")
    # Server may strip trailing whitespace; compare without trailing newline.
    assert got.rstrip("\n") == content.rstrip(
        "\n",
    ), f"content mismatch:\nexpected:{content!r}\nactual:{got!r}"


@pytest.mark.integration
@pytest.mark.p2
def test_long_agent_name_handled(app_server) -> None:
    """Test purpose:
    - Verify a 1000-character agent name is either accepted (with
      truncation) or rejected with a clear 4xx — never 5xx.

    API endpoints:
    - POST /api/agents
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_long_name"
    long_name = "x" * 1000
    delete_agent_quietly(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "POST",
            "/api/agents",
            json={"id": agent_id, "name": long_name},
            timeout=_HTTP_TIMEOUT,
        )
        assert (
            resp.status_code < 500
        ), f"5xx on long name: {resp.status_code} {resp.text[:200]}"
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# E. Service resilience (config corruption)
# ------------------------------------------------------------------ #


def _config_path(app_server):
    return app_server.working_dir / "config.json"


def _read_baseline_config(app_server) -> bytes:
    """Snapshot config.json bytes for restoration after the test."""
    path = _config_path(app_server)
    return path.read_bytes() if path.exists() else b""


def _restore_config(app_server, baseline: bytes) -> None:
    path = _config_path(app_server)
    if baseline:
        path.write_bytes(baseline)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    # Force config cache eviction by touching mtime.
    if path.exists():
        os.utime(path, None)


@pytest.mark.integration
@pytest.mark.p1
def test_corrupted_config_recovered_via_get_version(app_server) -> None:
    """Test purpose:
    - Seed garbage into config.json and verify the app recovers (auto
      backup + defaults) and continues serving GET /api/version.

    Test flow:
    1. Snapshot config.json.
    2. Write '{not valid json' to config.json.
    3. GET /api/version — must return 200.
    4. Restore baseline config.
    """
    baseline = _read_baseline_config(app_server)
    path = _config_path(app_server)
    try:
        path.write_text("{not valid json")
        resp = app_server.api_request(
            "GET",
            "/api/version",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, (
            f"version failed after corruption: "
            f"{resp.status_code} {resp.text}"
        )
    finally:
        _restore_config(app_server, baseline)


@pytest.mark.integration
@pytest.mark.p2
def test_empty_config_falls_back_to_defaults(app_server) -> None:
    """Test purpose:
    - Truncate config.json to empty bytes; verify app still responds
      to public endpoints (falls back to defaults).

    Test flow:
    1. Snapshot config.json.
    2. Write empty bytes to config.json.
    3. GET /api/version — 200.
    4. Restore baseline.
    """
    baseline = _read_baseline_config(app_server)
    path = _config_path(app_server)
    try:
        path.write_bytes(b"")
        resp = app_server.api_request(
            "GET",
            "/api/version",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
    finally:
        _restore_config(app_server, baseline)


@pytest.mark.integration
@pytest.mark.p2
def test_config_with_trailing_comma_repaired(app_server) -> None:
    """Test purpose:
    - Seed config.json with trailing commas (invalid JSON, but
      repairable by ``json_repair``); verify app continues serving.

    Test flow:
    1. Snapshot config.json.
    2. Write '{"language": "zh",}' (trailing comma) to config.json.
    3. GET /api/version — 200.
    4. Restore baseline.
    """
    baseline = _read_baseline_config(app_server)
    path = _config_path(app_server)
    try:
        path.write_text('{"language": "zh",}')
        resp = app_server.api_request(
            "GET",
            "/api/version",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
    finally:
        _restore_config(app_server, baseline)
