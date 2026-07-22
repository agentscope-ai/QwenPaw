# -*- coding: utf-8 -*-
"""Codex-compatible pet atlas constants."""

CELL_WIDTH = 192
CELL_HEIGHT = 208
COLUMNS = 8
ROWS = 9
ATLAS_WIDTH = CELL_WIDTH * COLUMNS
ATLAS_HEIGHT = CELL_HEIGHT * ROWS

STATE_SPECS = {
    "idle": {"row": 0, "frames": 6, "dur": 280, "last": 480},
    "running-right": {"row": 1, "frames": 8, "dur": 120, "last": 220},
    "running-left": {"row": 2, "frames": 8, "dur": 120, "last": 220},
    "waving": {"row": 3, "frames": 4, "dur": 140, "last": 320},
    "jumping": {"row": 4, "frames": 5, "dur": 140, "last": 280},
    "failed": {"row": 5, "frames": 8, "dur": 150, "last": 300},
    "waiting": {"row": 6, "frames": 6, "dur": 150, "last": 300},
    "running": {"row": 7, "frames": 6, "dur": 120, "last": 220},
    "review": {"row": 8, "frames": 6, "dur": 150, "last": 320},
}

VALID_STATES = set(STATE_SPECS)

EVENT_TO_STATE = {
    "qwenpaw.startup": "waving",
    "qwenpaw.shutdown": "idle",
    "query.received": "jumping",
    "query.running": "running",
    "query.first_token": "running-right",
    "query.done": "waving",
    "tool.detected": "running",
    "tool.result": "review",
    "query.cancelled": "waiting",
    "query.error": "failed",
    "approval.pending": "review",
    "approval.approved": "running",
    "approval.denied": "idle",
    "approval.timed_out": "failed",
    "approval.resolved": "idle",
    "approval.bulk_cancel": "idle",
    "idle": "idle",
}


def state_for_event(
    event: str | None,
    requested_state: str | None = None,
) -> str:
    """Return the display state for a QwenPaw event payload."""
    if event and event in EVENT_TO_STATE:
        return EVENT_TO_STATE[event]
    if requested_state in VALID_STATES:
        return requested_state
    return "idle"
