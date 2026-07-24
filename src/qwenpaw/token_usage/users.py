# -*- coding: utf-8 -*-
"""Reserved user ids used by token usage attribution."""

# Calls made without any user context: scheduled tasks, heartbeat/mission
# runs, sub-agents, context compaction, …
SYSTEM_USER_ID = "system"

# Usage recorded before per-user attribution existed, or any residual between
# an entry's totals and the sum of its per-user buckets.
UNKNOWN_USER_ID = "unknown"

__all__ = ["SYSTEM_USER_ID", "UNKNOWN_USER_ID"]
