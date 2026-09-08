# -*- coding: utf-8 -*-
"""Integration tests for the skills-hub client internals.

Covers src/qwenpaw/agents/skill_system/hub.py (663 uncovered lines):
env-driven HTTP configuration, backoff computation, URL building,
conflict payload construction, cancellation hooks, GitHub response
cache management.
"""

# pylint: disable=protected-access,consider-using-from-import

from __future__ import annotations

import time

import pytest


# ------------------------------------------------------------------ #
# conflict payload
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_build_hub_conflict_payload() -> None:
    """Conflict payloads carry reason, skill name, and suggestion."""
    from qwenpaw.agents.skill_system.hub import _build_hub_conflict

    payload = _build_hub_conflict("my-skill")
    assert payload["reason"] == "conflict"
    assert payload["skill_name"] == "my-skill"
    assert payload["suggested_name"]
    assert payload["suggested_name"] != "my-skill"
    assert isinstance(payload["conflicts"], list)
    assert payload["conflicts"][0]["skill_name"] == "my-skill"
    assert "already exists" in payload["message"]


# ------------------------------------------------------------------ #
# env-driven HTTP configuration
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_hub_http_timeout_defaults(monkeypatch) -> None:
    """Timeout defaults apply when the env var is unset."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.delenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", raising=False)
    assert hub._hub_http_timeout() == 30.0


@pytest.mark.integration
@pytest.mark.p1
def test_hub_http_timeout_env_override(monkeypatch) -> None:
    """Valid env values override the timeout."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", "45")
    assert hub._hub_http_timeout() == 45.0


@pytest.mark.integration
@pytest.mark.p1
def test_hub_http_timeout_floor(monkeypatch) -> None:
    """Timeouts below the floor clamp up to 3 seconds."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", "1")
    assert hub._hub_http_timeout() == 3.0


@pytest.mark.integration
@pytest.mark.p1
def test_hub_http_timeout_invalid_falls_back(monkeypatch) -> None:
    """Unparseable values fall back to the default."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", "not-a-number")
    assert hub._hub_http_timeout() == 30.0


@pytest.mark.integration
@pytest.mark.p1
def test_hub_http_retries_defaults_and_bounds(monkeypatch) -> None:
    """Retry count defaults to 3 and never goes negative."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.delenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", raising=False)
    assert hub._hub_http_retries() == 3
    monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "7")
    assert hub._hub_http_retries() == 7
    monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "-2")
    assert hub._hub_http_retries() == 0


@pytest.mark.integration
@pytest.mark.p1
def test_hub_http_backoff_base_defaults_and_bounds(monkeypatch) -> None:
    """Backoff base defaults to 0.8 and clamps at 0.1."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.delenv(
        "QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE",
        raising=False,
    )
    assert hub._hub_http_backoff_base() == 0.8
    monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "0.01")
    assert hub._hub_http_backoff_base() == 0.1


@pytest.mark.integration
@pytest.mark.p1
def test_hub_http_backoff_cap_defaults_and_bounds(monkeypatch) -> None:
    """Backoff cap defaults to 6 and clamps at 0.5."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.delenv(
        "QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP",
        raising=False,
    )
    assert hub._hub_http_backoff_cap() == 6.0
    monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "0.1")
    assert hub._hub_http_backoff_cap() == 0.5


@pytest.mark.integration
@pytest.mark.p1
def test_compute_backoff_seconds_growth(monkeypatch) -> None:
    """Backoff doubles per attempt up to the cap."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.delenv(
        "QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE",
        raising=False,
    )
    monkeypatch.delenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", raising=False)
    first = hub._compute_backoff_seconds(1)
    second = hub._compute_backoff_seconds(2)
    later = hub._compute_backoff_seconds(20)
    assert first == 0.8
    assert second == 1.6
    assert later == 6.0  # capped


@pytest.mark.integration
@pytest.mark.p1
def test_github_cache_ttl_env(monkeypatch) -> None:
    """Cache TTL parses env values and clamps at zero."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.setenv("QWENPAW_GITHUB_CACHE_TTL", "120")
    assert hub._github_cache_ttl() == 120.0
    monkeypatch.setenv("QWENPAW_GITHUB_CACHE_TTL", "-5")
    assert hub._github_cache_ttl() == 0.0
    monkeypatch.delenv("QWENPAW_GITHUB_CACHE_TTL", raising=False)
    assert hub._github_cache_ttl() > 0


# ------------------------------------------------------------------ #
# URL builders
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_hub_base_url_default(monkeypatch) -> None:
    """Default hub base URL is the public hub."""
    import qwenpaw.agents.skill_system.hub as hub

    monkeypatch.delenv("QWENPAW_SKILLS_HUB_BASE_URL", raising=False)
    assert hub._hub_base_url() == "https://clawhub.ai"


@pytest.mark.integration
@pytest.mark.p1
def test_hub_paths_default(monkeypatch) -> None:
    """Default API paths target the v1 endpoints."""
    import qwenpaw.agents.skill_system.hub as hub

    for var in (
        "QWENPAW_SKILLS_HUB_SEARCH_PATH",
        "QWENPAW_SKILLS_HUB_VERSION_PATH",
        "QWENPAW_SKILLS_HUB_DETAIL_PATH",
        "QWENPAW_SKILLS_HUB_FILE_PATH",
    ):
        monkeypatch.delenv(var, raising=False)
    assert hub._hub_search_path() == "/api/v1/search"
    assert "{slug}" in hub._hub_version_path()
    assert hub._hub_detail_path() == "/api/v1/skills/{slug}"
    assert hub._hub_file_path().endswith("/file")


@pytest.mark.integration
@pytest.mark.p1
def test_join_url_normalizes_slashes() -> None:
    """URL joining normalizes boundary slashes."""
    import qwenpaw.agents.skill_system.hub as hub

    assert hub._join_url("https://x.com/", "/api/v1") == "https://x.com/api/v1"
    assert hub._join_url("https://x.com", "api/v1") == "https://x.com/api/v1"
    assert hub._join_url("https://x.com//", "//api") == "https://x.com/api"


# ------------------------------------------------------------------ #
# cancellation hooks
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_ensure_not_cancelled_no_checker() -> None:
    """Without a checker installed, the check is a no-op."""
    import qwenpaw.agents.skill_system.hub as hub

    hub._ensure_not_cancelled()  # must not raise


@pytest.mark.integration
@pytest.mark.p1
def test_with_cancel_checker_raises_when_cancelled() -> None:
    """A truthy checker triggers SkillImportCancelled."""
    import qwenpaw.agents.skill_system.hub as hub
    from qwenpaw.exceptions import SkillImportCancelled

    with hub._with_cancel_checker(lambda: True):
        with pytest.raises(SkillImportCancelled):
            hub._ensure_not_cancelled()


@pytest.mark.integration
@pytest.mark.p1
def test_with_cancel_checker_false_continues() -> None:
    """A falsy checker lets execution continue."""
    import qwenpaw.agents.skill_system.hub as hub

    with hub._with_cancel_checker(lambda: False):
        hub._ensure_not_cancelled()  # must not raise


@pytest.mark.integration
@pytest.mark.p1
def test_with_cancel_checker_broken_checker_ignored() -> None:
    """Checker exceptions other than cancel are ignored."""
    import qwenpaw.agents.skill_system.hub as hub

    def broken() -> bool:
        raise RuntimeError("checker bug")

    with hub._with_cancel_checker(broken):
        hub._ensure_not_cancelled()  # must not raise


# ------------------------------------------------------------------ #
# GitHub response cache
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_github_cache_set_get_prune() -> None:
    """Cache set/get round-trips and prune drops expired entries."""
    import qwenpaw.agents.skill_system.hub as hub

    key = f"test-key-{time.monotonic_ns()}"
    assert hub._github_cache_get(key) is None
    hub._github_cache_set(key, {"data": 1})
    assert hub._github_cache_get(key) == {"data": 1}
    assert hub._github_cached(key) == {"data": 1}

    # Cache timestamps use the monotonic clock; prune with a monotonic
    # "now" keeps fresh entries alive and must not raise.
    hub._github_cache_prune(now=time.monotonic())
    assert isinstance(hub._github_cache_get(key), dict)
