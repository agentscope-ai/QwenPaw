# -*- coding: utf-8 -*-
"""Rule-based matcher for notification filtering."""

from __future__ import annotations

from typing import Any

from qwenpaw.config.config import NotificationConfig, NotificationRuleConfig


def event_matches_rules(
    event: dict[str, Any],
    config: NotificationConfig,
) -> bool:
    """Return True if *event* should trigger a notification.

    Matching logic:
    1. Master switch off -> never notify.
    2. Agent filter -> skip if agent not in allowlist.
    3. Source toggle ON -> notify.
    4. Source toggle OFF (explicitly managed type) -> block,
       advanced rules are NOT checked for this event.
    5. Unknown source type (no toggle) -> check advanced
       rules as fallback.
    """
    if not config.enabled:
        return False

    source_type = event.get("source_type", "")
    agent_id = event.get("agent_id", "default")

    if config.agent_ids is not None:
        if agent_id not in config.agent_ids:
            return False

    toggled = _source_toggled_on(source_type, event, config)
    if toggled is True:
        return True
    if toggled is False and _has_source_toggle(source_type):
        return False

    for rule in config.rules:
        if not rule.enabled:
            continue
        if _matches_rule(event, rule):
            return True

    return False


_MANAGED_SOURCE_TYPES = frozenset(
    {"cron", "approval", "heartbeat", "memory", "skill_autoupdate"},
)


def _has_source_toggle(source_type: str) -> bool:
    """Return True if *source_type* has a toggle in config."""
    return source_type in _MANAGED_SOURCE_TYPES


def _source_toggled_on(
    source_type: str,
    event: dict[str, Any],
    config: NotificationConfig,
) -> bool:
    """Check if the source_type is enabled in the toggles."""
    sources = config.sources
    if source_type == "cron":
        payload = event.get("payload") or {}
        task_type = payload.get("task_type", "agent")
        if task_type == "text":
            return sources.cron_text
        return sources.cron_agent
    mapping = {
        "approval": sources.approval,
        "heartbeat": sources.heartbeat,
        "memory": sources.memory,
        "skill_autoupdate": sources.skill_autoupdate,
    }
    return mapping.get(source_type, False)


def _matches_rule(event: dict[str, Any], rule: NotificationRuleConfig) -> bool:
    """Check if *event* satisfies all non-None filters of *rule* (AND)."""
    if rule.source_types is not None:
        if event.get("source_type") not in rule.source_types:
            return False

    if rule.severities is not None:
        if event.get("severity") not in rule.severities:
            return False

    if rule.event_types is not None:
        if event.get("event_type") not in rule.event_types:
            return False

    if rule.agent_ids is not None:
        if event.get("agent_id") not in rule.agent_ids:
            return False

    return True
