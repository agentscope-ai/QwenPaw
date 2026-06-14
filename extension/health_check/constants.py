# -*- coding: utf-8 -*-
"""Health Check shared constants."""

DEFAULT_HEALTH_FIX_ID = "ensure-working-dir"

# Fix ids exposed to the console repair action (subset of doctor fix allowlist).
CONSOLE_FIX_IDS = frozenset(
    {
        "ensure-working-dir",
        "ensure-workspace-dirs",
        "validate-all-jobs-json",
        "reconcile-workspace-skills",
        "seed-missing-agent-json",
        "reset-invalid-agent-json",
        "rebuild-console-npm",
    },
)

HIGH_RISK_FIX_IDS = frozenset(
    {
        "seed-missing-agent-json",
        "reset-invalid-agent-json",
        "rebuild-console-npm",
        "write-empty-jobs-json",
        "normalize-jobs-cron",
    },
)
