# -*- coding: utf-8 -*-
"""Short-lived signals shared by session lifecycle consumers."""

SESSION_SAVE_SUCCEEDED_KEY = "qwenpaw.session_save_succeeded"
TRANSCRIPT_TURN_ID_CONTEXT_KEY = "_qwenpaw_transcript_turn_id"
TRANSCRIPT_RECORDING_READY_KEY = "_qwenpaw_transcript_recording_ready"
TURN_COMMIT_KEY = "_qwenpaw_turn_commit"

__all__ = [
    "SESSION_SAVE_SUCCEEDED_KEY",
    "TRANSCRIPT_TURN_ID_CONTEXT_KEY",
    "TRANSCRIPT_RECORDING_READY_KEY",
    "TURN_COMMIT_KEY",
]
