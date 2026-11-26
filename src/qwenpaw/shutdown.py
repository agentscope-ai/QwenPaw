# -*- coding: utf-8 -*-
"""Default shutdown budgets shared by workers, the application and the CLI."""

CHANNEL_SHUTDOWN_SECONDS = 18.0
HTTP_DRAIN_SECONDS = 5
# The workspace watchdog also covers imports, management and shutdown hooks.
WORKSPACE_SHUTDOWN_SECONDS = CHANNEL_SHUTDOWN_SECONDS + 12.0
# Allow signal delivery and process exit around the two server phases.
SERVER_EXIT_SECONDS = 3
SERVER_SHUTDOWN_SECONDS = (
    HTTP_DRAIN_SECONDS + WORKSPACE_SHUTDOWN_SECONDS + SERVER_EXIT_SECONDS
)
