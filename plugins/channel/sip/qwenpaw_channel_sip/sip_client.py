# -*- coding: utf-8 -*-
"""SIP outbound call management."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

FAILED_HANGUP_CAUSES = {
    "NO_ANSWER",
    "USER_BUSY",
    "CALL_REJECTED",
    "NO_USER_RESPONSE",
    "NETWORK_OUT_OF_ORDER",
    "DESTINATION_OUT_OF_ORDER",
    "NORMAL_TEMPORARY_FAILURE",
    "SUBSCRIBER_ABSENT",
    "UNALLOCATED_NUMBER",
    "INVALID_NUMBER_FORMAT",
    "RECOVERY_ON_TIMER_EXPIRE",
}


class CallFailedError(Exception):
    def __init__(
        self,
        cause: str,
        message: str = "",
    ) -> None:
        self.cause = cause
        super().__init__(
            message or f"Call failed: {cause}",
        )
