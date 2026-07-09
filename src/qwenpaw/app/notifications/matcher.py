# -*- coding: utf-8 -*-
"""Rule-based matcher for notification filtering."""

from __future__ import annotations

from typing import Any

from qwenpaw.config.config import NotificationConfig, NotificationRuleConfig


def event_matches_rules(
    event: dict[str, Any],
    config: NotificationConfig,
) -> bool:
    """Return True if *event* should trigger a system notification.

    Matching logic:
    1. If the event's source_type is toggled ON in config.sources AND
       the event's agent matches config.agent_ids filter -> notify.
    2. Otherwise, check advanced rules (OR any rule matches -> notify).
    """
    if not config.enabled:
        return False

    source_type = event.get("source_type", "")
    agent_id = event.get("agent_id", "default")

    # Check agent filter (applies to both source toggles and rules)
    if config.agent_ids is not None:
        if agent_id not in config.agent_ids:
            return False

    # Primary: simple source-type toggles
    if _source_toggled_on(source_type, event, config):
        return True

    # Fallback: advanced rules
    for rule in config.rules:
        if not rule.enabled:
            continue
        if _matches_rule(event, rule):
            return True

    return False


def _source_toggled_on(
    source_type: str,
    event: dict[str, Any],
    config: NotificationConfig,
) -> bool:
    """Check if the source_type is enabled in the simple toggles."""
    sources = config.sources
    if source_type == "cron":
        payload = event.get("payload") or {}
        task_type = payload.get("task_type", "agent")
        return sources.cron_text if task_type == "text" else sources.cron_agent
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
