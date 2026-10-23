# -*- coding: utf-8 -*-
"""Offline stand-in for a vendor SDK, imported only by the process Driver."""

import os

PID = os.getpid()


class DeliveryError(RuntimeError):
    def __init__(self, reason_code, *, side_effect_possible, retryable=False):
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable
        super().__init__(reason_code)
