# -*- coding: utf-8 -*-
"""Adapter over the host QwenPaw Skills Hub, reusing the Skill Pool import.

The Skill Pane already imports skills from an uploaded zip. This module adds
the other half of the QwenPaw Skill Pool UX -- importing from a market URL --
by borrowing *only* the host's fetch-and-normalise step, the same one
``POST /skills/pool/import`` uses. Every URL scheme a market supports
(skills.sh, GitHub, LobeHub, ClawHub, ModelScope, SkillsMP, the QwenPaw
platform, ...) plus its package size caps and path sanitising come from the
host; nothing here networks on its own, so there is no second, weaker
downloader to audit and no new SSRF surface beyond what the Pool already
accepts.

Writing stays entirely in ``services.media_files.user_skills``: this module
returns the fetched SKILL.md text and never touches the data root, so the
duplicate-name and builtin-shadowing rules keep applying to hub imports
exactly as they do to a hand-created skill.

The host keeps this half of its install flow private, so the reference is
resolved lazily and a failure to resolve it becomes an actionable refusal
rather than a broken plugin.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from utils.logger import setup_logger

logger = setup_logger("services.skill_hub")

# The console budgets 90s for a hub install. Creator's import is a single
# synchronous request (like the Pool one), so it gets the same ceiling and
# then reports a timeout instead of hanging the caller.
_HUB_IMPORT_TIMEOUT_SECONDS = 90.0

# Upper bound for the submitted URL. It is stored as the skill's source link
# and echoed back to the client, so an unbounded URL is a log/response
# pollution vector; no real market URL approaches this length.
_MAX_URL_CHARS = 2048


class SkillHubUrlError(ValueError):
    """A submitted URL that must be refused before any request is made."""


class SkillHubUnavailable(RuntimeError):
    """The running QwenPaw build exposes no hub fetch entry point."""


class SkillHubTimeout(RuntimeError):
    """The hub fetch exceeded its time budget."""


@dataclass(frozen=True)
class HubBundle:
    """One normalised remote skill, held in memory only."""

    name: str
    content: str
    source_url: str
    installed_from: str
    ignored_files: int


def _count_tree_leaves(tree: Any) -> int:
    """Count files in a host-sanitised ``references``/``scripts`` tree."""

    if not isinstance(tree, dict):
        return 0
    total = 0
    for value in tree.values():
        if isinstance(value, dict):
            total += _count_tree_leaves(value)
        else:
            total += 1
    return total


def _validate_url(bundle_url: str) -> str:
    url = (bundle_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SkillHubUrlError("URL 需以 http:// 或 https:// 开头")
    if len(url) > _MAX_URL_CHARS:
        raise SkillHubUrlError(
            f"URL 超过 {_MAX_URL_CHARS} 字符上限",
        )
    if parsed.username or parsed.password:
        # Credentials here would land in server logs and in the skill's
        # stored source link, and no supported market needs them.
        raise SkillHubUrlError("URL 不允许携带账号密码")
    return url


def _resolve_fetcher() -> Any:
    try:
        from qwenpaw.agents.skill_system.hub import (
            _prepare_install_payload,
        )
    except Exception as exc:  # noqa: BLE001 - host layout, not our bug
        logger.warning("skills hub fetcher unavailable: %s", exc)
        raise SkillHubUnavailable(
            "当前 QwenPaw 运行时未提供技能中心（Skills Hub）取包能力，请改用 ZIP 上传或手动创建技能",
        ) from exc
    return _prepare_install_payload


async def fetch_skill_bundle(
    bundle_url: str,
    *,
    version: str = "",
    target_name: str | None = None,
) -> HubBundle:
    """Fetch and normalise one remote skill; nothing is written to disk.

    ``target_name`` is forwarded to the host so a caller can pin the skill
    name instead of inheriting whatever the remote bundle declares.
    """

    url = _validate_url(bundle_url)
    fetcher = _resolve_fetcher()
    try:
        payload = await asyncio.wait_for(
            fetcher(url, (version or "").strip(), target_name),
            timeout=_HUB_IMPORT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise SkillHubTimeout(
            f"从 URL 获取技能超时（{_HUB_IMPORT_TIMEOUT_SECONDS:.0f}s），请确认外网可访问后重试",
        ) from exc

    ignored = (
        _count_tree_leaves(payload.references)
        + _count_tree_leaves(payload.scripts)
        + _count_tree_leaves(payload.extra_files)
    )
    logger.info(
        "skills hub bundle fetched: name=%s origin=%s ignored=%d",
        payload.name,
        payload.installed_from,
        ignored,
    )
    return HubBundle(
        name=str(payload.name or ""),
        content=str(payload.content or ""),
        source_url=str(payload.source_url or url),
        installed_from=str(payload.installed_from or ""),
        ignored_files=ignored,
    )


__all__ = [
    "HubBundle",
    "SkillHubTimeout",
    "SkillHubUnavailable",
    "SkillHubUrlError",
    "fetch_skill_bundle",
]
