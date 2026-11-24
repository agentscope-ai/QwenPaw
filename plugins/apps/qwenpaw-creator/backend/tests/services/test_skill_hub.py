# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""The hub adapter borrows the host's downloader and never adds its own."""

from __future__ import annotations

import asyncio
import sys

import pytest

from services import skill_hub

pytestmark = pytest.mark.unit


class _Payload:
    """Stands in for the host's private ``_InstallPayload``."""

    name = "hub-skill"
    content = "---\nname: hub-skill\n---\n\n# Hub\n"
    source_url = "https://skills.sh/acme/skills/hub-skill"
    installed_from = "skills-sh"
    references = {"a.md": "1", "deep": {"b.md": "2", "c.md": "3"}}
    scripts = {"run.sh": "echo"}
    extra_files: dict = {}


@pytest.mark.parametrize(
    "url",
    (
        "",
        "skills.sh/acme/skills/hub-skill",
        "ftp://example.com/SKILL.md",
        "file:///etc/passwd",
        "https:///no-host",
        "https://user:secret@example.com/SKILL.md",
        "https://example.com/" + "a" * 3000,
    ),
)
def test_refused_urls_never_reach_the_fetcher(url, monkeypatch) -> None:
    """URL shape is decided locally, before anything is resolved or fetched."""

    def forbidden():
        raise AssertionError("the fetcher must not be resolved")

    monkeypatch.setattr(skill_hub, "_resolve_fetcher", forbidden)
    with pytest.raises(skill_hub.SkillHubUrlError):
        asyncio.run(skill_hub.fetch_skill_bundle(url))


def test_missing_host_hub_becomes_a_clean_refusal(monkeypatch) -> None:
    """A host without the hub fetch fails as 501 material, not a crash.

    ``sys.modules`` set to None makes the import itself raise, which is how a
    renamed or dropped private helper would look at request time.
    """

    monkeypatch.setitem(sys.modules, "qwenpaw.agents.skill_system.hub", None)
    with pytest.raises(skill_hub.SkillHubUnavailable):
        asyncio.run(
            skill_hub.fetch_skill_bundle(
                "https://skills.sh/acme/skills/hub-skill",
            ),
        )


def test_slow_market_becomes_a_timeout(monkeypatch) -> None:
    """The 90s budget is a stated refusal rather than a hung request."""

    async def slow(_bundle_url, _version, _target_name):
        await asyncio.sleep(1)
        return _Payload()

    monkeypatch.setattr(skill_hub, "_resolve_fetcher", lambda: slow)
    monkeypatch.setattr(skill_hub, "_HUB_IMPORT_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(skill_hub.SkillHubTimeout):
        asyncio.run(
            skill_hub.fetch_skill_bundle(
                "https://skills.sh/acme/skills/hub-skill",
            ),
        )


def test_bundle_is_normalised_and_attached_files_counted(monkeypatch) -> None:
    """Only SKILL.md travels on; the rest is counted, not written."""

    async def fetcher(_bundle_url, _version, _target_name):
        return _Payload()

    monkeypatch.setattr(skill_hub, "_resolve_fetcher", lambda: fetcher)
    bundle = asyncio.run(
        skill_hub.fetch_skill_bundle(
            "https://skills.sh/acme/skills/hub-skill",
        ),
    )
    assert bundle.name == "hub-skill"
    assert bundle.content == _Payload.content
    assert bundle.source_url == _Payload.source_url
    assert bundle.installed_from == "skills-sh"
    # references (3 leaves, one nested) + scripts (1).
    assert bundle.ignored_files == 4


def test_target_name_is_forwarded_to_the_host(monkeypatch) -> None:
    """Pinning the name stays the host's decision, not a second rule here."""

    seen: list[tuple] = []

    async def fetcher(bundle_url, version, target_name):
        seen.append((bundle_url, version, target_name))
        return _Payload()

    monkeypatch.setattr(skill_hub, "_resolve_fetcher", lambda: fetcher)
    asyncio.run(
        skill_hub.fetch_skill_bundle(
            "https://skills.sh/acme/skills/hub-skill",
            version="1.2.3",
            target_name="pinned-skill",
        ),
    )
    assert seen == [
        (
            "https://skills.sh/acme/skills/hub-skill",
            "1.2.3",
            "pinned-skill",
        ),
    ]
