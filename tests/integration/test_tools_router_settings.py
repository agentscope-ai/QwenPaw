# -*- coding: utf-8 -*-
"""Builtin tool enable/async-execution toggles and tool config.

Covers ``app/routers/tools.py`` beyond the listing that existing tests
touch: the per-tool enable toggle, the async-execution setting, the tool
config read/write pair, and the 404 branches for unknown tool names.

Each toggle is verified by reading the tool listing back and inspecting
the flag, and every test restores the original value in ``finally`` so a
disabled tool cannot leak into later tests in the session. The config
tests only use a non-sensitive key, so no secret is ever written.

API endpoints:
  - GET   /api/tools
  - PATCH /api/tools/{tool_name}/toggle
  - PATCH /api/tools/{tool_name}/async-execution
  - GET   /api/tools/{tool_name}/config
  - POST  /api/tools/{tool_name}/config
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)

# A read-only builtin that is safe to toggle: nothing else in the suite
# depends on it being enabled.
_TOOL = "get_current_time"
_ABSENT_TOOL = "integ_no_such_tool_6621"


def _tool_entry(app_server, tool_name: str) -> dict:
    """Return one tool's entry from the listing."""
    resp = app_server.api_request(
        "GET",
        "/api/tools",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    for item in resp.json():
        if item.get("name") == tool_name:
            return item
    raise AssertionError(f"tool {tool_name} not in listing")


# ============================ A. enable toggle =============================


@pytest.mark.integration
@pytest.mark.p1
def test_toggle_tool_flips_enabled_then_restores(app_server):
    """Toggling a tool flips its enabled flag in the listing.

    Test purpose:
      - Cover toggle_tool's config load / flip / save path and assert
        the change is observable through GET /api/tools, not just in the
        PATCH response.

    Test flow:
      1. Read the tool's current enabled value.
      2. PATCH toggle and assert both the response and the listing show
         the inverted value.
      3. PATCH again to restore the original value.
    """
    before = _tool_entry(app_server, _TOOL)["enabled"]
    first = app_server.api_request(
        "PATCH",
        f"/api/tools/{_TOOL}/toggle",
        timeout=_HTTP_TIMEOUT,
    )
    assert first.status_code == 200, first.text
    try:
        assert first.json()["enabled"] is (not before), first.json()
        assert _tool_entry(app_server, _TOOL)["enabled"] is (not before)
    finally:
        restore = app_server.api_request(
            "PATCH",
            f"/api/tools/{_TOOL}/toggle",
            timeout=_HTTP_TIMEOUT,
        )
        assert restore.status_code == 200, restore.text
    assert (
        _tool_entry(app_server, _TOOL)["enabled"] is before
    ), "toggle did not restore the original enabled state"


@pytest.mark.integration
@pytest.mark.p2
def test_toggle_unknown_tool_returns_404(app_server):
    """Toggling a tool that is not a builtin is a 404.

    Test purpose:
      - Cover toggle_tool's membership check against
        ``tools.builtin_tools``, which prevents writing a config entry
        for an arbitrary name.
    """
    resp = app_server.api_request(
        "PATCH",
        f"/api/tools/{_ABSENT_TOOL}/toggle",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower(), resp.text


# ========================= B. async-execution flag =========================


@pytest.mark.integration
@pytest.mark.p1
def test_async_execution_setting_roundtrip(app_server):
    """The async-execution flag persists and reads back.

    Test purpose:
      - Cover update_tool_async_execution, whose body field is embedded
        (``{"async_execution": ...}``) rather than a bare boolean.
    """
    before = _tool_entry(app_server, _TOOL).get("async_execution")
    target = not bool(before)
    resp = app_server.api_request(
        "PATCH",
        f"/api/tools/{_TOOL}/async-execution",
        json={"async_execution": target},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    try:
        assert resp.json().get("async_execution") is target, resp.json()
        listed = _tool_entry(app_server, _TOOL).get("async_execution")
        assert listed is target, listed
    finally:
        app_server.api_request(
            "PATCH",
            f"/api/tools/{_TOOL}/async-execution",
            json={"async_execution": bool(before)},
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_async_execution_unknown_tool_returns_404(app_server):
    """Setting async-execution on an unknown tool is a 404.

    Test purpose:
      - Cover this route's own membership check, separate from toggle's.
    """
    resp = app_server.api_request(
        "PATCH",
        f"/api/tools/{_ABSENT_TOOL}/async-execution",
        json={"async_execution": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_async_execution_requires_body_field(app_server):
    """Omitting the embedded body field is a validation error.

    Test purpose:
      - Cover the embedded-Body requirement; without it the handler
        would receive no value to persist.
    """
    resp = app_server.api_request(
        "PATCH",
        f"/api/tools/{_TOOL}/async-execution",
        json={},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text


# ============================== C. tool config =============================


@pytest.mark.integration
@pytest.mark.p1
def test_tool_config_write_then_read(app_server):
    """A written tool config is returned by the config read.

    Test purpose:
      - Cover update_tool_config and get_tool_config for a builtin with
        no plugin manifest, which is the path that skips the
        password-masking logic.

    Test flow:
      1. POST a config with a non-sensitive key.
      2. GET the config and assert the value is present.
      3. POST an empty config to clean up.
    """
    try:
        posted = app_server.api_request(
            "POST",
            f"/api/tools/{_TOOL}/config",
            json={"config": {"integ_probe_key": "integ-probe-value"}},
            timeout=_HTTP_TIMEOUT,
        )
        assert posted.status_code == 200, posted.text

        fetched = app_server.api_request(
            "GET",
            f"/api/tools/{_TOOL}/config",
            timeout=_HTTP_TIMEOUT,
        )
        assert fetched.status_code == 200, fetched.text
        body = fetched.json()
        assert isinstance(body, dict), body
        assert body.get("integ_probe_key") == "integ-probe-value", body
    finally:
        app_server.api_request(
            "POST",
            f"/api/tools/{_TOOL}/config",
            json={"config": {}},
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_tool_config_read_for_unknown_tool_is_empty(app_server):
    """Config for a tool with no stored entry is an empty mapping.

    Test purpose:
      - Cover get_tool_config's default when the registry has nothing
        for this name; it must return an object rather than 500.
    """
    resp = app_server.api_request(
        "GET",
        f"/api/tools/{_ABSENT_TOOL}/config",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {}, resp.json()


@pytest.mark.integration
@pytest.mark.p2
def test_tool_config_accepts_empty_body_as_clear(app_server):
    """A config POST with no config field clears the stored config.

    Test purpose:
      - ToolConfigUpdate defaults ``config`` to an empty mapping, so an
        empty body is a valid "reset this tool's config" request rather
        than a validation error. Assert the read-back is empty.
    """
    resp = app_server.api_request(
        "POST",
        f"/api/tools/{_TOOL}/config",
        json={},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    fetched = app_server.api_request(
        "GET",
        f"/api/tools/{_TOOL}/config",
        timeout=_HTTP_TIMEOUT,
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == {}, fetched.json()
