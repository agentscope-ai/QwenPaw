# -*- coding: utf-8 -*-
"""Tests for notification rule matcher."""

from qwenpaw.app.notifications.matcher import (
    event_matches_rules,
)
from qwenpaw.config.config import (
    NotificationConfig,
    NotificationRuleConfig,
    NotificationSourceToggles,
)


def _cfg(**overrides):
    """Build a NotificationConfig with sensible test defaults."""
    defaults = {
        "enabled": True,
        "sound": True,
        "min_interval_seconds": 5,
        "sources": NotificationSourceToggles(),
        "language": "en",
        "agent_ids": None,
        "rules": [],
    }
    defaults.update(overrides)
    return NotificationConfig(**defaults)


# ── Master switch ────────────────────────────────────────────────


class TestMasterSwitch:
    def test_disabled_blocks_everything(self):
        config = _cfg(enabled=False)
        event = {
            "source_type": "approval",
            "agent_id": "default",
        }
        assert event_matches_rules(event, config) is False

    def test_enabled_allows_matching_source(self):
        config = _cfg(enabled=True)
        event = {
            "source_type": "approval",
            "agent_id": "default",
        }
        assert event_matches_rules(event, config) is True


# ── Source toggles ───────────────────────────────────────────────


class TestSourceToggles:
    def test_approval_on(self):
        config = _cfg(
            sources=NotificationSourceToggles(approval=True),
        )
        event = {
            "source_type": "approval",
            "agent_id": "default",
        }
        assert event_matches_rules(event, config) is True

    def test_approval_off(self):
        config = _cfg(
            sources=NotificationSourceToggles(approval=False),
        )
        event = {
            "source_type": "approval",
            "agent_id": "default",
        }
        assert event_matches_rules(event, config) is False

    def test_cron_text_on(self):
        config = _cfg(
            sources=NotificationSourceToggles(cron_text=True),
        )
        event = {
            "source_type": "cron",
            "agent_id": "default",
            "payload": {"task_type": "text"},
        }
        assert event_matches_rules(event, config) is True

    def test_cron_text_off(self):
        config = _cfg(
            sources=NotificationSourceToggles(
                cron_text=False,
                cron_agent=False,
            ),
        )
        event = {
            "source_type": "cron",
            "agent_id": "default",
            "payload": {"task_type": "text"},
        }
        assert event_matches_rules(event, config) is False

    def test_cron_agent_on(self):
        config = _cfg(
            sources=NotificationSourceToggles(cron_agent=True),
        )
        event = {
            "source_type": "cron",
            "agent_id": "default",
            "payload": {"task_type": "agent"},
        }
        assert event_matches_rules(event, config) is True

    def test_cron_defaults_to_agent_type(self):
        """Cron event without task_type defaults to 'agent'."""
        config = _cfg(
            sources=NotificationSourceToggles(cron_agent=True),
        )
        event = {
            "source_type": "cron",
            "agent_id": "default",
            "payload": {},
        }
        assert event_matches_rules(event, config) is True

    def test_heartbeat_toggle(self):
        config = _cfg(
            sources=NotificationSourceToggles(heartbeat=False),
        )
        event = {
            "source_type": "heartbeat",
            "agent_id": "default",
        }
        assert event_matches_rules(event, config) is False

    def test_unknown_source_type_not_matched(self):
        config = _cfg()
        event = {
            "source_type": "unknown_type",
            "agent_id": "default",
        }
        assert event_matches_rules(event, config) is False


# ── Agent filter ─────────────────────────────────────────────────


class TestAgentFilter:
    def test_no_filter_allows_any_agent(self):
        config = _cfg(agent_ids=None)
        event = {
            "source_type": "approval",
            "agent_id": "agent-xyz",
        }
        assert event_matches_rules(event, config) is True

    def test_filter_allows_listed_agent(self):
        config = _cfg(agent_ids=["agent-a", "agent-b"])
        event = {
            "source_type": "approval",
            "agent_id": "agent-a",
        }
        assert event_matches_rules(event, config) is True

    def test_filter_blocks_unlisted_agent(self):
        config = _cfg(agent_ids=["agent-a"])
        event = {
            "source_type": "approval",
            "agent_id": "agent-c",
        }
        assert event_matches_rules(event, config) is False

    def test_filter_blocks_even_with_matching_rule(self):
        """Agent filter is applied before rules."""
        rule = NotificationRuleConfig(
            enabled=True,
            severities=["error"],
        )
        config = _cfg(
            agent_ids=["agent-a"],
            rules=[rule],
            sources=NotificationSourceToggles(
                approval=False,
                heartbeat=False,
                memory=False,
                skill_autoupdate=False,
                cron_text=False,
                cron_agent=False,
            ),
        )
        event = {
            "source_type": "cron",
            "agent_id": "agent-b",
            "severity": "error",
        }
        assert event_matches_rules(event, config) is False


# ── Advanced rules ───────────────────────────────────────────────


class TestAdvancedRules:
    def test_disabled_rule_skipped(self):
        rule = NotificationRuleConfig(
            enabled=False,
            severities=["error"],
        )
        config = _cfg(
            rules=[rule],
            sources=NotificationSourceToggles(
                approval=False,
                heartbeat=False,
                memory=False,
                skill_autoupdate=False,
                cron_text=False,
                cron_agent=False,
            ),
        )
        event = {
            "source_type": "cron",
            "agent_id": "default",
            "severity": "error",
        }
        assert event_matches_rules(event, config) is False

    def test_severity_rule_matches_unknown_source(self):
        """Advanced rules still fire for source types without a toggle."""
        rule = NotificationRuleConfig(
            enabled=True,
            severities=["error", "warning"],
        )
        config = _cfg(rules=[rule])
        event = {
            "source_type": "custom_plugin",
            "agent_id": "default",
            "severity": "error",
        }
        assert event_matches_rules(event, config) is True

    def test_severity_rule_blocked_when_toggle_off(self):
        """Advanced rules are skipped when source toggle is off."""
        rule = NotificationRuleConfig(
            enabled=True,
            severities=["error", "warning"],
        )
        config = _cfg(
            rules=[rule],
            sources=NotificationSourceToggles(
                cron_text=False,
                cron_agent=False,
            ),
        )
        event = {
            "source_type": "cron",
            "agent_id": "default",
            "severity": "error",
        }
        assert event_matches_rules(event, config) is False

    def test_severity_rule_no_match(self):
        rule = NotificationRuleConfig(
            enabled=True,
            severities=["error"],
        )
        config = _cfg(
            rules=[rule],
            sources=NotificationSourceToggles(
                approval=False,
                heartbeat=False,
                memory=False,
                skill_autoupdate=False,
                cron_text=False,
                cron_agent=False,
            ),
        )
        event = {
            "source_type": "cron",
            "agent_id": "default",
            "severity": "info",
        }
        assert event_matches_rules(event, config) is False

    def test_multi_field_rule_and_logic(self):
        """All non-None fields must match (AND)."""
        rule = NotificationRuleConfig(
            enabled=True,
            source_types=["custom_plugin"],
            severities=["error"],
        )
        config = _cfg(rules=[rule])
        event_match = {
            "source_type": "custom_plugin",
            "agent_id": "default",
            "severity": "error",
        }
        event_no_match = {
            "source_type": "custom_plugin",
            "agent_id": "default",
            "severity": "info",
        }
        assert event_matches_rules(event_match, config) is True
        assert event_matches_rules(event_no_match, config) is False

    def test_multiple_rules_or_logic(self):
        """Matching ANY enabled rule triggers notification."""
        rule1 = NotificationRuleConfig(
            enabled=True,
            source_types=["custom_a"],
        )
        rule2 = NotificationRuleConfig(
            enabled=True,
            event_types=["plugin_event"],
        )
        config = _cfg(rules=[rule1, rule2])
        event = {
            "source_type": "custom_b",
            "agent_id": "default",
            "event_type": "plugin_event",
        }
        assert event_matches_rules(event, config) is True

    def test_source_toggle_takes_priority(self):
        """Source toggles match before rules are checked."""
        config = _cfg(
            sources=NotificationSourceToggles(approval=True),
            rules=[],
        )
        event = {
            "source_type": "approval",
            "agent_id": "default",
        }
        assert event_matches_rules(event, config) is True
